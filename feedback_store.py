from feedback_db import get_connection
import datetime
import json


def record_promotion(client_email, article):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO feedback
                (client_email, article_url, article_headline, primary_tag,
                 original_score, source_name, affects_region, action)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'PROMOTED')
            """,
            (
                client_email,
                article.get("url"),
                article.get("headline"),
                article.get("primary_tag"),
                article.get("final_score"),
                article.get("source_name"),
                1 if article.get("affects_client_region") else 0,
            ),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def get_feedback_summary(client_email):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT article_headline, primary_tag, source_name,
               original_score, affects_region, promoted_at
        FROM feedback
        WHERE client_email = ? AND action = 'PROMOTED'
        ORDER BY promoted_at ASC
        """,
        (client_email,),
    )
    rows = cursor.fetchall()
    conn.close()

    total_promotions = len(rows)

    if total_promotions == 0:
        return {
            "total_promotions": 0,
            "days_active": 0,
            "promotions_by_tag": {},
            "promotions_by_source": {},
            "low_score_promotions": [],
            "avg_promoted_score": 0.0,
            "region_promotion_rate": 0.0,
        }

    first_ts = rows[0]["promoted_at"]
    last_ts = rows[-1]["promoted_at"]

    def parse_ts(ts):
        if isinstance(ts, datetime.datetime):
            return ts
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return datetime.datetime.strptime(ts, fmt)
            except ValueError:
                continue
        return datetime.datetime.now()

    first_dt = parse_ts(first_ts)
    last_dt = parse_ts(last_ts)
    days_active = (last_dt - first_dt).days

    promotions_by_tag = {}
    promotions_by_source = {}
    low_score_promotions = []
    score_sum = 0.0
    score_count = 0
    region_count = 0

    for row in rows:
        tag = row["primary_tag"] or "unknown"
        promotions_by_tag[tag] = promotions_by_tag.get(tag, 0) + 1

        source = row["source_name"] or "unknown"
        promotions_by_source[source] = promotions_by_source.get(source, 0) + 1

        score = row["original_score"]
        if score is not None:
            score_sum += score
            score_count += 1
            if score < 5:
                low_score_promotions.append({
                    "headline": row["article_headline"],
                    "primary_tag": row["primary_tag"],
                    "source_name": row["source_name"],
                    "original_score": score,
                    "promoted_at": row["promoted_at"],
                })

        if row["affects_region"]:
            region_count += 1

    avg_promoted_score = round(score_sum / score_count, 4) if score_count > 0 else 0.0
    region_promotion_rate = round((region_count / total_promotions) * 100, 2)

    return {
        "total_promotions": total_promotions,
        "days_active": days_active,
        "promotions_by_tag": promotions_by_tag,
        "promotions_by_source": promotions_by_source,
        "low_score_promotions": low_score_promotions,
        "avg_promoted_score": avg_promoted_score,
        "region_promotion_rate": region_promotion_rate,
    }


def get_recent_promotions(client_email, limit=100):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, client_email, article_url, article_headline, primary_tag,
               original_score, source_name, affects_region, action, promoted_at
        FROM feedback
        WHERE client_email = ?
        ORDER BY promoted_at DESC
        LIMIT ?
        """,
        (client_email, limit),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def should_generate_profile(client_email):
    summary = get_feedback_summary(client_email)
    return summary["total_promotions"] >= 15 and summary["days_active"] >= 30


def get_profile_status(client_email):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT generated_at, next_refresh_at FROM client_profiles WHERE client_email = ?",
        (client_email,),
    )
    row = cursor.fetchone()
    conn.close()

    if row is None:
        summary = get_feedback_summary(client_email)
        days_active = summary["days_active"]
        total_promotions = summary["total_promotions"]
        days_until_profile = max(0, 30 - days_active)
        return {
            "status": "collecting",
            "days_active": days_active,
            "total_promotions": total_promotions,
            "days_until_profile": days_until_profile,
        }

    return {
        "status": "active",
        "generated_at": str(row["generated_at"]),
        "next_refresh_at": str(row["next_refresh_at"]),
    }


if __name__ == "__main__":
    TEST_EMAIL = "test_user@example.com"

    print("--- Testing record_promotion ---")
    sample_articles = [
        {
            "url": f"https://example.com/article-{i}",
            "headline": f"Test Article {i}",
            "primary_tag": ["politics", "economy", "health"][i % 3],
            "final_score": 3.5 + i * 0.5,
            "source_name": ["BBC", "Reuters", "AP"][i % 3],
            "affects_client_region": i % 2 == 0,
        }
        for i in range(5)
    ]
    for article in sample_articles:
        result = record_promotion(TEST_EMAIL, article)
        print(f"  record_promotion({article['headline']}): {result}")

    print("\n--- Testing get_feedback_summary ---")
    summary = get_feedback_summary(TEST_EMAIL)
    print(f"  total_promotions: {summary['total_promotions']}")
    print(f"  days_active: {summary['days_active']}")
    print(f"  promotions_by_tag: {summary['promotions_by_tag']}")
    print(f"  promotions_by_source: {summary['promotions_by_source']}")
    print(f"  avg_promoted_score: {summary['avg_promoted_score']}")
    print(f"  region_promotion_rate: {summary['region_promotion_rate']}%")
    print(f"  low_score_promotions count: {len(summary['low_score_promotions'])}")

    print("\n--- Testing get_recent_promotions ---")
    recent = get_recent_promotions(TEST_EMAIL, limit=3)
    for r in recent:
        print(f"  {r['article_headline']} | score={r['original_score']}")

    print("\n--- Testing should_generate_profile ---")
    print(f"  should_generate_profile: {should_generate_profile(TEST_EMAIL)}")

    print("\n--- Testing get_profile_status ---")
    status = get_profile_status(TEST_EMAIL)
    print(f"  profile_status: {status}")
