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

def handle_snapshot(user_id: str, session_id: str,
                    key_events: list, mouse_events: list,
                    scroll_events: list, summary: dict) -> dict:
    """
    Receives a 30-second behavioral snapshot:
    1. Store raw data in behavior_logs
    2. Extract features in-memory (NOT persisted to behavior_features)
    3. Score against the user's model
    4. Update risk_level in behavior_logs
    5. Return risk response
    """
    # Step 1: Store raw snapshot
    log_row = insert_behavior_log(
        user_id=user_id,
        session_id=session_id,
        key_events=key_events,
        mouse_events=mouse_events,
        scroll_events=scroll_events,
        summary=summary,
    )
    log_id = log_row.get("id")

    # Step 2: Extract features in-memory
    features = extract_features(key_events, mouse_events, scroll_events, summary)

    if features is None:
        # Not enough data in this snapshot to extract features
        if log_id:
            update_behavior_log_risk(log_id, "LOW", None)
        return {"status": "OK", "risk_level": "LOW", "detail": "insufficient_data_for_scoring"}

    # Step 3: Load model and score
    model, model_version = load_model(user_id)

    if model is None:
        # No model yet — still collecting baseline sessions
        if log_id:
            update_behavior_log_risk(log_id, "LOW", None)
        return {"status": "COLLECTING_DATA", "risk_level": "LOW"}

    # Step 4: Predict risk
    risk_level, raw_score = predict_risk(model, features)

    # Step 5: Update behavior_logs row
    if log_id:
        update_behavior_log_risk(log_id, risk_level, model_version)

    logger.info(
        f"Snapshot scored for user {user_id}: risk={risk_level}, "
        f"score={raw_score:.4f}, model_v={model_version}"
    )

    # Build response based on risk level
    if risk_level == "LOW":
        return {
            "status": "OK",
            "risk_level": "LOW",
            "model_version": model_version,
            "score": round(raw_score, 4),
        }
    elif risk_level == "MEDIUM":
        # OTP challenge will be created by the route handler (otp_controller)
        return {
            "status": "OTP_REQUIRED",
            "risk_level": "MEDIUM",
            "session_id": session_id,
            "model_version": model_version,
            "score": round(raw_score, 4),
        }
    else:
        # HIGH risk — immediate session termination
        return {
            "status": "SESSION_TERMINATED",
            "risk_level": "HIGH",
            "model_version": model_version,
            "score": round(raw_score, 4),
        }


# ──────────────────────────────────────────────
# PHASE 2: SESSION END
# ──────────────────────────────────────────────

def handle_session_end(user_id: str, session_id: str) -> dict:
    """
    Session ended — aggregate LOW-risk features and persist to behavior_features.
    Then apply training/retraining logic.
    Idempotent: skips if features already stored for this session.
    """
    logger.info(f"SESSION END called for user={user_id}, session={session_id}")

    # Idempotency check — prevent duplicate feature rows
    if features_exist_for_session(user_id, session_id):
        logger.info(f"Features already stored for session {session_id}, skipping.")
        return {"status": "ALREADY_PROCESSED"}

    # Step 1: Fetch all LOW-risk behavior_logs for this session
    low_risk_logs = get_low_risk_session_logs(user_id, session_id)
    logger.info(f"Found {len(low_risk_logs)} LOW-risk logs for session {session_id}")

    if not low_risk_logs:
        logger.warning(f"NO LOW-risk logs found for session {session_id}")
        return {"status": "NO_LOW_RISK_DATA", "detail": "No LOW-risk snapshots found for this session"}

    # Step 2: Extract features from each LOW-risk snapshot
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
        logger.warning(f"Could not extract features from {len(low_risk_logs)} LOW-risk logs for session {session_id}")
        return {"status": "NO_EXTRACTABLE_FEATURES", "detail": "Could not extract features from LOW-risk snapshots"}

    # Step 3: Aggregate features into one row
    aggregated = aggregate_features(feature_list)
    if not aggregated:
        logger.error(f"Feature aggregation failed for session {session_id}")
        return {"status": "AGGREGATION_FAILED"}

    # Step 4: Persist to behavior_features
    logger.info(f"Inserting aggregated features for session {session_id} ({len(feature_list)} snapshots averaged)")
    insert_behavior_features(user_id, session_id, aggregated)

    # Step 5: Apply training logic (15 / retrain / store)
    training_result = handle_session_end_training(user_id)

    # Step 6: Sliding window cleanup
    sliding_window_cleanup(user_id, max_logs=500)

    return training_result
