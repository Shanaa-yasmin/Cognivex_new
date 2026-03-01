"""
model_engine.py — Train, predict, retrain, version, cache, threshold constants
"""

import io
import logging
from threading import Lock

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from supabase_client import (
    fetch_latest_features,
    get_model_bytes,
    get_model_metadata,
    upsert_model_metadata,
    count_user_features,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CONFIGURABLE THRESHOLDS
# ──────────────────────────────────────────────

THRESHOLD_LOW = -0.02       # score > -0.02         → LOW
THRESHOLD_MEDIUM = -0.07    # -0.07 < score <= -0.02 → MEDIUM
                            # score <= -0.07         → HIGH

ENROLLMENT_SESSIONS = 15    # Sessions needed before first model train
RETRAIN_INTERVAL = 20       # Retrain after every 20 new sessions

FEATURE_COLUMNS = [
    "typing_speed",
    "backspace_ratio",
    "avg_keystroke_interval",
    "keystroke_variance",
    "avg_mouse_speed",
    "mouse_move_variance",
    "scroll_frequency",
    "idle_ratio",
]

# ──────────────────────────────────────────────
# IN-MEMORY MODEL CACHE
# ──────────────────────────────────────────────
# { user_id: (model_version, model_object) }
_model_cache: dict[str, tuple[int, IsolationForest]] = {}
_cache_lock = Lock()


def _features_to_array(rows: list[dict]) -> np.ndarray:
    """Convert list of feature dicts to a 2D numpy array."""
    data = []
    for row in rows:
        data.append([float(row.get(col, 0.0)) for col in FEATURE_COLUMNS])
    return np.array(data)


def _serialize_model(model: IsolationForest) -> bytes:
    """Serialize model to bytes using joblib."""
    buf = io.BytesIO()
    joblib.dump(model, buf)
    return buf.getvalue()


def _deserialize_model(model_bytes: bytes) -> IsolationForest:
    """Deserialize model from bytes using joblib."""
    buf = io.BytesIO(model_bytes)
    return joblib.load(buf)


# ──────────────────────────────────────────────
# TRAIN / RETRAIN
# ──────────────────────────────────────────────

def train_model(user_id: str, feature_rows: list[dict], model_version: int,
                total_sessions: int) -> IsolationForest:
    """
    Train an IsolationForest on the given feature rows.
    Saves to model_metadata in Supabase and updates the in-memory cache.
    """
    X = _features_to_array(feature_rows)

    model = IsolationForest(
        n_estimators=100,
        contamination=0.1,
        random_state=42,
    )
    model.fit(X)

    model_bytes = _serialize_model(model)

    upsert_model_metadata(
        user_id=user_id,
        model_bytes=model_bytes,
        model_version=model_version,
        total_sessions=total_sessions,
        last_trained_count=total_sessions,
        feature_columns=FEATURE_COLUMNS,
    )

    with _cache_lock:
        _model_cache[user_id] = (model_version, model)

    logger.info(f"Model v{model_version} trained for user {user_id} with {len(feature_rows)} rows")
    return model


# ──────────────────────────────────────────────
# LOAD MODEL (lazy, from cache or Supabase)
# ──────────────────────────────────────────────

def load_model(user_id: str) -> tuple[IsolationForest | None, int | None]:
    """
    Return (model, model_version) from cache or Supabase.
    Returns (None, None) if no model exists.
    """
    # Check cache first
    with _cache_lock:
        cached = _model_cache.get(user_id)

    if cached:
        cached_version, cached_model = cached
        # Verify version matches Supabase
        meta = get_model_metadata(user_id)
        if meta and meta["model_version"] == cached_version:
            return cached_model, cached_version
        # Version mismatch — reload below

    # Load from Supabase
    model_bytes, model_version = get_model_bytes(user_id)
    if model_bytes is None:
        return None, None

    model = _deserialize_model(model_bytes)

    with _cache_lock:
        _model_cache[user_id] = (model_version, model)

    logger.info(f"Model v{model_version} loaded from Supabase for user {user_id}")
    return model, model_version


# ──────────────────────────────────────────────
# PREDICT / SCORE
# ──────────────────────────────────────────────

def score_to_risk(score: float) -> str:
    """Map Isolation Forest decision_function score to risk level."""
    if score > THRESHOLD_LOW:
        return "LOW"
    elif score > THRESHOLD_MEDIUM:
        return "MEDIUM"
    else:
        return "HIGH"


def predict_risk(model: IsolationForest, features: dict) -> tuple[str, float]:
    """
    Predict risk level for a single feature dict.
    Returns (risk_level, raw_score).
    """
    X = _features_to_array([features])
    raw_score = model.decision_function(X)[0]
    risk_level = score_to_risk(raw_score)
    return risk_level, float(raw_score)


# ──────────────────────────────────────────────
# SESSION-END LOGIC
# ──────────────────────────────────────────────

def handle_session_end_training(user_id: str) -> dict:
    """
    After a feature row is stored to behavior_features, decide whether to train/retrain.
    Returns a status dict.
    """
    total = count_user_features(user_id)

    if total < ENROLLMENT_SESSIONS:
        return {"status": "COLLECTING_DATA", "sessions_collected": total}

    # Check if model already exists
    meta = get_model_metadata(user_id)

    if total >= ENROLLMENT_SESSIONS and not meta:
        # First-time training (or retry after previous failure)
        rows = fetch_latest_features(user_id, limit=ENROLLMENT_SESSIONS)
        model = train_model(user_id, rows, model_version=1, total_sessions=total)
        return {"status": "MODEL_TRAINED", "model_version": 1}

    last_trained = meta.get("last_trained_count", 0)
    current_version = meta.get("model_version", 1)

    if (total - last_trained) >= RETRAIN_INTERVAL:
        # Retrain with latest 15 rows
        rows = fetch_latest_features(user_id, limit=ENROLLMENT_SESSIONS)
        new_version = current_version + 1
        model = train_model(user_id, rows, model_version=new_version, total_sessions=total)
        return {"status": "MODEL_RETRAINED", "model_version": new_version}

    return {"status": "SESSION_STORED"}


# ──────────────────────────────────────────────
# CACHE INVALIDATION
# ──────────────────────────────────────────────

def invalidate_cache(user_id: str):
    """Remove a user's model from in-memory cache."""
    with _cache_lock:
        _model_cache.pop(user_id, None)
