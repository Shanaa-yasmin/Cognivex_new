"""
model_engine.py — Train, predict, retrain, version, cache, adaptive thresholds

Training strategy: progressive sliding window with recency weighting.
  - Sessions 1-14:   collecting, no model
  - Session 15:      first train on all 15 sessions
  - Sessions 16-49:  retrain on all available sessions (growing window)
  - Sessions 50+:    retrain on latest 50 sessions (sliding window, stable cap)
  - Retrain trigger: every RETRAIN_INTERVAL new sessions after last train
  - Recency weight:  recent 20% of training rows get 2x sample weight

NOTE: Features are passed RAW (un-normalized) to IsolationForest.
IsolationForest is tree-based and invariant to monotone feature scaling,
so normalization provides no benefit and capping destroys variance information
(particularly for mouse_move_variance which routinely reaches 100k–1M px²/s²).
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
    get_adaptive_thresholds,
    upsert_model_metadata,
    count_user_features,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# TRAINING STRATEGY CONSTANTS
# ──────────────────────────────────────────────

ENROLLMENT_SESSIONS = 15    # Minimum sessions before first train
SLIDING_WINDOW_CAP  = 50    # Max sessions used for training at any time
RETRAIN_INTERVAL    = 10    # Retrain every 10 new sessions after last train
RECENCY_WEIGHT      = 2.0   # Most recent 20% of training rows get this
                            # sample weight multiplier vs older rows (1.0)

# ──────────────────────────────────────────────
# STATIC FALLBACK THRESHOLDS
# ──────────────────────────────────────────────
# Only used if adaptive thresholds haven't been computed yet.

_FALLBACK_MEDIUM_THRESHOLD = -0.02
_FALLBACK_HIGH_THRESHOLD   = -0.07

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
# IN-MEMORY CACHE
# ──────────────────────────────────────────────
# { user_id: (model_version, model_object, medium_threshold, high_threshold) }

_model_cache: dict[str, tuple[int, IsolationForest, float, float]] = {}
_cache_lock = Lock()


# ──────────────────────────────────────────────
# FEATURE HELPERS  (no normalization — raw values only)
# ──────────────────────────────────────────────

def _raw_row(row: dict) -> list[float]:
    """Extract raw feature values in FEATURE_COLUMNS order."""
    return [float(row.get(col, 0.0)) for col in FEATURE_COLUMNS]


def _features_to_array(rows: list[dict]) -> np.ndarray:
    """Convert list of feature dicts to raw 2D numpy array."""
    return np.array([_raw_row(row) for row in rows])


def _compute_sample_weights(n_rows: int) -> np.ndarray:
    """
    Assign recency-based sample weights for IsolationForest training.

    The most recent 20% of rows (newest sessions) get RECENCY_WEIGHT (2.0).
    Older rows get weight 1.0.

    fetch_latest_features() returns rows newest-first, so rows[0] is the
    most recent — we assign the higher weight there.
    """
    weights = np.ones(n_rows)
    recency_cutoff = max(1, int(n_rows * 0.20))
    weights[:recency_cutoff] = RECENCY_WEIGHT
    return weights


def _determine_training_window(total_sessions: int) -> int:
    """
    Return how many sessions to fetch for this training run.

    Progressive growth:
      total < SLIDING_WINDOW_CAP  → use all available sessions (growing window)
      total >= SLIDING_WINDOW_CAP → use SLIDING_WINDOW_CAP (sliding window)
    """
    return min(total_sessions, SLIDING_WINDOW_CAP)


def _serialize_model(model: IsolationForest) -> bytes:
    buf = io.BytesIO()
    joblib.dump(model, buf)
    return buf.getvalue()


def _deserialize_model(model_bytes: bytes) -> IsolationForest:
    buf = io.BytesIO(model_bytes)
    return joblib.load(buf)


# ──────────────────────────────────────────────
# ADAPTIVE THRESHOLD COMPUTATION
# ──────────────────────────────────────────────

def _compute_adaptive_thresholds(
    model: IsolationForest,
    X_train: np.ndarray,
) -> tuple[float, float]:
    """
    Compute MEDIUM and HIGH thresholds from the training score distribution.

    MEDIUM = 10th percentile of training scores
        → suspicious if score falls below 90% of the user's own normal behavior
    HIGH   = 2nd percentile of training scores
        → strong anomaly if below 98% of normal behavior

    Safety margin of 1.1x applied to avoid false positives on smaller datasets.
    Remove the margin once you consistently have 50+ training sessions.
    """
    train_scores = model.decision_function(X_train)

    raw_medium = float(np.percentile(train_scores, 10))
    raw_high   = float(np.percentile(train_scores, 2))

    safety_factor    = 1.1
    medium_threshold = raw_medium * safety_factor
    high_threshold   = raw_high   * safety_factor

    logger.info(
        f"Adaptive thresholds | "
        f"scores: min={train_scores.min():.4f} "
        f"p2={raw_high:.4f} p10={raw_medium:.4f} max={train_scores.max():.4f} | "
        f"MEDIUM<{medium_threshold:.4f}  HIGH<{high_threshold:.4f}"
    )

    return medium_threshold, high_threshold


# ──────────────────────────────────────────────
# TRAIN / RETRAIN
# ──────────────────────────────────────────────

def train_model(
    user_id: str,
    feature_rows: list[dict],
    model_version: int,
    total_sessions: int,
) -> IsolationForest:
    """
    Train an IsolationForest with recency-weighted samples on RAW features.
    Computes adaptive thresholds from the training score distribution.
    Saves model + thresholds to Supabase and updates in-memory cache.
    """
    X       = _features_to_array(feature_rows)
    weights = _compute_sample_weights(len(feature_rows))

    logger.info(
        f"Training model for user {user_id} | "
        f"samples={len(feature_rows)} | "
        f"window={'growing' if len(feature_rows) < SLIDING_WINDOW_CAP else 'sliding'} | "
        f"feature_means={X.mean(axis=0).round(3).tolist()}"
    )

    model = IsolationForest(
        n_estimators=200,
        contamination=0.1,
        max_samples="auto",
        random_state=42,
    )
    model.fit(X, sample_weight=weights)

    medium_threshold, high_threshold = _compute_adaptive_thresholds(model, X)

    train_scores = model.decision_function(X)
    model_bytes  = _serialize_model(model)

    upsert_model_metadata(
        user_id=user_id,
        model_bytes=model_bytes,
        model_version=model_version,
        total_sessions=total_sessions,
        last_trained_count=total_sessions,
        feature_columns=FEATURE_COLUMNS,
        medium_threshold=medium_threshold,
        high_threshold=high_threshold,
        training_metrics={
            "n_samples":         len(feature_rows),
            "window_type":       "growing" if len(feature_rows) < SLIDING_WINDOW_CAP else "sliding",
            "window_cap":        SLIDING_WINDOW_CAP,
            "score_min":         float(train_scores.min()),
            "score_max":         float(train_scores.max()),
            "score_mean":        float(train_scores.mean()),
            "medium_threshold":  medium_threshold,
            "high_threshold":    high_threshold,
            "normalization":     "none",
        },
    )

    with _cache_lock:
        _model_cache[user_id] = (model_version, model, medium_threshold, high_threshold)

    logger.info(
        f"Model v{model_version} trained | user={user_id} | "
        f"rows={len(feature_rows)} | "
        f"MEDIUM<{medium_threshold:.4f} HIGH<{high_threshold:.4f}"
    )
    return model


# ──────────────────────────────────────────────
# LOAD MODEL
# ──────────────────────────────────────────────

def load_model(
    user_id: str,
) -> tuple[IsolationForest | None, int | None, float, float]:
    """
    Return (model, version, medium_threshold, high_threshold).
    Cache-first, then Supabase. Returns (None, None, fallback, fallback)
    if no model exists yet.
    """
    with _cache_lock:
        cached = _model_cache.get(user_id)

    if cached:
        cached_version, cached_model, cached_medium, cached_high = cached
        meta = get_model_metadata(user_id)
        if meta and meta["model_version"] == cached_version:
            return cached_model, cached_version, cached_medium, cached_high

    model_bytes, model_version = get_model_bytes(user_id)
    if model_bytes is None:
        return None, None, _FALLBACK_MEDIUM_THRESHOLD, _FALLBACK_HIGH_THRESHOLD

    model = _deserialize_model(model_bytes)

    medium_threshold, high_threshold = get_adaptive_thresholds(user_id)
    if medium_threshold is None:
        medium_threshold = _FALLBACK_MEDIUM_THRESHOLD
        logger.warning(
            f"No adaptive thresholds for user {user_id} — "
            f"using fallback. Call /admin/train to recompute."
        )
    if high_threshold is None:
        high_threshold = _FALLBACK_HIGH_THRESHOLD

    with _cache_lock:
        _model_cache[user_id] = (model_version, model, medium_threshold, high_threshold)

    logger.info(
        f"Model v{model_version} loaded | user={user_id} | "
        f"MEDIUM<{medium_threshold:.4f} HIGH<{high_threshold:.4f}"
    )
    return model, model_version, medium_threshold, high_threshold


# ──────────────────────────────────────────────
# PREDICT / SCORE
# ──────────────────────────────────────────────

def score_to_risk(score: float, medium_threshold: float, high_threshold: float) -> str:
    """Map decision_function score to risk level using adaptive thresholds."""
    if score > medium_threshold:
        return "LOW"
    elif score > high_threshold:
        return "MEDIUM"
    else:
        return "HIGH"


def predict_risk(
    model: IsolationForest,
    features: dict,
    medium_threshold: float,
    high_threshold: float,
) -> tuple[str, float]:
    """
    Score a single feature dict using per-user adaptive thresholds.
    Features are passed raw (no normalization).
    Returns (risk_level, raw_score).
    """
    X          = _features_to_array([features])
    raw_score  = model.decision_function(X)[0]
    risk_level = score_to_risk(raw_score, medium_threshold, high_threshold)

    logger.info(
        f"Prediction | raw={X[0].round(3).tolist()} | "
        f"score={raw_score:.4f} | "
        f"MEDIUM<{medium_threshold:.4f} HIGH<{high_threshold:.4f} | "
        f"risk={risk_level}"
    )

    return risk_level, float(raw_score)


# ──────────────────────────────────────────────
# SESSION-END TRAINING LOGIC
# ──────────────────────────────────────────────

def handle_session_end_training(user_id: str) -> dict:
    """
    After a feature row is stored, decide whether to train or retrain.

    Training window progression:
      total < 15:              collecting data, no model yet
      total == 15 (no model):  first train on all 15 rows
      total > 15, model exists:
        - every RETRAIN_INTERVAL new sessions → retrain
        - fetch min(total, SLIDING_WINDOW_CAP) rows for training
        - so window grows 15→16→...→50 then slides at 50
    """
    total = count_user_features(user_id)

    if total < ENROLLMENT_SESSIONS:
        return {"status": "COLLECTING_DATA", "sessions_collected": total}

    meta = get_model_metadata(user_id)

    if not meta:
        window = _determine_training_window(total)
        rows   = fetch_latest_features(user_id, limit=window)
        train_model(user_id, rows, model_version=1, total_sessions=total)
        return {
            "status":        "MODEL_TRAINED",
            "model_version": 1,
            "trained_on":    len(rows),
            "window_type":   "growing",
        }

    last_trained    = meta.get("last_trained_count", 0)
    current_version = meta.get("model_version", 1)

    if (total - last_trained) >= RETRAIN_INTERVAL:
        window      = _determine_training_window(total)
        rows        = fetch_latest_features(user_id, limit=window)
        new_version = current_version + 1
        train_model(user_id, rows, model_version=new_version, total_sessions=total)

        window_type = "sliding" if window == SLIDING_WINDOW_CAP else "growing"
        return {
            "status":        "MODEL_RETRAINED",
            "model_version": new_version,
            "trained_on":    len(rows),
            "window_type":   window_type,
        }

    return {"status": "SESSION_STORED"}


# ──────────────────────────────────────────────
# CACHE INVALIDATION
# ──────────────────────────────────────────────

def invalidate_cache(user_id: str):
    """Remove a user's model from in-memory cache."""
    with _cache_lock:
        _model_cache.pop(user_id, None)