from dotenv import load_dotenv
load_dotenv()

import json
import time
import urllib.request
import urllib.parse

import anthropic

from language_config import LANGUAGE_CODES


# ---------------------------------------------------------------------------
# Claude prompt constants
# ---------------------------------------------------------------------------

_CLAUDE_SYSTEM = (
    "You are a senior political analyst for an Indian consulting firm. "
    "Read articles in any Indian language and summarize in English. "
    "Keep politician names in standard English transliteration. "
    "Party abbreviations only: BJP Congress AAP JD(S) DMK AIADMK NCP TMC SP BSP. "
    "If article content is sparse, infer from the headline. "
    "Never refuse. Never add preamble or commentary. Output only the 4 summary lines."
)

# Prefilling the assistant turn with this string forces Claude to continue
# the summary format rather than producing a refusal or preamble.
_PREFILL = "What happened:"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _detect_language(text: str) -> tuple[str, str]:
    """Detect language using langdetect. Returns (iso_code, display_name).
    Never raises — falls back to ("en", "English") on any failure so that
    the caller always receives a usable value.
    """
    # Guard: import failure means package not installed yet
    try:
        from langdetect import detect, DetectorFactory, LangDetectException
    except ImportError:
        return "en", "English"

    DetectorFactory.seed = 0            # deterministic results across runs

    clean = " ".join(text.split())
    if len(clean) < 20:                 # too short for reliable detection
        return "en", "English"

    try:
        code = detect(clean[:1000])
        name = LANGUAGE_CODES.get(code, code.capitalize())
        return code, name
    except Exception:                   # LangDetectException or any other error
        return "en", "English"


def _sarvam_translate(text: str, sarvam_api_key: str) -> str:
    """Translate text to English (en-IN) via Sarvam AI mayura:v1.
    Returns translated text, or original text if the call fails.
    """
    payload = json.dumps({
        "input":                text[:3000],
        "source_language_code": "auto",
        "target_language_code": "en-IN",
        "model":                "mayura:v1",
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.sarvam.ai/translate",
        data=payload,
        headers={
            "Content-Type":          "application/json",
            "api-subscription-key":  sarvam_api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    return data.get("translated_text") or data.get("output") or text


def _claude_summarize(article_text: str, anthropic_api_key: str) -> str:
    """Call Claude Haiku to produce a clean 4-line English summary.

    Uses an assistant prefill ("What happened:") so Claude is forced into the
    summary format and cannot produce refusal messages or preamble — the
    response must be a continuation of that line.
    """
    if not article_text.strip():
        return (
            "What happened: No article content available. "
            "Key people and party: Unknown. "
            "Location: Unknown. "
            "Political significance: Unable to summarize."
        )

    user_content = (
        "Summarize this Indian political news article in exactly 4 lines.\n\n"
        f"<article>\n{article_text[:2500]}\n</article>\n\n"
        "Output format — 4 lines, nothing else:\n"
        "What happened: ...\n"
        "Key people and party: ...\n"
        "Location: ...\n"
        "Political significance: ..."
    )

    client = anthropic.Anthropic(api_key=anthropic_api_key)
    for attempt in range(3):
        try:
            time.sleep(0.5)
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=350,
                system=_CLAUDE_SYSTEM,
                messages=[
                    {"role": "user",      "content": user_content},
                    {"role": "assistant", "content": _PREFILL},
                ],
            )
            # The API returns only the completion after the prefill, so
            # prepend the prefill to reconstruct the full first line.
            completion = msg.content[0].text.strip()
            full_text  = f"{_PREFILL} {completion}"
            for ch in ("*", "#"):
                full_text = full_text.replace(ch, "")
            return " ".join(full_text.split())
        except anthropic.RateLimitError:
            if attempt < 2:
                time.sleep(60)
            else:
                return "Summary unavailable — rate limit reached."
        except Exception:
            return "Summary unavailable."
    return "Summary unavailable."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_article(article_text: str, state: str, api_keys: dict) -> dict:
    """Detect language and produce a 4-line English political summary.

    Steps:
        1. langdetect to identify the article's language.
        2. If English  → skip to Step 4.
        3. If regional → note language name, proceed to Step 4.
        4. Call Claude Haiku (reads any language natively).
        5. If langdetect fails → call Sarvam AI (auto→en-IN), then Claude.

    Args:
        article_text: Combined headline + snippet text.
        state:        Indian state name (used for context, not filtering).
        api_keys:     Dict with keys "anthropic" and "sarvam".

    Returns:
        {
            "summary":            str,
            "original_language":  str,   # e.g. "English", "Kannada", "Unknown"
            "translation_method": str,   # "none" | "direct" | "sarvam"
        }
    """
    anthropic_key = api_keys.get("anthropic", "")
    sarvam_key    = api_keys.get("sarvam", "")

    text_for_claude    = article_text
    lang_name          = "English"
    translation_method = "none"

    # Step 1-3: detect language
    try:
        lang_code, lang_name = _detect_language(article_text)

        if lang_code == "en":
            # Step 2: already English — Claude reads it directly
            translation_method = "none"
        else:
            # Step 3: regional language — Claude still reads it directly
            translation_method = "direct"

    except Exception:
        # Step 5: langdetect failed — translate via Sarvam first
        lang_name = "Unknown"
        if sarvam_key:
            try:
                text_for_claude    = _sarvam_translate(article_text, sarvam_key)
                translation_method = "sarvam"
            except Exception:
                translation_method = "none"
        else:
            translation_method = "none"

    # Step 4: Claude Haiku produces the English summary
    summary = _claude_summarize(text_for_claude, anthropic_key)

    return {
        "summary":            summary,
        "original_language":  lang_name,
        "translation_method": translation_method,
    }
