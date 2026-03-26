"""
otp_controller.py — OTP creation, verification, expiry
"""

import logging
from datetime import datetime, timezone

from supabase_client import create_otp_challenge, get_pending_otp, update_otp_status

logger = logging.getLogger(__name__)


def issue_otp(user_id: str, session_id: str) -> dict:
    """
    Create a PENDING OTP challenge for a MEDIUM-risk snapshot.
    Returns the inserted otp_challenges row.
    """
    otp_row = create_otp_challenge(user_id, session_id)
    logger.info(f"OTP issued | user={user_id} session={session_id} id={otp_row.get('id')}")
    return otp_row


def verify_otp(user_id: str, session_id: str, otp_code: str) -> dict:
    """
    Verify the OTP code submitted by the user.

    Returns:
      { "status": "OTP_VERIFIED" }                           — correct + not expired
      { "status": "SESSION_TERMINATED", "risk_level": "HIGH" } — wrong / expired
    """
    otp_row = get_pending_otp(user_id, session_id)

    if not otp_row:
        logger.warning(f"No PENDING OTP found | user={user_id} session={session_id}")
        return {"status": "SESSION_TERMINATED", "risk_level": "HIGH", "detail": "no_pending_otp"}

    otp_id      = otp_row["id"]
    stored_code = otp_row.get("otp_code", "")
    expires_at  = otp_row.get("expires_at")

    # Check expiry
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp_dt:
                update_otp_status(otp_id, "FAILED")
                logger.warning(f"OTP expired | user={user_id} session={session_id}")
                return {
                    "status":     "SESSION_TERMINATED",
                    "risk_level": "HIGH",
                    "detail":     "otp_expired",
                }
        except Exception as e:
            logger.error(f"Could not parse OTP expiry timestamp: {e}")

    # Check code
    if otp_code.strip() == stored_code.strip():
        update_otp_status(otp_id, "VERIFIED")
        logger.info(f"OTP verified | user={user_id} session={session_id}")
        return {"status": "OTP_VERIFIED"}
    else:
        update_otp_status(otp_id, "FAILED")
        logger.warning(f"OTP wrong code | user={user_id} session={session_id}")
        return {
            "status":     "SESSION_TERMINATED",
            "risk_level": "HIGH",
            "detail":     "wrong_otp_code",
        }