from dotenv import load_dotenv
load_dotenv()

import json
import os
import time
import anthropic


TIER1_OUTLETS = {
    "the hindu", "ndtv", "indian express", "business standard", "mint",
    "times of india", "hindustan times", "the wire", "scroll", "republic tv",
    "india today",
}


def get_source_tier(source_name: str) -> str:
    """Return tier1, tier2, or tier3 based on outlet name."""
    if not source_name or not source_name.strip():
        return "tier3"
    if source_name.strip().lower() in TIER1_OUTLETS:
        return "tier1"
    return "tier2"


def score_importance(
    headline: str,
    content: str,
    source_name: str,
    published_iso: str,
    state: str,
    district: str,
    api_key: str,
) -> dict:
    """Score a political news item for importance using Claude Haiku.

    Returns a dict with keys:
        importance_score (int 1-10),
        primary_tag (str),
        one_line_reason (str),
        affects_client_region (bool)
    """
    client = anthropic.Anthropic(api_key=api_key)

    system_prompt = (
        "You are a senior political analyst for an Indian consulting firm. "
        "Score this political news item on a scale of 1 to 10 for political importance. "
        "Scoring guide: "
        "9-10 CRITICAL: major breaking development, cabinet change, election announcement, "
        "major policy shift, political crisis, government collapse, major alliance formed or broken. "
        "7-8 HIGH: significant development, senior leader statement on key issue, protest with 1000+ people, "
        "important policy notification, party candidate announced. "
        "5-6 MEDIUM: moderate development, routine political statement, minor party meeting, "
        "local government decision. "
        "3-4 LOW: press conference with no new information, political social media activity, "
        "routine inauguration. "
        "1-2 MINIMAL: repetition of known information, very local event with no broader implications. "
        "Assign one PRIMARY_TAG from: ELECTION, CABINET, POLICY, PROTEST, ALLIANCE, SCANDAL, "
        "APPOINTMENT, STATEMENT, PARTY_INTERNAL, GOVERNANCE. "
        f"State context: {state} and {district}. "
        "Return only a JSON object: "
        '{"importance_score": integer 1 to 10, "primary_tag": "TAG", '
        '"one_line_reason": "why this score", "affects_client_region": true or false, '
        '"report_type": "CONFIRMED or SPECULATIVE or ANALYTICAL", '
        '"speculation_signals": ["exact short phrase", ...], '
        '"type_confidence": 0.0 to 1.0}. '
        "Also classify the report_type as exactly one of: "
        "CONFIRMED if the article reports established facts, official announcements, "
        "on-record statements, or verified events with no journalistic hedging. "
        "SPECULATIVE if uncertain or unverified. Signals to look for: sources say, "
        "sources close to, it is learnt, expected to, likely to, may announce, could be, "
        "rumoured, unconfirmed, insiders suggest, in what could be, highly placed sources, "
        "there is speculation that, we are getting inputs that. "
        "ANALYTICAL if the article primarily interprets or provides opinion with no new confirmed facts. "
        "speculation_signals: list of exact short phrases from the article triggering the classification, "
        "empty list if CONFIRMED. "
        "type_confidence: float 0.0 to 1.0."
    )

    user_message = (
        f"Headline: {headline}\n"
        f"Content: {content}\n"
        f"Source: {source_name}\n"
        f"Published: {published_iso}"
    )

    raw = None
    for attempt in range(3):
        try:
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            raw = message.content[0].text.strip()
            break
        except anthropic.RateLimitError:
            if attempt < 2:
                time.sleep(60)
            else:
                return {
                    "importance_score": 5, "primary_tag": "STATEMENT",
                    "one_line_reason": "api error", "affects_client_region": False,
                    "report_type": "CONFIRMED", "speculation_signals": [], "type_confidence": 0.0,
                }
        except Exception:
            return {
                "importance_score": 5, "primary_tag": "STATEMENT",
                "one_line_reason": "api error", "affects_client_region": False,
                "report_type": "CONFIRMED", "speculation_signals": [], "type_confidence": 0.0,
            }

    if raw is None:
        return {
            "importance_score": 5, "primary_tag": "STATEMENT",
            "one_line_reason": "api error", "affects_client_region": False,
            "report_type": "CONFIRMED", "speculation_signals": [], "type_confidence": 0.0,
        }

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        result = json.loads(raw)
        return {
            "importance_score":      int(result.get("importance_score") or 5),
            "primary_tag":           str(result.get("primary_tag", "STATEMENT")),
            "one_line_reason":       str(result.get("one_line_reason", "")),
            "affects_client_region": bool(result.get("affects_client_region", False)),
            "report_type":           str(result.get("report_type", "CONFIRMED")),
            "speculation_signals":   list(result.get("speculation_signals", [])),
            "type_confidence":       float(result.get("type_confidence") or 0.0),
        }
    except (json.JSONDecodeError, ValueError, KeyError):
        return {
            "importance_score": 5, "primary_tag": "STATEMENT",
            "one_line_reason": "parse error", "affects_client_region": False,
            "report_type": "CONFIRMED", "speculation_signals": [], "type_confidence": 0.0,
        }


