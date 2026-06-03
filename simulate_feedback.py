"""
simulate_feedback.py

Inserts 20 realistic PROMOTED feedback rows for test@politiscan.in into
politiscan.db, then runs should_generate_profile and generate_client_profile
to verify the profile generation pipeline.

Simulates a client who has used the tool for 35 days and consistently promotes
regional Kannada sources (Prajavani, Vijay Karnataka) and party-internal stories
that the AI undervalued (original_score 3.0-5.5).
"""

import os
import json
import datetime

from feedback_db import get_connection
from feedback_store import should_generate_profile
from feedback_store import get_recent_promotions, get_feedback_summary

CLIENT_EMAIL = "test@politiscan.in"

# ---------------------------------------------------------------------------
# Sample data — 20 rows
# Tags: ELECTION x5, PARTY_INTERNAL x8, ALLIANCE x4, PROTEST x3
# Kannada sources (Prajavani / Vijay Karnataka): rows 0–11  (12 rows)
# Other sources: rows 12–19  (8 rows)
# affects_region = 1: rows 0–15  (16 rows), 0: rows 16–19
# original_score: all between 3.0 and 5.5
# promoted_at: spread across last 35 days (oldest first)
# ---------------------------------------------------------------------------

_now = datetime.datetime.utcnow()

def _days_ago(n, hour=9, minute=0):
    return (_now - datetime.timedelta(days=n)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    ).strftime("%Y-%m-%d %H:%M:%S")


