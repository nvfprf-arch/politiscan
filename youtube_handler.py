import json
import os
import re
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

    classification_instructions = (
        "\n\nAlso classify the report_type of this video as exactly one of: "
        "CONFIRMED if the anchor or reporter presents established facts, official statements, or verified events with no hedging. "
        "SPECULATIVE if the content is uncertain or unverified. This is a TV broadcast transcript so use broadcast hedging signals: "
        "we are getting inputs that, sources are telling us, our sources suggest, there are strong indications, "
        "in what could be a major development, party insiders are saying, we are hearing that. "
        "ANALYTICAL if the content is primarily commentary, analysis, or debate with no new confirmed facts or speculation. "
        "After the summary, output a JSON block (and nothing after it) in this exact format:\n"
        "```json\n"
        '{"report_type": "CONFIRMED|SPECULATIVE|ANALYTICAL", '
        '"speculation_signals": ["exact short phrase 1", "exact short phrase 2"], '
        '"type_confidence": 0.0}\n'
        "```\n"
        "speculation_signals must be exact short phrases from the transcript that triggered the classification; use an empty list if CONFIRMED."
    )

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
            f"{classification_instructions}"
        )
        transcript_status = "Full Summary"
    else:
        prompt = (
            f"You are a political analyst summarizing a news video for an Indian consulting firm. "
            f"The video is in {language}. Write a 2-line English summary based on the title only, "
            f"then add a note that the transcript was unavailable.\n\n"
            f"Title: {title}\n"
            f"Channel: {channel_name}"
            f"{classification_instructions}"
        )
        transcript_status = "Title Only"

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text

    # Extract the JSON block appended after the summary
    report_type = "CONFIRMED"
    speculation_signals = []
    type_confidence = 0.0

    json_match = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if json_match:
        try:
            classification = json.loads(json_match.group(1))
            report_type = classification.get("report_type", "CONFIRMED")
            speculation_signals = classification.get("speculation_signals", [])
            type_confidence = float(classification.get("type_confidence", 0.0))
        except (json.JSONDecodeError, ValueError):
            pass

    # Strip the JSON block from the summary text
    summary = raw[: json_match.start()].strip() if json_match else raw.strip()

    return {
        "summary": summary,
        "transcript_status": transcript_status,
        "report_type": report_type,
        "speculation_signals": speculation_signals,
        "type_confidence": type_confidence,
    }
