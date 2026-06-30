from dotenv import load_dotenv
load_dotenv()

import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from classifier import classify_political
from scorer import score_importance, get_source_tier


SOURCE_TIER_SCORES = {"tier1": 10, "tier2": 7, "tier3": 4}

# Complete list of Indian states and union territories (lowercase).
# Used for the deterministic region-override check.
_ALL_INDIAN_REGIONS = {
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh",
    "goa", "gujarat", "haryana", "himachal pradesh", "jharkhand", "karnataka",
    "kerala", "madhya pradesh", "maharashtra", "manipur", "meghalaya", "mizoram",
    "nagaland", "odisha", "punjab", "rajasthan", "sikkim", "tamil nadu",
    "telangana", "tripura", "uttar pradesh", "uttarakhand", "west bengal",
    "andaman and nicobar", "chandigarh", "dadra and nagar haveli", "daman and diu",
    "delhi", "jammu and kashmir", "ladakh", "lakshadweep", "puducherry",
}

# Geographic relevance scoring controls.
# Articles where affects_client_region=False have their final_score multiplied by this factor.
OUT_OF_REGION_PENALTY = 0.6
# After ranking, articles with affects_client_region=False AND score below this threshold
# are dropped entirely (major national stories above the threshold are still surfaced).
OUT_OF_REGION_SCORE_THRESHOLD = 6.0


def apply_client_profile(base_score: float, article: dict, client_profile: dict | None) -> float:
    """Adjust base_score using a client profile. Returns base_score if profile is None."""
    if client_profile is None:
        return base_score

    score = base_score

    primary_tag = article.get("primary_tag")
    if primary_tag and primary_tag in client_profile.get("preferred_tags", []):
        multiplier = client_profile.get("tag_multipliers", {}).get(primary_tag, 1.2)
        score *= multiplier

    source_name = article.get("source_name")
    if source_name and source_name in client_profile.get("preferred_sources", []):
        multiplier = client_profile.get("source_multipliers", {}).get(source_name, 1.15)
        score *= multiplier

    if article.get("affects_client_region"):
        boost = client_profile.get("region_weight_boost", 1.0)
        if boost > 1.0:
            score *= boost

    return round(min(score, 10.0), 2)


def calculate_recency_score(published_iso: str) -> float:
    """Return a 0-10 recency score based on hours since publication."""
    try:
        pub = datetime.fromisoformat(published_iso.replace("Z", "+00:00"))
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        hours = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
    except Exception:
        return 5.0  # unknown age — neutral score

    if hours < 0:
        return 10.0
    if hours >= 36:
        return 0.0
    return round(10 - hours / 3.6, 1)


def _process_article(article: dict, state: str, district: str, api_key: str) -> dict | None:
    """Run the full classification + scoring pipeline for one article.
    Returns enriched dict or None if the article is not political.
    """
    headline    = article.get("headline", "")
    snippet     = article.get("snippet") or article.get("content", "")
    source_name = article.get("source_name", "")
    published   = article.get("published_iso", "")

    # Step 1 — classify
    cls = classify_political(headline, snippet, api_key)
    if cls["classification"] != "POLITICAL":
        return None

    # Step 2 — importance score
    imp = score_importance(headline, snippet, source_name, published, state, district, api_key)

    # Step 2b — deterministic region override (safety net independent of LLM judgment).
    # If the article text names any other Indian state/UT and does NOT mention the
    # target state or district at all, force affects_client_region to False.
    _text_lower   = (headline + " " + snippet).lower()
    _state_lower  = state.lower()
    _dist_lower   = district.lower()
    _target_in_text = _state_lower in _text_lower or _dist_lower in _text_lower
    _other_states = _ALL_INDIAN_REGIONS - {_state_lower}
    _other_found  = next((s for s in _other_states if s in _text_lower), None)
    if _other_found and not _target_in_text:
        if imp["affects_client_region"]:
            print(f"  [REGION OVERRIDE] Claude=True → forced False  "
                  f"('{_other_found}' in text, '{state}/{district}' not in text)  "
                  f"{headline[:65]}")
        imp = {**imp, "affects_client_region": False}
    elif not _target_in_text and imp["affects_client_region"]:
        # No other state name found but target also absent — log for visibility
        print(f"  [REGION WARN] Claude=True but '{state}/{district}' not found in text  {headline[:65]}")

    # Step 3 — source tier & score
    tier         = get_source_tier(source_name)
    source_score = SOURCE_TIER_SCORES.get(tier, 4)

    # Step 4 — recency
    recency_score = calculate_recency_score(published)

    # Step 5 — final score
    final_score = round(
        imp["importance_score"] * 0.45
        + recency_score          * 0.30
        + source_score           * 0.25,
        2,
    )

    # Step 6 — geographic relevance penalty for out-of-region articles
    pre_penalty = final_score
    if not imp["affects_client_region"]:
        final_score = round(final_score * OUT_OF_REGION_PENALTY, 2)

    region_tag = "IN-REGION" if imp["affects_client_region"] else "OUT-OF-REGION"
    print(f"  [score] {region_tag:<14} pre={pre_penalty:.2f} post={final_score:.2f}  {headline[:65]}")

    # Step 7 — assemble
    return {
        **article,
        "classification":        cls["classification"],
        "confidence":            cls["confidence"],
        "importance_score":      imp["importance_score"],
        "primary_tag":           imp["primary_tag"],
        "one_line_reason":       imp["one_line_reason"],
        "affects_client_region": imp["affects_client_region"],
        "report_type":           imp["report_type"],
        "speculation_signals":   imp["speculation_signals"],
        "type_confidence":       imp["type_confidence"],
        "recency_score":         recency_score,
        "source_tier":           tier,
        "source_score":          source_score,
        "final_score":           final_score,
    }


