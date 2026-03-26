"""
session_controller.py — 30-sec snapshot pipeline + session-end orchestration
"""

import logging

from feature_extractor import extract_features, aggregate_features
from model_engine import load_model, predict_risk, handle_session_end_training
from supabase_client import (
    insert_behavior_log,
    update_behavior_log_risk,
    get_low_risk_session_logs,
    insert_behavior_features,
    sliding_window_cleanup,
    features_exist_for_session,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# PHASE 1: 30-SECOND SNAPSHOT
# ──────────────────────────────────────────────

def handle_snapshot(
    user_id:       str,
    session_id:    str,
    key_events:    list,
    mouse_events:  list,
    scroll_events: list,
    summary:       dict,
) -> dict:
    """
    Receives a 30-second behavioral snapshot:
      1. Store raw data in behavior_logs
      2. Extract 8 features in-memory (NOT persisted to behavior_features)
      3. Load model + per-user adaptive thresholds
      4. Score the snapshot
      5. Update risk_level in behavior_logs
      6. Return risk response
    """

    # Step 1 — persist raw snapshot
    log_row = insert_behavior_log(
        user_id=user_id,
        session_id=session_id,
        key_events=key_events,
        mouse_events=mouse_events,
        scroll_events=scroll_events,
        summary=summary,
    )
    log_id = log_row.get("id")

    # Step 2 — extract features in memory only
    features = extract_features(key_events, mouse_events, scroll_events, summary)

    if features is None:
        if log_id:
            update_behavior_log_risk(log_id, "LOW", None)
        return {
            "status":     "OK",
            "risk_level": "LOW",
            "detail":     "insufficient_data_for_scoring",
        }

    # Step 3 — load model and adaptive thresholds
    # load_model() now returns 4 values: (model, version, medium_threshold, high_threshold)
    model, model_version, medium_threshold, high_threshold = load_model(user_id)

    if model is None:
        if log_id:
            update_behavior_log_risk(log_id, "LOW", None)
        return {"status": "COLLECTING_DATA", "risk_level": "LOW"}

    # Step 4 — score using per-user adaptive thresholds
    risk_level, raw_score = predict_risk(
        model, features, medium_threshold, high_threshold
    )

    # Step 5 — update behavior_logs row
    if log_id:
        update_behavior_log_risk(log_id, risk_level, model_version)

    logger.info(
        f"Snapshot scored | user={user_id} risk={risk_level} "
        f"score={raw_score:.4f} model_v={model_version} "
        f"thresholds: M<{medium_threshold:.4f} H<{high_threshold:.4f}"
    )

    # Step 6 — return risk response
    if risk_level == "LOW":
        return {
            "status":        "OK",
            "risk_level":    "LOW",
            "model_version": model_version,
            "score":         round(raw_score, 4),
        }

    elif risk_level == "MEDIUM":
        # OTP challenge will be created by the route handler in main.py
        return {
            "status":        "OTP_REQUIRED",
            "risk_level":    "MEDIUM",
            "session_id":    session_id,
            "model_version": model_version,
            "score":         round(raw_score, 4),
        }

    else:
        # HIGH — immediate termination, no OTP
        return {
            "status":        "SESSION_TERMINATED",
            "risk_level":    "HIGH",
            "model_version": model_version,
            "score":         round(raw_score, 4),
        }


# ──────────────────────────────────────────────
# PHASE 2: SESSION END
# ──────────────────────────────────────────────

def handle_session_end(user_id: str, session_id: str) -> dict:
    """
    Session ended — aggregate LOW-risk snapshot features and persist to
    behavior_features. Then apply train / retrain / store logic.
    Idempotent: skips if features already stored for this session.
    """
    logger.info(f"SESSION END | user={user_id} session={session_id}")

    # Idempotency guard — prevents duplicate feature rows
    if features_exist_for_session(user_id, session_id):
        logger.info(f"Features already stored for session {session_id}, skipping.")
        return {"status": "ALREADY_PROCESSED"}

    # Step 1 — fetch only LOW-risk snapshots for this session
    low_risk_logs = get_low_risk_session_logs(user_id, session_id)
    logger.info(f"Found {len(low_risk_logs)} LOW-risk logs for session {session_id}")

    if not low_risk_logs:
        logger.warning(f"No LOW-risk logs for session {session_id}")
        return {
            "status": "NO_LOW_RISK_DATA",
            "detail": "No LOW-risk snapshots found for this session",
        }

    # Step 2 — extract features from each LOW-risk snapshot
    feature_list = []
    for log in low_risk_logs:
        feats = extract_features(
            log.get("key_events"),
            log.get("mouse_events"),
            log.get("scroll_events"),
            log.get("summary"),
        )
        if feats:
            feature_list.append(feats)

    if not feature_list:
        logger.warning(
            f"Could not extract features from {len(low_risk_logs)} "
            f"LOW-risk logs for session {session_id}"
        )
        return {
            "status": "NO_EXTRACTABLE_FEATURES",
            "detail": "Could not extract features from LOW-risk snapshots",
        }

    # Step 3 — aggregate into one row
    aggregated = aggregate_features(feature_list)
    if not aggregated:
        logger.error(f"Feature aggregation failed for session {session_id}")
        return {"status": "AGGREGATION_FAILED"}

    # Step 4 — persist to behavior_features
    logger.info(
        f"Inserting aggregated features for session {session_id} "
        f"({len(feature_list)} snapshots averaged)"
    )
    insert_behavior_features(user_id, session_id, aggregated)

    # Step 5 — apply training logic (first train / retrain / store)
    training_result = handle_session_end_training(user_id)

    # Step 6 — sliding window cleanup (keep max 500 behavior_logs rows)
    sliding_window_cleanup(user_id, max_logs=500)

    return training_result