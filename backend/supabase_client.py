"""
supabase_client.py — All DB operations for Cognivex backend
"""

import os
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")

_client: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def get_client() -> Client:
    return _client


# ──────────────────────────────────────────────
# BEHAVIOR LOGS
# ──────────────────────────────────────────────

def insert_behavior_log(user_id: str, session_id: str,
                        key_events, mouse_events, scroll_events, summary) -> dict:
    """Insert a 30-sec snapshot into behavior_logs. Returns the inserted row."""
    row = {
        "user_id":      user_id,
        "session_id":   session_id,
        "key_events":   key_events,
        "mouse_events": mouse_events,
        "scroll_events":scroll_events,
        "summary":      summary,
    }
    resp = _client.table("behavior_logs").insert(row).execute()
    return resp.data[0] if resp.data else {}


def update_behavior_log_risk(log_id: str, risk_level: str, model_version: int | None):
    """Update risk_level and model_version on a behavior_logs row."""
    update = {"risk_level": risk_level}
    if model_version is not None:
        update["model_version"] = model_version
    _client.table("behavior_logs").update(update).eq("id", log_id).execute()


def get_session_logs(user_id: str, session_id: str) -> list[dict]:
    """Fetch all behavior_logs rows for a given session."""
    resp = (
        _client.table("behavior_logs")
        .select("*")
        .eq("user_id", user_id)
        .eq("session_id", session_id)
        .order("created_at", desc=False)
        .execute()
    )
    return resp.data or []


def get_low_risk_session_logs(user_id: str, session_id: str) -> list[dict]:
    """Fetch only LOW-risk behavior_logs rows for a given session."""
    resp = (
        _client.table("behavior_logs")
        .select("*")
        .eq("user_id", user_id)
        .eq("session_id", session_id)
        .eq("risk_level", "LOW")
        .order("created_at", desc=False)
        .execute()
    )
    return resp.data or []


def count_user_logs(user_id: str) -> int:
    """Total behavior_logs rows for a user."""
    resp = (
        _client.table("behavior_logs")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .execute()
    )
    return resp.count or 0


# ──────────────────────────────────────────────
# BEHAVIOR FEATURES
# ──────────────────────────────────────────────

def insert_behavior_features(user_id: str, session_id: str, features: dict) -> dict:
    """Insert one aggregated feature row at session end."""
    row = {
        "user_id":                user_id,
        "session_id":             session_id,
        "typing_speed":           features["typing_speed"],
        "backspace_ratio":        features["backspace_ratio"],
        "avg_keystroke_interval": features["avg_keystroke_interval"],
        "keystroke_variance":     features["keystroke_variance"],
        "avg_mouse_speed":        features["avg_mouse_speed"],
        "mouse_move_variance":    features["mouse_move_variance"],
        "scroll_frequency":       features["scroll_frequency"],
        "idle_ratio":             features["idle_ratio"],
        "total_windows":          features.get("total_windows", 1),
        "generated_at":           datetime.now(timezone.utc).isoformat(),
    }
    resp = _client.table("behavior_features").insert(row).execute()
    return resp.data[0] if resp.data else {}


def features_exist_for_session(user_id: str, session_id: str) -> bool:
    """Check if behavior_features already has a row for this session."""
    resp = (
        _client.table("behavior_features")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("session_id", session_id)
        .execute()
    )
    return (resp.count or 0) > 0


def count_user_features(user_id: str) -> int:
    """Total behavior_features rows for a user."""
    resp = (
        _client.table("behavior_features")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .execute()
    )
    return resp.count or 0