def rank_articles(
    articles_list: list,
    state: str,
    district: str,
    api_key: str,
    client_profile: dict | None = None,
) -> list:
    """Classify, score, and rank a list of article dicts.

    Each dict must have: headline, snippet or content, source_name,
    published_iso, url.

    Returns articles that are POLITICAL, sorted by final_score descending.
    """
    results = []
    processed = 0

    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {
            executor.submit(_process_article, art, state, district, api_key): art
            for art in articles_list
        }
        for future in as_completed(futures):
            result = future.result()
            processed += 1
            if processed % 10 == 0:
                print(f"  [ranker] processed {processed}/{len(articles_list)} articles...")
            if result is not None:
                original = result["final_score"]
                adjusted = apply_client_profile(original, result, client_profile)
                result["original_final_score"] = original
                result["client_adjusted_score"] = adjusted
                result["profile_boosted"] = (adjusted - original) > 0.5
                results.append(result)

    results.sort(key=lambda x: x["client_adjusted_score"], reverse=True)

    # Step 4 — hard filter: drop out-of-region articles below the score threshold
    before_filter = len(results)
    results = [
        r for r in results
        if r["affects_client_region"] or r["client_adjusted_score"] >= OUT_OF_REGION_SCORE_THRESHOLD
    ]
    dropped = before_filter - len(results)

    # Debug: print per-article region flag and score
    print(f"\n[DEBUG] rank_articles: {state}/{district} — "
          f"{before_filter} political articles scored, {dropped} out-of-region articles dropped "
          f"(score < {OUT_OF_REGION_SCORE_THRESHOLD}), {len(results)} returned.")
    print(f"  {'Rank':<4} {'Score':<6} {'Region':<7} {'Headline'[:65]}")
    for i, r in enumerate(results, 1):
        region_flag = "YES" if r["affects_client_region"] else "NO "
        print(f"  {i:<4} {r['client_adjusted_score']:<6.2f} {region_flag}    {r.get('headline', '')[:65]}")

    return results


def _process_video(video: dict, state: str, district: str, api_key: str) -> dict | None:
    """Run the full pipeline for one video, incorporating engagement_score."""
    headline        = video.get("headline") or video.get("title", "")
    snippet         = video.get("snippet") or video.get("content", "")
    source_name     = video.get("source_name") or video.get("channel_name", "")
    published       = video.get("published_iso") or video.get("published_at", "")
    engagement_score = float(video.get("engagement_score") or video.get("engagement_velocity_score") or 5.0)

    # Step 1 — importance score
    imp = score_importance(headline, snippet, source_name, published, state, district, api_key)

    # Step 2 — source tier & score
    tier         = get_source_tier(source_name)
    source_score = SOURCE_TIER_SCORES.get(tier, 4)

    # Step 3 — recency
    recency_score = calculate_recency_score(published)

    # Step 4 — final score (video formula)
    final_score = round(
        imp["importance_score"] * 0.40
        + engagement_score       * 0.25
        + recency_score          * 0.20
        + source_score           * 0.15,
        2,
    )

    # Step 5 — assemble
    return {
        **video,
        "importance_score":      imp["importance_score"],
        "primary_tag":           imp["primary_tag"],
        "one_line_reason":       imp["one_line_reason"],
        "affects_client_region": imp["affects_client_region"],
        "report_type":           imp["report_type"],
        "speculation_signals":   imp["speculation_signals"],
        "type_confidence":       imp["type_confidence"],
        "recency_score":         recency_score,
        "source_tier":           tier,
        "source_score":          source_score,
        "final_score":           final_score,
    }


