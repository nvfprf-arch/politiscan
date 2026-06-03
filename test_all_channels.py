import os
import requests
import urllib3
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# Suppress SSL warnings — this machine has a broken cert chain for googleapis.com.
# We disable verification only in this test script so the API responses are visible.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from channels import YOUTUBE_CHANNELS

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")


def fetch_channel_videos_noverify(channel_id, youtube_api_key, hours_back):
    """Local copy of fetch_channel_videos with SSL verification disabled."""
    published_after = (
        datetime.now(timezone.utc) - timedelta(hours=hours_back)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "key": youtube_api_key,
        "channelId": channel_id,
        "publishedAfter": published_after,
        "type": "video",
        "order": "date",
        "maxResults": 50,
        "part": "snippet",
    }

    response = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params=params,
        verify=False,
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()

    # Surface quota/error responses from the API itself
    if "error" in data:
        err = data["error"]
        raise RuntimeError(f"API error {err.get('code')}: {err.get('message')}")

    videos = []
    for item in data.get("items", []):
        video_id = item["id"].get("videoId")
        if not video_id:
            continue
        snippet = item["snippet"]
        videos.append({
            "video_id": video_id,
            "title": snippet.get("title", ""),
            "channel_name": snippet.get("channelTitle", ""),
            "published_at": snippet.get("publishedAt", ""),
            "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
        })

    return videos, data.get("pageInfo", {})


def check_channel_id_valid(channel_id):
    """Return the channel title from the YouTube API, or None if not found."""
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={
                "key": YOUTUBE_API_KEY,
                "id": channel_id,
                "part": "snippet",
            },
            verify=False,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            return f"API_ERROR: {data['error'].get('message')}"
        items = data.get("items", [])
        if items:
            return items[0]["snippet"]["title"]
        return None
    except Exception as e:
        return f"ERROR: {e}"


def main():
    if not YOUTUBE_API_KEY:
        print("ERROR: YOUTUBE_API_KEY not set in .env")
        return

    rows = []  # (language, channel_name, channel_id, video_count)

    for language, channels in YOUTUBE_CHANNELS.items():
        for channel_name, channel_id in channels.items():
            print(f"  Fetching {language} | {channel_name} ...", flush=True)
            try:
                videos, page_info = fetch_channel_videos_noverify(channel_id, YOUTUBE_API_KEY, hours_back=168)
                count = len(videos)
                total_results = page_info.get("totalResults", "?")
                if count == 0:
                    print(f"    -> 0 videos returned (API totalResults={total_results})")
            except Exception as e:
                print(f"    fetch error: {e}")
                count = -1
            rows.append((language, channel_name, channel_id, count))

    # --- sort: languages where every channel got 0 first, then others ---
    lang_has_any = {}
    for language, _, _, count in rows:
        if count > 0:
            lang_has_any[language] = True
        elif language not in lang_has_any:
            lang_has_any[language] = False

    def sort_key(row):
        language, _, _, count = row
        lang_all_zero = not lang_has_any.get(language, False)
        return (not lang_all_zero, language)

    rows.sort(key=sort_key)

    # --- print results ---
    print()
    print(f"{'LANGUAGE':<12} | {'Channel Name':<25} | {'Channel ID':<28} | Videos")
    print("-" * 85)

    zero_channels = []
    for language, channel_name, channel_id, count in rows:
        status = str(count) if count >= 0 else "FETCH_ERROR"
        print(f"{language:<12} | {channel_name:<25} | {channel_id:<28} | {status}")
        if count == 0:
            zero_channels.append((language, channel_name, channel_id))

    # --- validate zero-result channel IDs ---
    if zero_channels:
        print()
        print("=== Validating channel IDs that returned 0 videos ===")
        valid_count = 0
        for language, channel_name, channel_id in zero_channels:
            title = check_channel_id_valid(channel_id)
            if title and not str(title).startswith("ERROR"):
                valid_count += 1
                verdict = f"VALID — YouTube title: {title!r}"
            elif title and str(title).startswith("ERROR"):
                verdict = title
            else:
                verdict = "INVALID — channel ID not found on YouTube"
            print(f"  {language} | {channel_name} | {channel_id} => {verdict}")

    # --- summary ---
    total_channels = len(rows)
    channels_with_videos = sum(1 for _, _, _, c in rows if c > 0)
    channels_returning_zero = len(zero_channels)

    all_channel_ids = [(cid, lang, name) for lang, name, cid, _ in rows]
    print()
    print("=== Summary ===")

    # Re-validate all zero channels for the "valid IDs" count
    valid_ids = sum(
        1 for _, _, channel_id, count in rows
        if count > 0  # fetched successfully => ID is valid
    )
    # For zero-count channels, check validity
    id_valid_flags = {}
    for language, channel_name, channel_id in zero_channels:
        title = check_channel_id_valid(channel_id)
        id_valid_flags[channel_id] = bool(title and not str(title).startswith("ERROR"))

    valid_ids += sum(1 for v in id_valid_flags.values() if v)
    total_ids = total_channels

    langs_with_working = sum(1 for lang, has_any in lang_has_any.items() if has_any)

    print(f"  {valid_ids} out of {total_ids} channel IDs are valid")
    print(f"  {langs_with_working} languages have at least one working channel")
    print(f"  {channels_returning_zero} channels returned 0 videos in the last 7 days")


if __name__ == "__main__":
    main()