if __name__ == "__main__":
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in environment.")
        raise SystemExit(1)

    # --- source tier helper test (no API call) ---
    print("=== get_source_tier tests ===")
    tier_cases = [
        ("The Hindu",        "tier1"),
        ("NDTV",             "tier1"),
        ("Times of India",   "tier1"),
        ("Deccan Herald",    "tier2"),
        ("Local Daily",      "tier2"),
        ("",                 "tier3"),
        ("Unknown",          "tier2"),
    ]
    for name, expected in tier_cases:
        result = get_source_tier(name)
        status = "OK" if result == expected else f"FAIL (expected {expected})"
        print(f"  {name!r:25} -> {result}  {status}")

    # --- scoring tests ---
    print("\n=== score_importance tests ===")
    samples = [
        {
            "label": "CRITICAL — cabinet reshuffle",
            "headline": "Karnataka CM Siddaramaiah drops 5 ministers in major cabinet reshuffle",
            "content": "Chief Minister Siddaramaiah restructured the Karnataka cabinet today, dropping five senior ministers and inducting three new faces ahead of the 2025 municipal elections.",
            "source_name": "The Hindu",
            "published_iso": "2026-03-22T08:00:00Z",
            "state": "Karnataka",
            "district": "Bengaluru",
        },
        {
            "label": "LOW — routine inauguration",
            "headline": "MLA inaugurates new community hall in Mysuru village",
            "content": "Local MLA attended the inauguration ceremony of a newly built community hall in a village near Mysuru, thanking the state government for the funds.",
            "source_name": "Deccan Herald",
            "published_iso": "2026-03-22T09:30:00Z",
            "state": "Karnataka",
            "district": "Mysuru",
        },
        {
            "label": "HIGH — large protest",
            "headline": "Farmers block Bengaluru-Mysuru highway demanding loan waiver",
            "content": "Over 5,000 farmers gathered on the Bengaluru-Mysuru highway blocking traffic for six hours demanding the state government immediately implement the promised crop loan waiver scheme.",
            "source_name": "NDTV",
            "published_iso": "2026-03-22T07:15:00Z",
            "state": "Karnataka",
            "district": "Mandya",
        },
    ]

    for sample in samples:
        print(f"\n[{sample['label']}]")
        print(f"  Headline : {sample['headline']}")
        result = score_importance(
            headline=sample["headline"],
            content=sample["content"],
            source_name=sample["source_name"],
            published_iso=sample["published_iso"],
            state=sample["state"],
            district=sample["district"],
            api_key=api_key,
        )
        tier = get_source_tier(sample["source_name"])
        print(f"  Score    : {result['importance_score']}/10  |  Tag: {result['primary_tag']}  |  Source tier: {tier}")
        print(f"  Region?  : {result['affects_client_region']}")
        print(f"  Reason   : {result['one_line_reason']}")
