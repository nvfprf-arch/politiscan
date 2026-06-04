import os
import json
import random
import datetime
import ssl
import urllib.request


def generate_otp() -> str:
    """Return a random zero-padded 6-digit string."""
    return f"{random.randint(0, 999999):06d}"


def send_otp_email(to_email: str, otp: str) -> bool:
    """Send the OTP to to_email via the Resend API.
    Returns True on success, False on any error.
    """
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        return False

    payload = json.dumps({
        "from":    "onboarding@resend.dev",
        "to":      [to_email],
        "subject": "PolitiScan - Your Login Code",
        "text": (
            f"Your PolitiScan login code is: {otp}\n\n"
            "This code expires in 10 minutes.\n\n"
            "If you did not request this code, please ignore this email."
        ),
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )
    # Disable SSL certificate verification to work around Norton Antivirus
    # SSL/TLS inspection, which replaces server certs with its own self-signed
    # cert that no public CA bundle can verify.
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as resp:
            return resp.status in (200, 201)
    except Exception as e:
        print(f"[auth] send_otp_email failed: {e}")
        return False


def verify_otp(entered: str, stored: str, timestamp: datetime.datetime) -> bool:
    """Return True only if entered matches stored and fewer than 600 seconds
    have passed since timestamp.
    """
    if entered != stored:
        return False
    elapsed = (datetime.datetime.now() - timestamp).total_seconds()
    return elapsed < 600
