"""
main.py — FastAPI app & all routes for Cognivex behavioral biometrics backend
"""

import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from session_controller import handle_snapshot, handle_session_end, set_grace_period
from otp_controller import issue_otp, verify_otp
from supabase_client import (
    get_user_status,
    fetch_latest_features,
    get_model_metadata,
    count_user_features,
)

# ──────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# APP
# ──────────────────────────────────────────────
app = FastAPI(
    title="Cognivex Behavioral Biometrics API",
    version="2.0.0",
    description=(
        "Continuous behavioral authentication using Isolation Forest "
        "with per-user adaptive anomaly thresholds."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# REQUEST MODELS
# ──────────────────────────────────────────────

class SnapshotRequest(BaseModel):
    user_id:       str
    session_id:    str
    key_events:    list | None = None
    mouse_events:  list | None = None
    scroll_events: list | None = None
    summary:       dict | None = None


class SessionEndRequest(BaseModel):
    user_id:    str
    session_id: str


class VerifyOTPRequest(BaseModel):
    user_id:    str
    session_id: str
    otp_code:   str


# ──────────────────────────────────────────────
# CORE ROUTES
# ──────────────────────────────────────────────

@app.post("/session/snapshot")
async def session_snapshot(req: SnapshotRequest):
    """
    Receives a 30-sec behavioral snapshot.
    Stores → scores with adaptive thresholds → returns risk level.
    If MEDIUM risk, also creates an OTP challenge.
    """
    try:
        result = handle_snapshot(
            user_id=req.user_id,
            session_id=req.session_id,
            key_events=req.key_events    or [],
            mouse_events=req.mouse_events  or [],
            scroll_events=req.scroll_events or [],
            summary=req.summary       or {},
        )

        # MEDIUM risk — issue OTP challenge
        if result.get("risk_level") == "MEDIUM":
            otp = issue_otp(req.user_id, req.session_id)
            result["otp_challenge_id"] = otp.get("id")

        return result

    except Exception as e:
        logger.error(f"Snapshot error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/session/end")
async def session_end(req: SessionEndRequest):
    """
    Session ended — persist aggregated features to behavior_features.
    Applies first-train / retrain / store logic.
    """
    logger.info(f"=== /session/end | user={req.user_id} session={req.session_id} ===")
    try:
        result = handle_session_end(
            user_id=req.user_id,
            session_id=req.session_id,
        )
        logger.info(f"=== /session/end result: {result} ===")
        return result

    except Exception as e:
        logger.error(f"Session end error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/verify-otp")
async def verify_otp_route(req: VerifyOTPRequest):
    """
    Verify OTP submitted by the user after a MEDIUM-risk challenge.
    On success, starts a 10-minute grace period — no scoring during this window.
    """
    try:
        result = verify_otp(
            user_id=req.user_id,
            session_id=req.session_id,
            otp_code=req.otp_code,
        )

        # ── Grace period: start 10-min window after successful OTP verification ──
        if result.get("status") == "OTP_VERIFIED":
            set_grace_period(req.user_id)
            result["grace_period_minutes"] = 10
            logger.info(f"Grace period started for user={req.user_id} after OTP verification")

        return result

    except Exception as e:
        logger.error(f"OTP verify error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status/{user_id}")
async def user_status(user_id: str):
    """
    Returns model version, total sessions, last risk level,
    and the current adaptive thresholds for inspection.
    """
    try:
        return get_user_status(user_id)
    except Exception as e:
        logger.error(f"Status error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


# ──────────────────────────────────────────────
# ADMIN / DEBUG ROUTES
# ──────────────────────────────────────────────

@app.post("/admin/train/{user_id}")
async def admin_train(user_id: str):
    """
    Force a full retrain from the user's stored behavior_features rows.
    """
    from model_engine import train_model, ENROLLMENT_SESSIONS

    try:
        rows = fetch_latest_features(user_id, limit=ENROLLMENT_SESSIONS)
        if not rows:
            raise HTTPException(
                status_code=404,
                detail=f"No behavior_features rows found for user {user_id}",
            )

        meta            = get_model_metadata(user_id)
        current_version = meta["model_version"] if meta else 0
        new_version     = current_version + 1
        total           = count_user_features(user_id)

        train_model(user_id, rows, model_version=new_version, total_sessions=total)

        updated_meta = get_model_metadata(user_id)

        logger.info(f"Admin retrain complete | user={user_id} v{new_version}")
        return {
            "status":           "RETRAINED",
            "model_version":    new_version,
            "trained_on":       len(rows),
            "medium_threshold": updated_meta.get("medium_threshold") if updated_meta else None,
            "high_threshold":   updated_meta.get("high_threshold")   if updated_meta else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin train error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/debug/{user_id}")
async def admin_debug(user_id: str):
    """
    Show raw feature values and what score the current model would give
    each stored session.
    """
    from model_engine import (
        FEATURE_COLUMNS, _raw_row,
        ENROLLMENT_SESSIONS, load_model, score_to_risk,
    )

    try:
        rows = fetch_latest_features(user_id, limit=ENROLLMENT_SESSIONS)
        if not rows:
            return {"detail": "No feature rows found for this user"}

        model, model_version, medium_threshold, high_threshold = load_model(user_id)

        debug_rows = []
        for r in rows:
            raw = {col: r.get(col) for col in FEATURE_COLUMNS}

            score_info = None
            if model is not None:
                import numpy as np
                X     = np.array([_raw_row(r)])
                score = float(model.decision_function(X)[0])
                score_info = {
                    "score":      round(score, 4),
                    "risk_level": score_to_risk(score, medium_threshold, high_threshold),
                }

            debug_rows.append({
                "session_id": r.get("session_id"),
                "created_at": r.get("created_at"),
                "raw":        raw,
                "scoring":    score_info,
            })

        return {
            "user_id":          user_id,
            "total_rows":       len(rows),
            "model_version":    model_version,
            "medium_threshold": medium_threshold,
            "high_threshold":   high_threshold,
            "normalization":    "none — raw features passed to IsolationForest",
            "rows":             debug_rows,
        }

    except Exception as e:
        logger.error(f"Debug error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))