ROWS = [
    # ── PARTY_INTERNAL — Kannada sources ───────────────────────────────────
    {
        "article_url":      "https://www.prajavani.net/politics/2025/bjp-karnataka-internal-rift-001",
        "article_headline": "BJP Karnataka: rift between BSY faction and Nalin Kumar Kateel deepens before district elections",
        "primary_tag":      "PARTY_INTERNAL",
        "original_score":   3.2,
        "source_name":      "Prajavani",
        "affects_region":   1,
        "promoted_at":      _days_ago(35, 8, 15),
    },
    {
        "article_url":      "https://www.vijaykarnatakanews.com/politics/congress-obc-reshuffle-mlc-002",
        "article_headline": "Congress high command signals OBC reshuffle in Karnataka MLC appointments — insiders",
        "primary_tag":      "PARTY_INTERNAL",
        "original_score":   3.5,
        "source_name":      "Vijay Karnataka",
        "affects_region":   1,
        "promoted_at":      _days_ago(33, 10, 30),
    },
    {
        "article_url":      "https://www.prajavani.net/politics/jds-delegation-delhi-hd-kumaraswamy-003",
        "article_headline": "JD(S) delegation meets HD Kumaraswamy in Delhi over Mandya seat-sharing grievances",
        "primary_tag":      "PARTY_INTERNAL",
        "original_score":   4.1,
        "source_name":      "Prajavani",
        "affects_region":   1,
        "promoted_at":      _days_ago(31, 14, 0),
    },
    {
        "article_url":      "https://www.vijaykarnatakanews.com/politics/siddaramaiah-dk-shivakumar-cm-race-004",
        "article_headline": "Siddaramaiah and DK Shivakumar loyalists spar over 2026 CM candidacy at KPCC meet",
        "primary_tag":      "PARTY_INTERNAL",
        "original_score":   4.4,
        "source_name":      "Vijay Karnataka",
        "affects_region":   1,
        "promoted_at":      _days_ago(29, 9, 45),
    },
    {
        "article_url":      "https://www.prajavani.net/politics/bjp-ob-leader-mysuru-005",
        "article_headline": "BJP scouts for OBC face in Mysuru-Kodagu to counter Congress ahead of assembly by-polls",
        "primary_tag":      "PARTY_INTERNAL",
        "original_score":   3.8,
        "source_name":      "Prajavani",
        "affects_region":   1,
        "promoted_at":      _days_ago(27, 11, 0),
    },
    # ── ELECTION — Kannada sources ──────────────────────────────────────────
    {
        "article_url":      "https://www.vijaykarnatakanews.com/election/bbmp-ward-delimitation-006",
        "article_headline": "BBMP ward delimitation draft triggers protests in South Bengaluru; poll panel seeks fresh report",
        "primary_tag":      "ELECTION",
        "original_score":   4.0,
        "source_name":      "Vijay Karnataka",
        "affects_region":   1,
        "promoted_at":      _days_ago(25, 16, 20),
    },
    {
        "article_url":      "https://www.prajavani.net/election/hassan-bypoll-candidate-shortlist-007",
        "article_headline": "JD(S)-BJP alliance finalises Hassan by-poll shortlist; Prajwal controversy still shadows candidate choice",
        "primary_tag":      "ELECTION",
        "original_score":   4.7,
        "source_name":      "Prajavani",
        "affects_region":   1,
        "promoted_at":      _days_ago(23, 8, 0),
    },
    {
        "article_url":      "https://www.vijaykarnatakanews.com/election/tumkur-urban-local-body-008",
        "article_headline": "Tumkur ULB polls: Congress eyes Vokkaliga outreach as BJP banks on anti-incumbency fatigue",
        "primary_tag":      "ELECTION",
        "original_score":   3.6,
        "source_name":      "Vijay Karnataka",
        "affects_region":   1,
        "promoted_at":      _days_ago(21, 12, 10),
    },
    # ── ALLIANCE — Kannada sources ──────────────────────────────────────────
    {
        "article_url":      "https://www.prajavani.net/politics/jds-bjp-alliance-seat-share-009",
        "article_headline": "JD(S)-BJP alliance seat-share talks stall over Mandya and Hassan districts; mediators called in",
        "primary_tag":      "ALLIANCE",
        "original_score":   5.0,
        "source_name":      "Prajavani",
        "affects_region":   1,
        "promoted_at":      _days_ago(19, 15, 0),
    },
    {
        "article_url":      "https://www.vijaykarnatakanews.com/politics/congress-sp-karnataka-alliance-010",
        "article_headline": "Congress-SP Karnataka tie-up floated for OBC vote consolidation in north Karnataka constituencies",
        "primary_tag":      "ALLIANCE",
        "original_score":   3.3,
        "source_name":      "Vijay Karnataka",
        "affects_region":   1,
        "promoted_at":      _days_ago(17, 10, 45),
    },
    {
        "article_url":      "https://www.prajavani.net/politics/bjp-jds-local-body-alliance-011",
        "article_headline": "BJP-JD(S) local body alliance faces first internal test in Shivamogga district panchayat vote",
        "primary_tag":      "ALLIANCE",
        "original_score":   4.2,
        "source_name":      "Prajavani",
        "affects_region":   1,
        "promoted_at":      _days_ago(15, 9, 0),
    },
    {
        "article_url":      "https://www.vijaykarnatakanews.com/politics/congress-alliance-dalit-orgs-012",
        "article_headline": "Congress Karnataka formalises poll alliance with three Dalit organisations ahead of gram panchayat elections",
        "primary_tag":      "ALLIANCE",
        "original_score":   3.9,
        "source_name":      "Vijay Karnataka",
        "affects_region":   1,
        "promoted_at":      _days_ago(13, 14, 30),
    },
    # ── PARTY_INTERNAL — non-Kannada sources ────────────────────────────────
    {
        "article_url":      "https://www.thehindu.com/news/national/karnataka/bjp-karnataka-president-013",
        "article_headline": "BJP Karnataka president election deferred again amid factional pressure from CM hopefuls",
        "primary_tag":      "PARTY_INTERNAL",
        "original_score":   4.5,
        "source_name":      "The Hindu",
        "affects_region":   1,
        "promoted_at":      _days_ago(11, 8, 0),
    },
    {
        "article_url":      "https://www.deccanherald.com/karnataka/congress-dcc-president-014",
        "article_headline": "Congress DCC president appointments in 8 districts delayed amid caste arithmetic disputes",
        "primary_tag":      "PARTY_INTERNAL",
        "original_score":   3.7,
        "source_name":      "Deccan Herald",
        "affects_region":   1,
        "promoted_at":      _days_ago(10, 11, 0),
    },
    # ── ELECTION — non-Kannada sources ─────────────────────────────────────
    {
        "article_url":      "https://www.ndtv.com/india-news/karnataka-mla-disqualification-015",
        "article_headline": "Karnataka Speaker fast-tracks MLA disqualification petitions ahead of by-poll calendar deadline",
        "primary_tag":      "ELECTION",
        "original_score":   5.1,
        "source_name":      "NDTV",
        "affects_region":   1,
        "promoted_at":      _days_ago(9, 14, 0),
    },
    {
        "article_url":      "https://www.indiatoday.in/india/karnataka-2026-election-survey-016",
        "article_headline": "Internal Congress survey flags seat vulnerability in 22 Karnataka constituencies ahead of 2026",
        "primary_tag":      "ELECTION",
        "original_score":   5.5,
        "source_name":      "India Today",
        "affects_region":   1,
        "promoted_at":      _days_ago(7, 10, 30),
    },
    # ── PROTEST — non-Kannada, affects_region = 0 ──────────────────────────
    {
        "article_url":      "https://www.thehindu.com/news/national/karnataka/farmers-protest-mandya-017",
        "article_headline": "Farmers block Bengaluru-Mysuru highway in Mandya demanding state loan waiver implementation",
        "primary_tag":      "PROTEST",
        "original_score":   3.4,
        "source_name":      "The Hindu",
        "affects_region":   0,
        "promoted_at":      _days_ago(6, 9, 0),
    },
    {
        "article_url":      "https://www.deccanherald.com/karnataka/darwad-protest-bjp-018",
        "article_headline": "BJP workers stage dharna in Dharwad against alleged government targeting of opposition MLAs",
        "primary_tag":      "PROTEST",
        "original_score":   3.0,
        "source_name":      "Deccan Herald",
        "affects_region":   0,
        "promoted_at":      _days_ago(4, 16, 0),
    },
    {
        "article_url":      "https://www.ndtv.com/india-news/karnataka-valmiki-community-protest-019",
        "article_headline": "Valmiki community leaders threaten statewide protest over unfilled SC/ST corporation board posts",
        "primary_tag":      "PROTEST",
        "original_score":   3.1,
        "source_name":      "NDTV",
        "affects_region":   0,
        "promoted_at":      _days_ago(2, 13, 0),
    },
    {
        "article_url":      "https://www.indiatoday.in/india/karnataka-obc-quota-agitation-020",
        "article_headline": "OBC quota agitation reaches Karnataka Assembly premises; police impose Section 144 around Vidhana Soudha",
        "primary_tag":      "ELECTION",
        "original_score":   4.8,
        "source_name":      "India Today",
        "affects_region":   0,
        "promoted_at":      _days_ago(1, 11, 0),
    },
]

