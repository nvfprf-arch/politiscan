import os
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi
import anthropic

load_dotenv()

LANGUAGE_CODE_MAP = {
    "English": "en",
    "Hindi": "hi",
    "Kannada": "kn",
    "Tamil": "ta",
    "Telugu": "te",
    "Malayalam": "ml",
    "Marathi": "mr",
    "Bengali": "bn",
}


def fetch_channel_videos(channel_id, youtube_api_key, hours_back):
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
        "https://www.googleapis.com/youtube/v3/search", params=params
    )
    response.raise_for_status()
    data = response.json()

    videos = []
    for item in data.get("items", []):
        video_id = item["id"].get("videoId")
        if not video_id:
            continue
        snippet = item["snippet"]
        videos.append(
            {
                "video_id": video_id,
                "title": snippet.get("title", ""),
                "channel_name": snippet.get("channelTitle", ""),
                "published_at": snippet.get("publishedAt", ""),
                "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
            }
        )

    return videos


def fetch_transcript(video_id, language_code):
    try:
        lang_code = LANGUAGE_CODE_MAP.get(language_code, language_code)

        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(
                video_id, languages=[lang_code]
            )
        except Exception:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)

        text = " ".join(segment["text"] for segment in transcript_list)
        return text[:4000]

    except Exception:
        return None


def summarize_video(title, transcript, channel_name, language, anthropic_api_key):
    client = anthropic.Anthropic(api_key=anthropic_api_key)

    if transcript is not None:
        prompt = (
            f"You are a political analyst summarizing a news video for an Indian consulting firm. "
            f"The video is in {language}. Write a 4-line English summary.\n"
            f"Line 1: main event.\n"
            f"Line 2: key people and party.\n"
            f"Line 3: location and context.\n"
            f"Line 4: political significance.\n"
            f"Keep all names in standard English.\n\n"
            f"Title: {title}\n"
            f"Channel: {channel_name}\n"
            f"Transcript: {transcript}"
        )
        transcript_status = "Full Summary"
    else:
        prompt = (
            f"You are a political analyst summarizing a news video for an Indian consulting firm. "
            f"The video is in {language}. Write a 2-line English summary based on the title only, "
            f"then add a note that the transcript was unavailable.\n\n"
            f"Title: {title}\n"
            f"Channel: {channel_name}"
        )
        transcript_status = "Title Only"

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    return {
        "summary": message.content[0].text,
        "transcript_status": transcript_status,
    }
