import os
import json
import random
import datetime
import urllib.request
import urllib.error


def generate_otp() -> str:
    """Return a random zero-padded 6-digit string."""
    return f"{random.randint(0, 999999):06d}"


def send_otp_email(to_email: str, otp: str) -> tuple[bool, str]:
    """DEBUG VERSION - prints raw Resend response."""
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    print(f"[auth] api_key present: {bool(api_key)}, prefix: '{api_key[:8]}'")

    payload = json.dumps({
        "from":    "noreply@politiscan.in",
        "to":      [to_email],
        "subject": "PolitiScan OTP Test",
        "text":    f"Your PolitiScan OTP is: {otp}",
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
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            print(f"[auth] Resend raw response: status={resp.status} body={body}")
            return (True, "") if resp.status in (200, 201) else (False, f"status {resp.status}: {body}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"[auth] Resend raw response: HTTP {e.code} body={body}")
        return False, f"HTTP {e.code}: {body}"
    except Exception as e:
        print(f"[auth] send_otp_email exception: {e}")
        return False, str(e)


def verify_otp(entered: str, stored: str, timestamp: datetime.datetime) -> bool:
    """Return True only if entered matches stored and fewer than 600 seconds
    have passed since timestamp.
    """
    if entered != stored:
        return False
    elapsed = (datetime.datetime.now() - timestamp).total_seconds()
    return elapsed < 600