def rank_videos(
    videos_list: list,
    state: str,
    district: str,
    api_key: str,
    client_profile: dict | None = None,
) -> list:
    """Classify, score, and rank a list of video dicts.

    Each dict must have: headline, snippet or content, source_name,
    published_iso, url, engagement_score.

    Returns videos that are POLITICAL, sorted by final_score descending.
    """
    print(f"[ranker] rank_videos called with {len(videos_list)} videos")
    results = []
    processed = 0

    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {
            executor.submit(_process_video, vid, state, district, api_key): vid
            for vid in videos_list
        }
        for future in as_completed(futures):
            result = future.result()
            processed += 1
            if processed % 10 == 0:
                print(f"  [ranker] processed {processed}/{len(videos_list)} videos...")
            if result is not None:
                original = result["final_score"]
                adjusted = apply_client_profile(original, result, client_profile)
                result["original_final_score"] = original
                result["client_adjusted_score"] = adjusted
                result["profile_boosted"] = (adjusted - original) > 0.5
                results.append(result)

    print(f"[ranker] videos scored: {len(results)}")
    results.sort(key=lambda x: x["client_adjusted_score"], reverse=True)
    print(f"[ranker] returning {len(results)} results")
    return results


if __name__ == "__main__":
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in environment.")
        raise SystemExit(1)

    # --- recency score unit tests (no API) ---
    print("=== calculate_recency_score tests ===")
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    recency_cases = [
        ("future (should be 10)",  (now + timedelta(hours=1)).isoformat()),
        ("0h old  (should be 10)", now.isoformat()),
        ("9h old  (should be 7.5)", (now - timedelta(hours=9)).isoformat()),
        ("18h old (should be 5.0)", (now - timedelta(hours=18)).isoformat()),
        ("36h old (should be 0.0)", (now - timedelta(hours=36)).isoformat()),
        ("48h old (should be 0.0)", (now - timedelta(hours=48)).isoformat()),
    ]
    for label, ts in recency_cases:
        score = calculate_recency_score(ts)
        print(f"  {label:30} -> {score}")

    # --- rank_articles test ---
    print("\n=== rank_articles test (5 articles) ===")
    recent_ts = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
    old_ts    = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()

    sample_articles = [
        {
            "headline": "Karnataka CM announces cabinet reshuffle, drops 3 senior ministers",
            "snippet": "Chief Minister Siddaramaiah overhauled the Karnataka cabinet today, removing three senior ministers and bringing in new faces from the OBC community ahead of upcoming elections.",
            "source_name": "The Hindu",
            "published_iso": recent_ts,
            "url": "https://thehindu.com/karnataka-cabinet-reshuffle",
        },
        {
            "headline": "Virat Kohli scores double century in Bengaluru Test",
            "snippet": "Indian cricket star Virat Kohli scored a brilliant double century on day three of the Test match at the M. Chinnaswamy Stadium in Bengaluru.",
            "source_name": "NDTV Sports",
            "published_iso": recent_ts,
            "url": "https://ndtv.com/sports/kohli-double-century",
        },
        {
            "headline": "Farmers block highway in Mandya demanding loan waiver",
            "snippet": "Over 3,000 farmers from Mandya district blocked the Bengaluru-Mysuru national highway demanding immediate implementation of the crop loan waiver promised by the Congress government.",
            "source_name": "Deccan Herald",
            "published_iso": recent_ts,
            "url": "https://deccanherald.com/mandya-farmer-protest",
        },
        {
            "headline": "BJP MLA inaugurates new road in Tumkur village",
            "snippet": "BJP MLA from Tumkur inaugurated a newly constructed road in a remote village, thanking the central government's rural development scheme for funding.",
            "source_name": "Local Daily",
            "published_iso": old_ts,
            "url": "https://localdaily.com/tumkur-road-inauguration",
        },
        {
            "headline": "New Bollywood film releases to mixed reviews in Karnataka theatres",
            "snippet": "The latest Bollywood release opened to mixed reviews across Karnataka multiplexes this weekend with moderate occupancy reported in Bengaluru and Mysuru.",
            "source_name": "Entertainment Weekly",
            "published_iso": recent_ts,
            "url": "https://entertainmentweekly.com/bollywood-release",
        },
    ]

    ranked = rank_articles(sample_articles, state="Karnataka", district="Bengaluru", api_key=api_key)

    print(f"\nPolitical articles after filtering: {len(ranked)} / {len(sample_articles)}")
    print("\nRanked results (highest first):")
    for i, art in enumerate(ranked, 1):
        print(
            f"  {i}. [{art['final_score']:5.2f}] "
            f"score={art['importance_score']}/10  "
            f"recency={art['recency_score']}  "
            f"tier={art['source_tier']}  "
            f"tag={art['primary_tag']:15}  "
            f"{art['headline'][:65]}"
        )
