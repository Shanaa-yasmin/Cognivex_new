"""
otp_controller.py — OTP creation, verification, expiry + email delivery via Gmail SMTP
"""
import os
import logging
import smtplib
from pathlib import Path
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

from supabase_client import create_otp_challenge, get_pending_otp, update_otp_status, get_user_email

logger = logging.getLogger(__name__)

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587
SMTP_USER     = os.environ.get("SMTP_USER")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
FROM_NAME     = "Your App Name"

print(f"DEBUG SMTP_USER: {repr(SMTP_USER)}")
print(f"DEBUG SMTP_PASSWORD: {repr(SMTP_PASSWORD)}")
# ── Email sender ──────────────────────────────────────────────────────────────

def send_otp_email(to_email: str, otp_code: str) -> bool:
    """
    Send OTP code to the user's email via Gmail SMTP.
    Returns True on success, False on failure.
    """
    subject = "Your OTP Verification Code"
    body_html = f"""
    <html><body>
      <p>Hello,</p>
      <p>Your verification code is:</p>
      <h2 style="letter-spacing:4px;">{otp_code}</h2>
      <p>This code expires in <strong>5 minutes</strong>. Do not share it with anyone.</p>
      <p>If you didn't request this, please ignore this email.</p>
    </body></html>
    """
    body_plain = f"Your OTP code is: {otp_code}\nExpires in 5 minutes. Do not share it."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{FROM_NAME} <{SMTP_USER}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(body_plain, "plain"))
    msg.attach(MIMEText(body_html,  "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, to_email, msg.as_string())
        logger.info(f"OTP email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send OTP email to {to_email}: {e}")
        return False


# ── OTP logic ─────────────────────────────────────────────────────────────────

def issue_otp(user_id: str, session_id: str) -> dict:
    otp_row = create_otp_challenge(user_id, session_id)
    otp_id  = otp_row.get("id")
    logger.info(f"OTP issued | user={user_id} session={session_id} id={otp_id}")

    email_sent = False
    try:
        user_email = get_user_email(user_id)
        print(f"DEBUG >>> user_email fetched: {user_email}")        # ← add this
        print(f"DEBUG >>> otp_code to send: {otp_row.get('otp_code')}")  # ← add this
        if user_email:
            email_sent = send_otp_email(user_email, otp_row["otp_code"])
            print(f"DEBUG >>> email_sent result: {email_sent}")     # ← add this
        else:
            logger.warning(f"No email found for user={user_id}, OTP not sent")
    except Exception as e:
        print(f"DEBUG >>> Exception: {e}")                          # ← add this
        logger.error(f"Error fetching email for user={user_id}: {e}")

    return {**otp_row, "email_sent": email_sent}


def verify_otp(user_id: str, session_id: str, otp_code: str) -> dict:
    """
    Verify the OTP code submitted by the user.

    Returns:
      { "status": "OTP_VERIFIED" }                              — correct + not expired
      { "status": "SESSION_TERMINATED", "risk_level": "HIGH" }  — wrong / expired
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