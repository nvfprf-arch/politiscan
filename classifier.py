from dotenv import load_dotenv
load_dotenv()

import json
import os
import time
import anthropic


def classify_political(headline: str, snippet: str, api_key: str) -> dict:
    """Classify a news item as POLITICAL or NOT_POLITICAL using Claude Haiku.

    Returns a dict with keys: classification, confidence, reason.
    """
    client = anthropic.Anthropic(api_key=api_key)
    user_message = f"Headline: {headline}\nDescription: {snippet}"

    raw = None
    for attempt in range(3):
        try:
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=150,
                system=(
                    "You are a political content classifier for an Indian political consulting firm. "
                    "Classify this news item as POLITICAL or NOT_POLITICAL. "
                    "POLITICAL means: involves politicians, political parties, elections, government policy, "
                    "legislation, political protests, governance, electoral politics, political appointments, "
                    "political scandals, government schemes, political alliances, government budgets, "
                    "political rallies, party internal matters. "
                    "NOT_POLITICAL means: sports, entertainment, crime not involving politicians, "
                    "business not involving government contracts, weather, lifestyle, general human interest. "
                    'Return only a JSON object with no extra text: '
                    '{"classification": "POLITICAL or NOT_POLITICAL", "confidence": 0.0 to 1.0, "reason": "one sentence max"}'
                ),
                messages=[{"role": "user", "content": user_message}],
            )
            raw = message.content[0].text.strip()
            break
        except anthropic.RateLimitError:
            if attempt < 2:
                time.sleep(60)
            else:
                return {"classification": "NOT_POLITICAL", "confidence": 0.0, "reason": "api error"}
        except Exception:
            return {"classification": "NOT_POLITICAL", "confidence": 0.0, "reason": "api error"}

    if raw is None:
        return {"classification": "NOT_POLITICAL", "confidence": 0.0, "reason": "api error"}

    try:
        # Strip markdown code fences if Claude wraps the JSON
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        result = json.loads(raw)
        return {
            "classification": str(result.get("classification", "NOT_POLITICAL")),
            "confidence": float(result.get("confidence", 0.0)),
            "reason": str(result.get("reason", "")),
        }
    except (json.JSONDecodeError, ValueError, KeyError):
        return {"classification": "NOT_POLITICAL", "confidence": 0.0, "reason": "parse error"}


if __name__ == "__main__":
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in environment.")
        raise SystemExit(1)

    samples = [
        {
            "label": "Clearly political",
            "headline": "BJP wins Karnataka bypolls, Congress demands recount",
            "snippet": "The Bharatiya Janata Party has won three out of four bypolls in Karnataka, "
                       "prompting the Congress party to demand a recount and alleging EVM tampering.",
        },
        {
            "label": "Clearly not political",
            "headline": "Virat Kohli scores century in Bangalore Test match",
            "snippet": "Indian cricket star Virat Kohli hit a brilliant century on day two of the "
                       "Test match against England at the M. Chinnaswamy Stadium.",
        },
        {
            "label": "Ambiguous",
            "headline": "Industrialist Ratan Tata meets Maharashtra CM for investment talks",
            "snippet": "Tata Group chairman Ratan Tata held a closed-door meeting with Maharashtra "
                       "Chief Minister to discuss potential investments in the state's infrastructure sector.",
        },
    ]

    for sample in samples:
        print(f"\n[{sample['label']}]")
        print(f"  Headline : {sample['headline']}")
        result = classify_political(sample["headline"], sample["snippet"], api_key)
        print(f"  Result   : {result['classification']}  (confidence: {result['confidence']:.2f})")
        print(f"  Reason   : {result['reason']}")