def fetch_latest_features(user_id: str, limit: int = 15) -> list[dict]:
    """Fetch the N most recent behavior_features rows for a user."""
    resp = (
        _client.table("behavior_features")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


# ──────────────────────────────────────────────
# MODEL METADATA  (includes adaptive thresholds)
# ──────────────────────────────────────────────

def get_model_metadata(user_id: str) -> dict | None:
    """Fetch the model metadata row for a user (one row per user)."""
    resp = (
        _client.table("model_metadata")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def upsert_model_metadata(
    user_id: str,
    model_bytes: bytes,
    model_version: int,
    total_sessions: int,
    last_trained_count: int,
    feature_columns: list[str] | None = None,
    medium_threshold: float | None = None,   # NEW — adaptive threshold
    high_threshold: float | None = None,     # NEW — adaptive threshold
    training_metrics: dict | None = None,
) -> dict:
    """
    Insert or update the model metadata for a user.
    Now persists adaptive thresholds computed from training score distribution.
    """
    existing = get_model_metadata(user_id)

    row = {
        "user_id":            user_id,
        "model_version":      model_version,
        "model_binary":       model_bytes.hex(),
        "feature_columns":    feature_columns or [],
        "total_sessions":     total_sessions,
        "last_trained_count": last_trained_count,
        "updated_at":         datetime.now(timezone.utc).isoformat(),
    }

    # Only include threshold columns if values were provided
    if medium_threshold is not None:
        row["medium_threshold"] = medium_threshold
    if high_threshold is not None:
        row["high_threshold"] = high_threshold
    if training_metrics is not None:
        row["training_metrics"] = training_metrics

    if existing:
        resp = (
            _client.table("model_metadata")
            .update(row)
            .eq("id", existing["id"])
            .execute()
        )
    else:
        resp = _client.table("model_metadata").insert(row).execute()

    return resp.data[0] if resp.data else {}


def get_model_bytes(user_id: str) -> tuple[bytes | None, int | None]:
    """Return (model_bytes, model_version) or (None, None)."""
    meta = get_model_metadata(user_id)
    if not meta:
        return None, None
    raw = meta.get("model_binary") or meta.get("model_bytes")
    if raw is None:
        return None, None
    return bytes.fromhex(raw), meta.get("model_version")


def get_adaptive_thresholds(user_id: str) -> tuple[float | None, float | None]:
    """
    Return (medium_threshold, high_threshold) stored from last training.
    Returns (None, None) if not yet computed (model not trained yet).
    """
    meta = get_model_metadata(user_id)
    if not meta:
        return None, None
    return meta.get("medium_threshold"), meta.get("high_threshold")


# ──────────────────────────────────────────────
# OTP CHALLENGES
# ──────────────────────────────────────────────

def create_otp_challenge(user_id: str, session_id: str) -> dict:
    """Create a new OTP challenge with 2-minute expiry."""
    now = datetime.now(timezone.utc)
    row = {
        "user_id":    user_id,
        "session_id": session_id,
        "otp_code":   "2323",
        "status":     "PENDING",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=2)).isoformat(),
    }
    resp = _client.table("otp_challenges").insert(row).execute()
    return resp.data[0] if resp.data else {}


def get_pending_otp(user_id: str, session_id: str) -> dict | None:
    """Get the latest PENDING OTP challenge for user+session."""
    resp = (
        _client.table("otp_challenges")
        .select("*")
        .eq("user_id", user_id)
        .eq("session_id", session_id)
        .eq("status", "PENDING")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def update_otp_status(otp_id: str, status: str):
    """Mark OTP as VERIFIED or FAILED."""
    _client.table("otp_challenges").update({"status": status}).eq("id", otp_id).execute()


# ──────────────────────────────────────────────
# SLIDING WINDOW CLEANUP
# ──────────────────────────────────────────────

def sliding_window_cleanup(user_id: str, max_logs: int = 500):
    """
    If user has > max_logs behavior_logs rows, delete the oldest ones
    and their corresponding behavior_features rows.
    Maintains referential integrity: features deleted before logs.
    """
    total = count_user_logs(user_id)
    if total <= max_logs:
        return

    excess = total - max_logs

    resp = (
        _client.table("behavior_logs")
        .select("id, session_id")
        .eq("user_id", user_id)
        .order("created_at", desc=False)
        .limit(excess)
        .execute()
    )
    old_rows = resp.data or []
    if not old_rows:
        return

    old_ids = [r["id"] for r in old_rows]
    old_session_ids = list({r["session_id"] for r in old_rows if r.get("session_id")})

    # Delete corresponding behavior_features first (referential integrity)
    if old_session_ids:
        _client.table("behavior_features").delete().in_("session_id", old_session_ids).execute()

    # Delete old behavior_logs
    _client.table("behavior_logs").delete().in_("id", old_ids).execute()


# ──────────────────────────────────────────────
# STATUS HELPER
# ──────────────────────────────────────────────

def get_user_status(user_id: str) -> dict:
    """Return model version, total sessions, last risk level, and current thresholds."""
    meta = get_model_metadata(user_id)
    total_sessions = count_user_features(user_id)

    resp = (
        _client.table("behavior_logs")
        .select("risk_level")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    last_risk = resp.data[0]["risk_level"] if resp.data else None

    return {
        "model_version":      meta["model_version"] if meta else None,
        "total_sessions":     total_sessions,
        "last_risk_level":    last_risk,
        # Surface the adaptive thresholds so you can inspect them via /status
        "medium_threshold":   meta.get("medium_threshold") if meta else None,
        "high_threshold":     meta.get("high_threshold") if meta else None,
    }