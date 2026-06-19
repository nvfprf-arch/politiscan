import html
import os
import re
import sys
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import difflib

import streamlit as st
import pandas as pd

if not st.session_state.get("logged_in"):
    st.warning("Please log in from the main app page.")
    st.stop()
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from channels import YOUTUBE_CHANNELS
from youtube_handler import fetch_channel_videos, fetch_transcript, summarize_video
from engagement_calculator import (
    fetch_video_statistics,
    calculate_engagement_velocity,
    get_channel_tier,
)
from classifier import classify_political
from ranker import rank_videos

load_dotenv()

from theme import apply_newspaper_theme
apply_newspaper_theme()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

_TYPE_STYLES = {
    "CONFIRMED":   "background-color: #1a472a; color: white",
    "SPECULATIVE": "background-color: #7d4e00; color: white",
    "ANALYTICAL":  "background-color: #1a3a5c; color: white",
}


def _style_report_type(col):
    return col.map(lambda v: _TYPE_STYLES.get(v, ""))


def _truncate_signals(signals, max_len=80):
    if not signals:
        return ""
    joined = ", ".join(str(s) for s in signals)
    return joined if len(joined) <= max_len else joined[:max_len - 1] + "…"

TIME_PERIOD_MAP = {
    "Last 6 Hours": 6,
    "Last 12 Hours": 12,
    "Last 24 Hours": 24,
    "Last 36 Hours": 36,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _titles_overlap(t1, t2, threshold=0.7):
    return difflib.SequenceMatcher(None, t1.lower(), t2.lower()).ratio() >= threshold


def _deduplicate(videos):
    unique = []
    for v in videos:
        if not any(_titles_overlap(v["title"], u["title"]) for u in unique):
            unique.append(v)
    return unique


def _get_channel_ids(language, selected_channels):
    all_opt = "All Channels" if language == "All Languages" else f"All {language} Channels"
    use_all = (not selected_channels) or (all_opt in selected_channels)

    result = []
    langs = YOUTUBE_CHANNELS.items() if language == "All Languages" else [(language, YOUTUBE_CHANNELS[language])]
    for lang, channels in langs:
        for name, cid in channels.items():
            if use_all or name in selected_channels:
                result.append({"name": name, "id": cid, "language": lang})
    return result


# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(page_title="YouTube Intelligence Monitor", layout="wide")
st.markdown(
    """<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
<svg width="28" height="28" viewBox="0 0 32 32"><circle cx="13" cy="13" r="9" fill="none" stroke="#D85A30" stroke-width="2.5"/><line x1="19.5" y1="19.5" x2="29" y2="29" stroke="#D85A30" stroke-width="2.5" stroke-linecap="round"/></svg>
<span style="font-size:20px;font-weight:700;color:#1A1A1A;letter-spacing:1px;">POLITISCAN</span>
</div>""",
    unsafe_allow_html=True,
)
st.title("YouTube Intelligence Monitor")

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown(
        f"""<div style="border:1px solid #1A1A1A;padding:12px;margin-bottom:4px;">
<p style="font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:#6B6B63;margin:0 0 6px 0;">Signed in as</p>
<p style="font-size:16px;font-weight:700;color:#1A1A1A;margin:0 0 12px 0;">{st.session_state.user_email}</p>
</div>""",
        unsafe_allow_html=True,
    )
    if st.button("LOGOUT", key="yt_sidebar_logout", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
    st.divider()
    st.header("Scan Settings")

    language = st.selectbox(
        "Language",
        ["All Languages"] + list(YOUTUBE_CHANNELS.keys()),
    )

    if language == "All Languages":
        ch_options = ["All Channels"] + [
            name for ch in YOUTUBE_CHANNELS.values() for name in ch
        ]
    else:
        ch_options = [f"All {language} Channels"] + list(YOUTUBE_CHANNELS[language].keys())

    all_opt = ch_options[0]

    # Initialize session state on first load
    if "yt_channel_widget" not in st.session_state:
        st.session_state["yt_channel_widget"] = [all_opt]
        st.session_state["yt_prev_channels"] = [all_opt]
        st.session_state["yt_prev_language"] = language

    # Reset selection when language changes
    if st.session_state.get("yt_prev_language") != language:
        st.session_state["yt_channel_widget"] = [all_opt]
        st.session_state["yt_prev_channels"] = [all_opt]
        st.session_state["yt_prev_language"] = language

    def _on_channel_change():
        current = st.session_state["yt_channel_widget"]
        prev = st.session_state["yt_prev_channels"]
        newly_added = [x for x in current if x not in prev]

        if not newly_added:
            # Items were only removed; ensure selection is never empty
            if not current:
                st.session_state["yt_channel_widget"] = [all_opt]
        elif all_opt in newly_added:
            # 'All Channels' was added — clear specific channels
            st.session_state["yt_channel_widget"] = [all_opt]
        else:
            # A specific channel was added — remove 'All Channels'
            st.session_state["yt_channel_widget"] = [x for x in current if x != all_opt]

        st.session_state["yt_prev_channels"] = list(st.session_state["yt_channel_widget"])

    selected_channels = st.multiselect(
        "News Channel",
        ch_options,
        key="yt_channel_widget",
        on_change=_on_channel_change,
    )

    time_period = st.selectbox(
        "Time Period",
        list(TIME_PERIOD_MAP.keys()),
        index=2,
    )

    keyword = st.text_input("Filter by Keyword (optional)", key="yt_keyword")

    scan_button = st.button("Scan and Rank", type="primary", use_container_width=True)

    report_type_filter = ["CONFIRMED", "SPECULATIVE", "ANALYTICAL"]
    relevance_filter = None
    if "yt_results" in st.session_state and st.session_state["yt_results"]:
        _rt_all = "All Report Types"
        _rt_options = [_rt_all, "CONFIRMED", "SPECULATIVE", "ANALYTICAL"]

        if "yt_report_type_widget" not in st.session_state:
            st.session_state["yt_report_type_widget"] = [_rt_all]
            st.session_state["yt_prev_report_types"] = [_rt_all]

        def _on_report_type_change():
            current = st.session_state["yt_report_type_widget"]
            prev = st.session_state["yt_prev_report_types"]
            newly_added = [x for x in current if x not in prev]

            if not newly_added:
                if not current:
                    st.session_state["yt_report_type_widget"] = [_rt_all]
            elif _rt_all in newly_added:
                st.session_state["yt_report_type_widget"] = [_rt_all]
            else:
                st.session_state["yt_report_type_widget"] = [x for x in current if x != _rt_all]

            st.session_state["yt_prev_report_types"] = list(st.session_state["yt_report_type_widget"])

        st.multiselect(
            "Show Report Types",
            _rt_options,
            key="yt_report_type_widget",
            on_change=_on_report_type_change,
        )

        _rt_sel = st.session_state["yt_report_type_widget"]
        if _rt_all in _rt_sel:
            report_type_filter = ["CONFIRMED", "SPECULATIVE", "ANALYTICAL"]
        else:
            report_type_filter = _rt_sel

        _rel_all = "All Relevance"
        _rel_options = [_rel_all, "Viral", "Rising", "Active"]

        if "yt_relevance_widget" not in st.session_state:
            st.session_state["yt_relevance_widget"] = [_rel_all]
            st.session_state["yt_prev_relevance"] = [_rel_all]

        def _on_relevance_change():
            current = st.session_state["yt_relevance_widget"]
            prev = st.session_state["yt_prev_relevance"]
            newly_added = [x for x in current if x not in prev]

            if not newly_added:
                if not current:
                    st.session_state["yt_relevance_widget"] = [_rel_all]
            elif _rel_all in newly_added:
                st.session_state["yt_relevance_widget"] = [_rel_all]
            else:
                st.session_state["yt_relevance_widget"] = [x for x in current if x != _rel_all]

            st.session_state["yt_prev_relevance"] = list(st.session_state["yt_relevance_widget"])

        st.multiselect(
            "Filter by Relevance",
            _rel_options,
            key="yt_relevance_widget",
            on_change=_on_relevance_change,
        )

        _rel_sel = st.session_state["yt_relevance_widget"]
        relevance_filter = None if _rel_all in _rel_sel else _rel_sel


# ── Pipeline ──────────────────────────────────────────────────────────────────

if scan_button:
    if not YOUTUBE_API_KEY:
        st.error("YOUTUBE_API_KEY is not set in environment.")
        st.stop()
    if not ANTHROPIC_API_KEY:
        st.error("ANTHROPIC_API_KEY is not set in environment.")
        st.stop()

    channel_data = _get_channel_ids(language, selected_channels)
    if not channel_data:
        st.warning("No channels selected.")
        st.stop()

    hours_back = TIME_PERIOD_MAP[time_period]
    status_box = st.empty()

    # Step 1: Fetch videos
    status_box.info(f"Step 1/7 — Fetching videos from {len(channel_data)} channels...")
    print(f"[YT] Step 1: fetching from {len(channel_data)} channels")

    def _fetch_channel(ch):
        try:
            vids = fetch_channel_videos(ch["id"], YOUTUBE_API_KEY, hours_back)
            for v in vids:
                v["title"] = html.unescape(v.get("title", ""))
                v["language"] = ch["language"]
                v.setdefault("channel_name", ch["name"])
            return vids
        except Exception:
            return []

    raw_videos = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for result in as_completed([ex.submit(_fetch_channel, ch) for ch in channel_data]):
            raw_videos.extend(result.result())

    # Step 2: Deduplicate
    unique_videos = _deduplicate(raw_videos)
    total_fetched = len(unique_videos)
    print(f"[YT] Step 2: {total_fetched} unique videos after dedup")

    # Step 3: Classify
    status_box.info(f"Step 2/7 — Classifying {total_fetched} videos for political relevance...")
    print(f"[YT] Step 3: classifying {total_fetched} videos")

    def _classify(v):
        try:
            result = classify_political(v["title"], "", ANTHROPIC_API_KEY)
        except Exception as e:
            result = {"classification": "NOT_POLITICAL", "confidence": 0.0, "reason": str(e)}
        return v, result

    political_videos = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        for future in as_completed([ex.submit(_classify, v) for v in unique_videos]):
            v, result = future.result()
            if result["classification"] != "NOT_POLITICAL":
                political_videos.append(v)

    non_political_count = total_fetched - len(political_videos)
    print(f"[YT] Step 3 done: {len(political_videos)} political, {non_political_count} non-political")

    # Step 4: Cap at top 30 most recent
    political_videos_sorted = sorted(
        political_videos,
        key=lambda v: v.get("published_at", ""),
        reverse=True,
    )
    videos_to_rank = political_videos_sorted[:30]
    status_box.info(
        f"Step 3/7 — Ranking top 30 most recent political videos "
        f"from {len(political_videos)} total political found. Fetching engagement data..."
    )
    print(f"[YT] Step 4: capped to {len(videos_to_rank)} videos for ranking")

    # Step 5: Fetch stats + transcripts
    status_box.info(f"Step 4/7 — Fetching transcripts and engagement metrics for {len(videos_to_rank)} videos...")
    print(f"[YT] Step 5: fetching stats + transcripts")

    def _fetch_stats_and_transcript(v):
        stats = fetch_video_statistics(v["video_id"], YOUTUBE_API_KEY)
        transcript = fetch_transcript(v["video_id"], v.get("language", "English"))
        return v["video_id"], stats, transcript

    stats_map = {}
    transcript_map = {}
    with ThreadPoolExecutor(max_workers=15) as ex:
        futures = {ex.submit(_fetch_stats_and_transcript, v): v["video_id"] for v in videos_to_rank}
        for f in as_completed(futures):
            vid_id, stats, transcript = f.result()
            stats_map[vid_id] = stats
            transcript_map[vid_id] = transcript

    print(f"[YT] Step 5 done: stats+transcripts fetched")

    # Step 6: Engagement scores + channel tier
    status_box.info(f"Step 5/7 — Calculating engagement scores for {len(videos_to_rank)} videos...")
    print(f"[YT] Step 6: calculating engagement")

    for v in videos_to_rank:
        stats = stats_map.get(v["video_id"], {"viewCount": 0, "likeCount": 0, "commentCount": 0})
        eng = calculate_engagement_velocity(stats, v["published_at"])
        v.update(stats)
        v.update(eng)
        v["channel_tier"] = get_channel_tier(v.get("channel_name", ""))
        v["transcript"] = transcript_map.get(v["video_id"])

    # Step 7: Rank
    status_box.info(f"Step 6/7 — Ranking {len(videos_to_rank)} videos by political significance...")
    print(f"[YT] Step 7: ranking")
    ranked = rank_videos(videos_to_rank, "", "", ANTHROPIC_API_KEY)
    print(f"[YT] Step 7 done: {len(ranked)} ranked")

    # Step 8: Summarize in parallel
    status_box.info(f"Step 7/7 — Summarizing {len(ranked)} ranked videos...")
    print(f"[YT] Step 8: summarizing")

    def _summarize(v):
        result = summarize_video(
            v["title"],
            v.get("transcript"),
            v.get("channel_name", ""),
            v.get("language", "English"),
            ANTHROPIC_API_KEY,
        )
        v["summary"] = result["summary"]
        v["transcript_status"] = result["transcript_status"]
        v["report_type"] = result["report_type"]
        v["speculation_signals"] = result["speculation_signals"]
        v["type_confidence"] = result["type_confidence"]
        return v

    with ThreadPoolExecutor(max_workers=10) as ex:
        ranked = list(ex.map(_summarize, ranked))

    print(f"[YT] Step 8 done: summaries complete")

    status_box.empty()

    st.session_state["yt_results"] = ranked
    st.session_state["yt_summary"] = {
        "total_fetched": total_fetched,
        "non_political_removed": non_political_count,
        "political_ranked": len(ranked),
        "language": language,
        "selected_channels": selected_channels,
        "time_period": time_period,
    }

    print(f"[YT] Pipeline complete. {len(ranked)} results stored in session_state.")


# ── Results ───────────────────────────────────────────────────────────────────

if "yt_results" in st.session_state and len(st.session_state["yt_results"]) > 0:
    meta = st.session_state["yt_summary"]
    results = st.session_state["yt_results"]

    display_results = results
    if report_type_filter:
        display_results = [
            v for v in display_results
            if v.get("report_type", "CONFIRMED") in report_type_filter
        ]

    # Compute percentile thresholds ONCE from the full results set
    _vph_all = [v.get("views_per_hour", 0) for v in results if v.get("views_per_hour", 0) > 0]
    if len(_vph_all) >= 2:
        _vph_sorted = sorted(_vph_all)
        _n = len(_vph_sorted)
        _p80 = _vph_sorted[int(_n * 0.80)]
        _p50 = _vph_sorted[int(_n * 0.50)]
    else:
        _p80 = _p50 = None

    def _relevance_label(vph):
        if not vph or _p80 is None:
            return ""
        if vph >= _p80:
            return "Viral"
        if vph >= _p50:
            return "Rising"
        return "Active"

    if relevance_filter:
        display_results = [
            v for v in display_results
            if _relevance_label(v.get("views_per_hour", 0)) in relevance_filter
        ]

    # Live keyword filter
    _kw = st.session_state.get("yt_keyword", "").strip()
    if _kw:
        _kw_lower = _kw.lower()
        display_results = [
            v for v in display_results
            if _kw_lower in v.get("title", "").lower() or _kw_lower in v.get("summary", "").lower()
        ]

    # Stats summary line
    stats_md = (
        f"**Total fetched:** {meta['total_fetched']} &nbsp;|&nbsp; "
        f"**Non-political removed:** {meta['non_political_removed']} &nbsp;|&nbsp; "
        f"**Political ranked:** {meta['political_ranked']}"
    )
    if _kw:
        stats_md += (
            f" &nbsp;|&nbsp; **Filtered to:** {len(display_results)} "
            f"matching `{_kw}`"
        )
    st.markdown(stats_md)

    if not display_results:
        st.info("No results match the current filters.")
    else:
        rows = []
        for rank_idx, v in enumerate(display_results, 1):
            rows.append({
                "Rank": rank_idx,
                "Score": round(v.get("final_score", 0), 2),
                "Tag": v.get("primary_tag", ""),
                "Relevance": _relevance_label(v.get("views_per_hour", 0)),
                "Title": v.get("title", ""),
                "Channel": v.get("channel_name", ""),
                "Views/hr": int(v.get("views_per_hour", 0)),
                "Upload Time": v.get("published_at", "")[:16].replace("T", " "),
                "Summary": (lambda s: s[:300] + "..." if len(s) > 300 else s)(re.sub(r'^\*\*Summary[:\s]*\*\*\s*', '', v.get("summary", "").removeprefix("## Summary").removeprefix("## ")).lstrip()),
                "Report Type": v.get("report_type", "CONFIRMED"),
                "Signals": _truncate_signals(v.get("speculation_signals", [])),
                "YouTube Link": v.get("youtube_url", ""),
            })

        df = pd.DataFrame(rows)
        df["Score"] = df["Score"].apply(lambda x: round(float(x), 2))

        styled = (
            df.style
            .apply(_style_report_type, subset=["Report Type"])
        )

        st.dataframe(
            styled,
            column_config={
                "Score": st.column_config.NumberColumn("Score", format="%.2f"),
                "YouTube Link": st.column_config.LinkColumn("YouTube Link", display_text="Watch"),
                "Title": st.column_config.TextColumn("Title", width="medium"),
                "Summary": st.column_config.TextColumn("Summary", width="large"),
            },
            column_order=["Rank", "Score", "Title", "Summary", "Channel", "Report Type", "Relevance", "Views/hr", "YouTube Link"],
            hide_index=True,
            use_container_width=True,
        )

    # ── PDF Report ────────────────────────────────────────────────────────────
    st.divider()
    if st.button("Generate PDF Report"):
        from fpdf import FPDF

        def _safe(text):
            return "".join(c if ord(c) < 256 else "?" for c in str(text))

        class PolitiScanPDF(FPDF):
            def footer(self):
                self.set_y(-15)
                self.set_font("Helvetica", "I", 8)
                self.set_text_color(128, 128, 128)
                self.cell(0, 10, "Confidential - For Internal Use Only", align="C")

        pdf = PolitiScanPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()

        ch_str = _safe(", ".join(meta["selected_channels"])) if meta.get("selected_channels") else "All"

        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "PolitiScan YouTube Intelligence Report", ln=True, align="C")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, f"Language: {meta['language']}  |  Channels: {ch_str}", ln=True, align="C")
        pdf.cell(
            0, 6,
            f"Time Period: {meta['time_period']}  |  "
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC",
            ln=True, align="C",
        )
        pdf.ln(6)

        pdf.set_fill_color(230, 230, 230)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, "Scan Summary", ln=True, fill=True)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(
            0, 6,
            f"Total Fetched: {meta['total_fetched']}   |   "
            f"Non-political Removed: {meta['non_political_removed']}   |   "
            f"Ranked: {meta['political_ranked']}",
            ln=True,
        )
        pdf.ln(6)

        for rank_idx, v in enumerate(display_results, 1):
            score = round(v.get("final_score", 0), 2)
            evs = v.get("engagement_velocity_score", 0)
            tag = _safe(v.get("primary_tag", ""))
            title = _safe(v.get("title", ""))
            channel = _safe(v.get("channel_name", ""))
            upload_time = v.get("published_at", "")[:16].replace("T", " ")
            vph = int(v.get("views_per_hour", 0))
            summary_text = _safe(v.get("summary", ""))
            url = v.get("youtube_url", "")
            t_status = v.get("transcript_status", "")
            report_type = v.get("report_type", "CONFIRMED")
            trending_label = "  [VIRAL]" if evs > 7 else "  [RISING]" if evs >= 5 else "  [ACTIVE]" if evs >= 3 else ""

            pdf.set_fill_color(235, 235, 245)
            pdf.set_draw_color(180, 180, 180)
            pdf.set_line_width(0.3)
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(
                0, 7,
                f"#{rank_idx}   Score: {score}   [{tag}]{trending_label}",
                ln=True, fill=True, border="TLR",
            )

            pdf.set_font("Helvetica", "B", 10)
            pdf.multi_cell(0, 6, f"{title}  [{report_type}]", border="LR")

            if report_type == "SPECULATIVE":
                signals = v.get("speculation_signals", [])
                if signals:
                    pdf.set_font("Helvetica", "I", 8)
                    pdf.cell(
                        0, 5,
                        _safe(f"    Signals: {_truncate_signals(signals)}"),
                        ln=True, border="LR",
                    )

            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(
                0, 6,
                f"{channel}  |  Uploaded: {upload_time}  |  Views/hr: {vph:,}",
                ln=True, border="LR",
            )

            pdf.set_font("Helvetica", "", 9)
            pdf.multi_cell(0, 5, summary_text, border="LR")

            if t_status == "Title Only":
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_fill_color(255, 245, 200)
                pdf.cell(
                    0, 5,
                    "  Note: Transcript unavailable - summary based on title only.",
                    ln=True, fill=True, border="LR",
                )
                pdf.set_fill_color(235, 235, 245)

            pdf.set_font("Helvetica", "U", 8)
            pdf.set_text_color(0, 0, 200)
            pdf.cell(0, 6, url, ln=True, border="LRB")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(4)

        pdf_bytes = bytes(pdf.output())
        st.download_button(
            label="Download PDF",
            data=pdf_bytes,
            file_name=f"politiscan_youtube_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
        )

elif "yt_results" in st.session_state and len(st.session_state["yt_results"]) == 0:
    st.warning("No political videos found. Try a longer time period or different channels.")
