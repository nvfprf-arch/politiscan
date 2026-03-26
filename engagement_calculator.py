import os
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

TIER1_CHANNELS = {
    "NDTV", "India Today", "Republic TV", "Aaj Tak", "ABP News", "Zee News",
    "Wion", "TV9 Kannada", "Suvarna News", "Puthiya Thalaimurai", "TV9 Telugu",
    "Asianet News", "ABP Majha", "ABP Ananda",
}


def fetch_video_statistics(video_id, youtube_api_key):
    default = {"viewCount": 0, "likeCount": 0, "commentCount": 0}
    try:
        response = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"key": youtube_api_key, "id": video_id, "part": "statistics"},
        )
        response.raise_for_status()
        items = response.json().get("items", [])
        if not items:
            return default
        stats = items[0].get("statistics", {})
        return {
            "viewCount": int(stats.get("viewCount", 0)),
            "likeCount": int(stats.get("likeCount", 0)),
            "commentCount": int(stats.get("commentCount", 0)),
        }
    except Exception:
        return default


def calculate_engagement_velocity(statistics_dict, published_iso):
    view_count = statistics_dict["viewCount"]
    like_count = statistics_dict["likeCount"]
    comment_count = statistics_dict["commentCount"]

    published_dt = datetime.fromisoformat(published_iso)
    if published_dt.tzinfo is None:
        published_dt = published_dt.replace(tzinfo=timezone.utc)

    hours_old = max(
        (datetime.now(timezone.utc) - published_dt).total_seconds() / 3600,
        0.5,
    )

    views_per_hour = view_count / hours_old
    engagement_ratio = (like_count + comment_count) / max(view_count, 1)
    velocity_score = min(views_per_hour / 1000, 10)
    engagement_score = min(engagement_ratio * 100, 10)
    combined = round((velocity_score * 0.7) + (engagement_score * 0.3), 2)

    return {
        "engagement_velocity_score": combined,
        "views_per_hour": round(views_per_hour),
        "total_views": view_count,
    }


def get_channel_tier(channel_name):
    if not channel_name:
        return "tier3"
    if channel_name in TIER1_CHANNELS:
        return "tier1"
    known_channels = {
        "Times Now", "News18 India", "Lallantop", "India TV", "NDTV India",
        "Public TV", "Asianet Suvarna News", "Zee Kannada News",
        "Polimer News", "Sun News", "Kalaignar TV", "News18 Tamil Nadu",
        "ABN Andhra Jyothi", "NTV Telugu", "Sakshi TV", "TV5 News",
        "Mathrubhumi News", "Reporter TV", "Manorama News", "Janam TV",
        "TV9 Marathi", "Zee 24 Taas", "Lokmat Times", "News18 Lokmat",
        "Zee 24 Ghanta", "News18 Bangla", "Calcutta News",
    }
    if channel_name in known_channels:
        return "tier2"
    return "tier3"


if __name__ == "__main__":
    now = datetime.now(timezone.utc)

    fresh_stats = {"viewCount": 8000, "likeCount": 400, "commentCount": 80}
    fresh_published = (now - timedelta(hours=1)).isoformat()
    fresh_result = calculate_engagement_velocity(fresh_stats, fresh_published)
    print("Fresh video (1 hour old, 8000 views):")
    print(f"  engagement_velocity_score : {fresh_result['engagement_velocity_score']}")
    print(f"  views_per_hour            : {fresh_result['views_per_hour']}")
    print(f"  total_views               : {fresh_result['total_views']}")

    print()

    old_stats = {"viewCount": 8000, "likeCount": 400, "commentCount": 80}
    old_published = (now - timedelta(hours=24)).isoformat()
    old_result = calculate_engagement_velocity(old_stats, old_published)
    print("Older video (24 hours old, 8000 views):")
    print(f"  engagement_velocity_score : {old_result['engagement_velocity_score']}")
    print(f"  views_per_hour            : {old_result['views_per_hour']}")
    print(f"  total_views               : {old_result['total_views']}")

    print()
    assert fresh_result["engagement_velocity_score"] > old_result["engagement_velocity_score"], \
        "Fresh video should score higher than older video"
    print("Assertion passed: fresh video scores higher than older video.")
