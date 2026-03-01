"""
main.py — FastAPI app & all routes for Cognivex behavioral biometrics backend
"""

import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from session_controller import handle_snapshot, handle_session_end
from otp_controller import issue_otp, verify_otp
from supabase_client import get_user_status

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
    version="1.0.0",
    description="Continuous behavioral monitoring with Isolation Forest anomaly detection",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# REQUEST / RESPONSE MODELS
# ──────────────────────────────────────────────

class SnapshotRequest(BaseModel):
    user_id: str
    session_id: str
    key_events: list | None = None
    mouse_events: list | None = None
    scroll_events: list | None = None
    summary: dict | None = None


class SessionEndRequest(BaseModel):
    user_id: str
    session_id: str


class VerifyOTPRequest(BaseModel):
    user_id: str
    session_id: str
    otp_code: str


# ──────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────

@app.post("/session/snapshot")
async def session_snapshot(req: SnapshotRequest):
    """
    Receives a 30-sec behavioral snapshot.
    Stores to behavior_logs → scores → returns risk level.
    If MEDIUM risk, also creates an OTP challenge.
    """
    try:
        result = handle_snapshot(
            user_id=req.user_id,
            session_id=req.session_id,
            key_events=req.key_events or [],
            mouse_events=req.mouse_events or [],
            scroll_events=req.scroll_events or [],
            summary=req.summary or {},
        )

        # If MEDIUM risk, create OTP challenge
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
    Session ended — persist features to behavior_features.
    Apply 15/retrain logic.
    """
    logger.info(f"=== /session/end received: user={req.user_id}, session={req.session_id} ===")
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
    Verify OTP for MEDIUM risk challenge.
    """
    try:
        result = verify_otp(
            user_id=req.user_id,
            session_id=req.session_id,
            otp_code=req.otp_code,
        )
        return result

    except Exception as e:
        logger.error(f"OTP verify error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status/{user_id}")
async def user_status(user_id: str):
    """
    Returns model version, total sessions, last risk level.
    """
    try:
        return get_user_status(user_id)
    except Exception as e:
        logger.error(f"Status error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/admin/train/{user_id}")
async def admin_train(user_id: str):
    """Manual trigger for model training. For debugging/admin use."""
    from model_engine import handle_session_end_training
    try:
        result = handle_session_end_training(user_id)
        logger.info(f"Manual training result: {result}")
        return result
    except Exception as e:
        logger.error(f"Manual training error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