assert len(ROWS) == 20, f"Expected 20 rows, got {len(ROWS)}"


def insert_feedback():
    conn = get_connection()
    cursor = conn.cursor()

    # Remove any existing test data for this email so the script is re-runnable
    cursor.execute("DELETE FROM feedback WHERE client_email = ?", (CLIENT_EMAIL,))
    deleted = cursor.rowcount
    if deleted:
        print(f"Cleared {deleted} existing feedback rows for {CLIENT_EMAIL}")

    for row in ROWS:
        cursor.execute(
            """
            INSERT INTO feedback
                (client_email, article_url, article_headline, primary_tag,
                 original_score, source_name, affects_region, action, promoted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'PROMOTED', ?)
            """,
            (
                CLIENT_EMAIL,
                row["article_url"],
                row["article_headline"],
                row["primary_tag"],
                row["original_score"],
                row["source_name"],
                row["affects_region"],
                row["promoted_at"],
            ),
        )

    conn.commit()
    conn.close()
    print(f"Inserted {len(ROWS)} feedback rows for {CLIENT_EMAIL}")
    print()

    # Breakdown summary
    from collections import Counter
    tag_counts    = Counter(r["primary_tag"]   for r in ROWS)
    source_counts = Counter(r["source_name"]   for r in ROWS)
    kannada_count = sum(1 for r in ROWS if r["source_name"] in ("Prajavani", "Vijay Karnataka"))
    region_count  = sum(1 for r in ROWS if r["affects_region"] == 1)
    scores        = [r["original_score"] for r in ROWS]

    print("  Tag distribution:   ", dict(tag_counts))
    print("  Source distribution:", dict(source_counts))
    print(f"  Kannada sources:     {kannada_count}/20")
    print(f"  affects_region=1:    {region_count}/20")
    print(f"  Score range:         {min(scores):.1f} – {max(scores):.1f}  "
          f"(avg {sum(scores)/len(scores):.2f})")
    print(f"  Date span:           {ROWS[0]['promoted_at'][:10]} -> {ROWS[-1]['promoted_at'][:10]}")
    print()


