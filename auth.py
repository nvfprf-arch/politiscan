import os
import json
import random
import datetime
import ssl
import urllib.request
import urllib.error


def generate_otp() -> str:
    """Return a random zero-padded 6-digit string."""
    return f"{random.randint(0, 999999):06d}"


def send_otp_email(to_email: str, otp: str) -> tuple[bool, str]:
    """Send the OTP to to_email via the Resend API.
    Returns (True, "") on success, (False, error_message) on any error.
    """
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        return False, "RESEND_API_KEY is not set."
    print(f"[auth] api_key prefix: '{api_key[:8]}'")

    from_email = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev").strip()
    print(f"[auth] from_email resolved to: '{from_email}'")
    payload = json.dumps({
        "from":    from_email,
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
            body = resp.read().decode("utf-8")
            print(f"[auth] Resend response: status={resp.status} body={body}")
            if resp.status in (200, 201):
                return True, ""
            err = f"Resend returned status {resp.status}: {body}"
            print(f"[auth] send_otp_email failed: {err}")
            return False, err
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        err = f"Resend HTTP {e.code}: {body}"
        print(f"[auth] send_otp_email failed: {err}")
        return False, err
    except Exception as e:
        err = str(e)
        print(f"[auth] send_otp_email failed: {err}")
        return False, err


def verify_otp(entered: str, stored: str, timestamp: datetime.datetime) -> bool:
    """Return True only if entered matches stored and fewer than 600 seconds
    have passed since timestamp.
    """
    if entered != stored:
        return False
    elapsed = (datetime.datetime.now() - timestamp).total_seconds()
    return elapsed < 600
