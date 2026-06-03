from feedback_store import get_recent_promotions, get_feedback_summary, should_generate_profile
from feedback_db import get_connection
import anthropic
import json
import datetime
import os
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-5"


def generate_client_profile(client_email):
    if not should_generate_profile(client_email):
        return None

    promotions = get_recent_promotions(client_email, limit=100)
    summary = get_feedback_summary(client_email)

    summary_text = (
        f"  total_promotions: {summary['total_promotions']}\n"
        f"  days_active: {summary['days_active']}\n"
        f"  avg_promoted_score: {summary['avg_promoted_score']}\n"
        f"  region_promotion_rate: {summary['region_promotion_rate']}%\n"
        f"  promotions_by_tag: {json.dumps(summary['promotions_by_tag'])}\n"
        f"  promotions_by_source: {json.dumps(summary['promotions_by_source'])}\n"
        f"  low_score_promotions_count: {len(summary['low_score_promotions'])}"
    )

    promotion_lines = []
    for p in promotions:
        headline = (p.get("article_headline") or "").replace("\n", " ")
        tag = p.get("primary_tag") or "unknown"
        score = p.get("original_score")
        source = p.get("source_name") or "unknown"
        region = p.get("affects_region", 0)
        promotion_lines.append(
            f"  headline={headline!r} tag={tag} score={score} source={source} region={region}"
        )
    promotions_text = "\n".join(promotion_lines)

    system_prompt = (
        "You are an AI analyst studying how a political consultant uses a news tool. "
        "Your job is to identify what types of political news this specific client values "
        "that a general importance model underestimates. "
        "Return only a valid JSON object with no other text."
    )

    user_message = (
        f"Here is the feedback data for client {client_email}. "
        f"They have promoted {summary['total_promotions']} articles over "
        f"{summary['days_active']} days that the AI scored too low.\n\n"
        f"Aggregate statistics:\n{summary_text}\n\n"
        f"Recent promotions list (headline, tag, original_score, source, affects_region):\n"
        f"{promotions_text}\n\n"
        "Analyse this data and return a JSON profile with exactly these keys:\n"
        "  preferred_tags: list of up to 4 tag strings this client values above default\n"
        "  preferred_sources: list of up to 6 source names this client consistently promotes\n"
        "  region_weight_boost: float between 1.0 and 2.0 where 1.0 means no boost and 2.0 means double weight for regional articles\n"
        "  score_floor: integer minimum score this client seems to care about even when AI scores lower\n"
        "  tag_multipliers: dict mapping each preferred tag to a float multiplier between 1.1 and 1.5\n"
        "  source_multipliers: dict mapping each preferred source to a float multiplier between 1.1 and 1.4\n"
        "  pattern_description: a plain English paragraph describing what this client cares about"
    )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = next(
        (block.text for block in response.content if block.type == "text"), ""
    )
    profile = json.loads(raw_text)

    now = datetime.datetime.utcnow()
    next_refresh = now + datetime.timedelta(days=2)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO client_profiles
            (client_email, profile_json, generated_at, total_promotions_at_generation, next_refresh_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(client_email) DO UPDATE SET
            profile_json = excluded.profile_json,
            generated_at = excluded.generated_at,
            total_promotions_at_generation = excluded.total_promotions_at_generation,
            next_refresh_at = excluded.next_refresh_at
        """,
        (
            client_email,
            json.dumps(profile),
            now.strftime("%Y-%m-%d %H:%M:%S"),
            summary["total_promotions"],
            next_refresh.strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    conn.commit()
    conn.close()

    return profile


def load_client_profile(client_email):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT profile_json, next_refresh_at FROM client_profiles WHERE client_email = ?",
        (client_email,),
    )
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    next_refresh_str = row["next_refresh_at"]
    if next_refresh_str:
        try:
            next_refresh = datetime.datetime.strptime(next_refresh_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            next_refresh = datetime.datetime.strptime(next_refresh_str, "%Y-%m-%dT%H:%M:%S")
        if datetime.datetime.utcnow() > next_refresh:
            return None

    return json.loads(row["profile_json"])


def check_and_refresh_profile(client_email):
    existing = load_client_profile(client_email)

    if existing is None:
        if should_generate_profile(client_email):
            return generate_client_profile(client_email)
        return None

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT next_refresh_at FROM client_profiles WHERE client_email = ?",
        (client_email,),
    )
    row = cursor.fetchone()
    conn.close()

    if row and row["next_refresh_at"]:
        next_refresh_str = row["next_refresh_at"]
        try:
            next_refresh = datetime.datetime.strptime(next_refresh_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            next_refresh = datetime.datetime.strptime(next_refresh_str, "%Y-%m-%dT%H:%M:%S")

        if datetime.datetime.utcnow() > next_refresh and should_generate_profile(client_email):
            return generate_client_profile(client_email)

    return existing


if __name__ == "__main__":
    TEST_EMAIL = "test@politiscan.in"

    print(f"--- Testing load_client_profile for {TEST_EMAIL} ---")
    profile = load_client_profile(TEST_EMAIL)
    if profile:
        print(f"  Profile found: {json.dumps(profile, indent=2)}")
    else:
        print("  No profile found (not enough data or expired).")

    print(f"\n--- Testing check_and_refresh_profile for {TEST_EMAIL} ---")
    result = check_and_refresh_profile(TEST_EMAIL)
    if result:
        print(f"  Profile returned:\n{json.dumps(result, indent=2)}")
    else:
        print("  No profile available yet (not enough data to generate one).")
