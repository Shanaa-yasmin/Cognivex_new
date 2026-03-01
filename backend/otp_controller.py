"""
otp_controller.py — OTP creation, verification, expiry
"""

import logging
from datetime import datetime, timezone

from supabase_client import (
    create_otp_challenge,
    get_pending_otp,
    update_otp_status,
    update_behavior_log_risk,
    get_session_logs,
)

logger = logging.getLogger(__name__)


def issue_otp(user_id: str, session_id: str) -> dict:
    """
    Create an OTP challenge for MEDIUM risk.
    Returns the OTP challenge record.
    """
    otp = create_otp_challenge(user_id, session_id)
    logger.info(f"OTP issued for user {user_id}, session {session_id}")
    return otp


def verify_otp(user_id: str, session_id: str, otp_code: str) -> dict:
    """
    Verify the OTP code submitted by the user.

    Returns:
        - OTP_VERIFIED if correct and not expired
        - SESSION_TERMINATED if wrong, expired, or no pending OTP
    """
    otp = get_pending_otp(user_id, session_id)

    if not otp:
        logger.warning(f"No pending OTP for user {user_id}, session {session_id}")
        return {"status": "SESSION_TERMINATED", "risk_level": "HIGH", "detail": "no_pending_otp"}

    # Check expiry
    expires_at_str = otp.get("expires_at")
    if expires_at_str:
        expires_at_str = expires_at_str.replace("Z", "+00:00")
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
        except ValueError:
            expires_at = datetime.fromisoformat(expires_at_str[:26]).replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        if now > expires_at:
            # Expired
            update_otp_status(otp["id"], "FAILED")
            _escalate_session(user_id, session_id)
            logger.warning(f"OTP expired for user {user_id}, session {session_id}")
            return {"status": "SESSION_TERMINATED", "risk_level": "HIGH", "detail": "otp_expired"}

    # Check code
    if otp_code == otp.get("otp_code"):
        update_otp_status(otp["id"], "VERIFIED")
        logger.info(f"OTP verified for user {user_id}, session {session_id}")
        return {"status": "OTP_VERIFIED"}
    else:
        # Wrong code
        update_otp_status(otp["id"], "FAILED")
        _escalate_session(user_id, session_id)
        logger.warning(f"OTP wrong code for user {user_id}, session {session_id}")
        return {"status": "SESSION_TERMINATED", "risk_level": "HIGH", "detail": "wrong_otp"}


def _escalate_session(user_id: str, session_id: str):
    """
    After OTP failure, update the latest behavior_logs row
    for this session to risk_level = HIGH.
    """
    logs = get_session_logs(user_id, session_id)
    if logs:
        # Update the most recent log entry
        latest = logs[-1]
        update_behavior_log_risk(latest["id"], "HIGH", latest.get("model_version"))