def _generate_profile(client_email: str):
    """
    Replicates profile_analyzer.generate_client_profile but builds the
    httpx.Client explicitly with certifi's CA bundle to work around the
    Windows SSL certificate chain issue.
    """
    import httpx
    import certifi
    import anthropic
    from dotenv import load_dotenv
    load_dotenv()

    MODEL = "claude-sonnet-4-5"

    promotions = get_recent_promotions(client_email, limit=100)
    summary    = get_feedback_summary(client_email)

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
        tag      = p.get("primary_tag") or "unknown"
        score    = p.get("original_score")
        source   = p.get("source_name") or "unknown"
        region   = p.get("affects_region", 0)
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

    # Norton Antivirus SSL inspection replaces the server cert with its own
    # self-signed cert, so no public CA bundle (including certifi) can verify
    # it. verify=False is the only option on this machine for local scripts.
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    http_client = httpx.Client(verify=False)
    claude      = anthropic.Anthropic(http_client=http_client)
    response    = claude.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = next(
        (block.text for block in response.content if block.type == "text"), ""
    )
    # Strip markdown code fences if the model wrapped the JSON
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()
    profile = json.loads(stripped)

    now          = datetime.datetime.utcnow()
    next_refresh = now + datetime.timedelta(days=2)

    conn   = get_connection()
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


def main():
    print("=" * 60)
    print("PolitiScan — Feedback Simulation")
    print("=" * 60)
    print()

    insert_feedback()

    # ── should_generate_profile ─────────────────────────────────────────────
    print("-" * 60)
    print("should_generate_profile check")
    print("-" * 60)
    result = should_generate_profile(CLIENT_EMAIL)
    print(f"  should_generate_profile('{CLIENT_EMAIL}'): {result}")
    print()

    if not result:
        print("  Profile generation threshold not met — check row counts / days_active.")
        print("  Aborting profile generation.")
        return

    # ── generate_client_profile ─────────────────────────────────────────────
    print("-" * 60)
    print("generate_client_profile -- calling Claude API...")
    print("-" * 60)
    profile = _generate_profile(CLIENT_EMAIL)

    if profile is None:
        print("  generate_client_profile returned None (threshold not met or error).")
        return

    print()
    print("Generated client profile:")
    print(json.dumps(profile, indent=2))
    print()

    print("-" * 60)
    print("Key profile signals expected for this simulation:")
    print("  preferred_tags:     PARTY_INTERNAL, ALLIANCE")
    print("  preferred_sources:  Prajavani, Vijay Karnataka")
    print("  region_weight_boost > 1.0  (16/20 rows affect region)")
    print("  score_floor: 3–4  (AI consistently undervalued at 3.0–5.5)")
    print("-" * 60)


if __name__ == "__main__":
    main()
