import os
import sys
import time
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from channels import YOUTUBE_CHANNELS

API_KEY = os.getenv("YOUTUBE_API_KEY")


def check_id(channel_id):
    r = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"key": API_KEY, "id": channel_id, "part": "snippet"},
        verify=False, timeout=10,
    )
    r.raise_for_status()
    items = r.json().get("items", [])
    return items[0]["snippet"]["title"] if items else None


def search_channel(query, retries=3):
    for attempt in range(retries):
        time.sleep(1.5)   # respect rate limits between search calls
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={"key": API_KEY, "q": query, "type": "channel",
                    "part": "snippet", "maxResults": 5},
            verify=False, timeout=10,
        )
        if r.status_code == 429:
            wait = 10 * (attempt + 1)
            print(f"    [rate limited, waiting {wait}s...]")
            time.sleep(wait)
            continue
        r.raise_for_status()
        items = r.json().get("items", [])
        return [(i["id"]["channelId"], i["snippet"]["title"]) for i in items]
    return []


def safe(s):
    """Encode string safely for Windows console."""
    return s.encode(sys.stdout.encoding, errors="replace").decode(sys.stdout.encoding)


def main():
    valid = []
    invalid = []

    print("=== Verifying all channel IDs ===\n")
    for lang, channels in YOUTUBE_CHANNELS.items():
        for name, cid in channels.items():
            title = check_id(cid)
            if title:
                print(f"  VALID   {lang:<10} | {name:<25} | {cid} => {safe(title)!r}")
                valid.append((lang, name, cid, title))
            else:
                print(f"  INVALID {lang:<10} | {name:<25} | {cid}")
                invalid.append((lang, name, cid))

    print(f"\n=== {len(valid)} valid, {len(invalid)} invalid out of {len(valid)+len(invalid)} total ===\n")

    if not invalid:
        print("All channel IDs confirmed valid.")
        return

    print("=== Searching for correct IDs for invalid channels ===\n")
    corrections = {}  # (lang, name) -> (best_cid, best_title)
    for lang, name, old_id in invalid:
        results = search_channel(name)
        if results:
            best_cid, best_title = results[0]
            # Prefer a result whose title closely matches the channel name
            for cid, title in results:
                if name.lower() in title.lower() or title.lower() in name.lower():
                    best_cid, best_title = cid, title
                    break
            corrections[(lang, name)] = (best_cid, best_title)
            print(f"  {lang} | {name}")
            for cid, title in results:
                marker = " <-- BEST" if cid == best_cid else ""
                print(f"    {cid}  {safe(title)!r}{marker}")
        else:
            print(f"  {lang} | {name}  => NO SEARCH RESULTS")

    # Print the final corrections table
    print("\n=== Suggested corrections ===")
    for (lang, name), (cid, title) in corrections.items():
        print(f"  {lang:<10} | {name:<25} => {cid}  ({safe(title)})")

    return corrections


if __name__ == "__main__":
    main()
