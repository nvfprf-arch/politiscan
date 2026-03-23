# NEWS SOURCE: Google News RSS + NewsData.io

import os
import json
import time
import threading
import urllib.request
import urllib.parse
from collections import Counter
from datetime import datetime, timezone, timedelta
from io import BytesIO

from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import feedparser
import anthropic
from fpdf import FPDF

from regions import REGIONS
from outlets import STATE_OUTLETS, OUTLET_DOMAINS
from ranker import rank_articles
from deduplicator import deduplicate_all
from translation import process_article
from pdf_handler import fetch_article_content

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch_feed(url: str, results: list, index: int):
    """Fetch a single Google News RSS feed and store entries in results[index]."""
    try:
        feed = feedparser.parse(url)
        results[index] = feed.entries
    except Exception:
        results[index] = []


def _build_queries(location: str) -> list[str]:
    """Return 4 time-bounded queries for a given location string."""
    return [
        f"{location} politics when:2d",
        f"{location} BJP Congress when:2d",
        f"{location} MLA minister when:2d",
        f"{location} election protest when:2d",
    ]


def _build_outlet_queries(location: str, domain: str) -> list[str]:
    """Return 4 site-filtered queries for a specific outlet domain."""
    return [
        f"{location} politics site:{domain} when:2d",
        f"{location} BJP Congress site:{domain} when:2d",
        f"{location} MLA minister site:{domain} when:2d",
        f"{location} election protest site:{domain} when:2d",
    ]


def _run_feeds(queries: list[str]) -> list:
    """Fetch all queries in parallel and return combined entries."""
    base = "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q="
    urls = [base + q.replace(" ", "+") for q in queries]
    results = [None] * len(urls)
    threads = [
        threading.Thread(target=fetch_feed, args=(url, results, i))
        for i, url in enumerate(urls)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    combined = []
    for entries in results:
        if entries:
            combined.extend(entries)
    return combined


def fetch_all_feeds(district: str, state: str, selected_outlets: list | None = None) -> tuple[list, str]:
    """Fetch news with district+state queries, falling back to state-only if needed.
    When selected_outlets is provided, also runs 4 site-filtered queries per outlet.
    Returns (combined_entries, scope_used) where scope_used is 'district' or 'state'.
    """
    location = f"{district} {state}"
    queries = _build_queries(location)
    for outlet in (selected_outlets or []):
        domain = OUTLET_DOMAINS.get(outlet)
        if domain:
            queries.extend(_build_outlet_queries(location, domain))

    entries = _run_feeds(queries)
    recent, _ = filter_recent(entries, hours=36)
    if recent:
        return entries, "district"

    # Fallback: state-only queries
    state_queries = _build_queries(state)
    for outlet in (selected_outlets or []):
        domain = OUTLET_DOMAINS.get(outlet)
        if domain:
            state_queries.extend(_build_outlet_queries(state, domain))

    entries = _run_feeds(state_queries)
    return entries, "state"


def parse_published(entry) -> datetime | None:
    """Return timezone-aware datetime from a feed entry, or None."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    return None


def filter_recent(entries: list, hours: int = 36) -> tuple[list, list]:
    """Keep only articles published within the last `hours` hours.
    Returns (kept, rejected) — both are plain entry lists.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    kept, rejected = [], []
    for e in entries:
        pub = parse_published(e)
        (kept if (pub is None or pub >= cutoff) else rejected).append(e)
    return kept, rejected


def word_overlap(title1: str, title2: str) -> float:
    """Return Jaccard word-overlap ratio between two strings."""
    words1 = set(title1.lower().split())
    words2 = set(title2.lower().split())
    if not words1 or not words2:
        return 0.0
    return len(words1 & words2) / len(words1 | words2)


def deduplicate(entries: list, threshold: float = 0.70) -> list:
    """Remove entries whose titles share > threshold word overlap with kept entries."""
    unique = []
    for entry in entries:
        title = getattr(entry, "title", "") or ""
        duplicate = False
        for kept in unique:
            kept_title = getattr(kept, "title", "") or ""
            if word_overlap(title, kept_title) > threshold:
                duplicate = True
                break
        if not duplicate:
            unique.append(entry)
    return unique


def get_outlet(entry) -> str:
    """Extract news outlet name from feed entry source or link."""
    if hasattr(entry, "source") and isinstance(entry.source, dict):
        return entry.source.get("title", "Unknown")
    link = getattr(entry, "link", "") or ""
    if "news.google.com" in link:
        return "Google News"
    try:
        from urllib.parse import urlparse
        host = urlparse(link).netloc
        return host.replace("www.", "") if host else "Unknown"
    except Exception:
        return "Unknown"


def summarize_article(title: str, description: str) -> str:
    """Call Claude Haiku to produce a 4-line political summary."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return "API key not configured."
    client = anthropic.Anthropic(api_key=api_key)
    prompt = (
        "You are a political analyst. Summarize this Indian political news in exactly 4 lines "
        "with no formatting or symbols. "
        "Line 1 starts with What happened:. "
        "Line 2 starts with Who is involved:. "
        "Line 3 starts with Where:. "
        "Line 4 starts with Why it matters:.\n\n"
        f"Article: {title}\n{description}"
    )
    for attempt in range(3):
        try:
            time.sleep(0.5)
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            text = message.content[0].text.strip()
            for char in ("*", "#"):
                text = text.replace(char, "")
            return " ".join(text.split())
        except anthropic.RateLimitError:
            if attempt < 2:
                time.sleep(60)
            else:
                return "Summary unavailable — rate limit reached."
        except Exception:
            return "Summary unavailable."


def entries_to_dicts(entries: list, channel: str = "rss") -> list:
    """Convert feedparser entries to ranker-compatible dicts."""
    dicts = []
    for e in entries:
        pub = parse_published(e)
        dicts.append({
            "headline":      getattr(e, "title", "") or "",
            "snippet":       getattr(e, "summary", "") or getattr(e, "description", "") or "",
            "source_name":   get_outlet(e),
            "published_iso": pub.isoformat() if pub else "",
            "url":           getattr(e, "link", "") or "",
            "source_channel": channel,
        })
    return dicts


def fetch_newsdata_articles(district: str, state: str, domains: list, api_key: str) -> list:
    """Fetch recent articles from NewsData.io filtered to specified outlet domains.
    Returns a list of ranker-compatible dicts with source_channel='newsdata'.
    """
    if not api_key or not domains:
        return []

    location = f"{district} {state}"
    queries = [
        f"{location} politics",
        f"{location} election BJP Congress MLA minister",
    ]
    domain_str = ",".join(domains)
    base_url = "https://newsdata.io/api/1/latest"
    all_articles = []

    for q in queries:
        params = {
            "apikey":    api_key,
            "q":         q,
            "country":   "in",
            "language":  "en",
            "category":  "politics",
            "domainurl": domain_str,
        }
        url = base_url + "?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PolitiScan/1.1"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            for item in data.get("results", []):
                all_articles.append({
                    "headline":      item.get("title", ""),
                    "snippet":       (item.get("description") or item.get("content") or "")[:600],
                    "source_name":   item.get("source_id", "Unknown"),
                    "published_iso": item.get("pubDate", ""),
                    "url":           item.get("link", ""),
                    "source_channel": "newsdata",
                })
        except Exception:
            pass

    # Filter to last 36 hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
    recent = []
    for art in all_articles:
        try:
            pub = datetime.fromisoformat(art["published_iso"].replace(" ", "T").replace("Z", "+00:00"))
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            if pub >= cutoff:
                recent.append(art)
        except Exception:
            recent.append(art)  # include if date unparseable

    # Deduplicate by URL
    seen: set = set()
    unique = []
    for art in recent:
        if art["url"] and art["url"] not in seen:
            seen.add(art["url"])
            unique.append(art)

    return unique


def summarize_all(
    ranked_articles: list,
    state: str = "",
    api_keys: dict | None = None,
    progress_bar=None,
    status_text=None,
) -> list:
    """Summarise ranked article dicts in parallel (max 5 workers).
    Detects language and produces a 4-line English summary via process_article.
    Adds 'Summary' and '_language' keys to each dict; returns list in original order.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    _api_keys = api_keys or {}
    total     = len(ranked_articles)
    rows      = [None] * total
    completed = 0

    def _process(i, art):
        title = art.get("headline", "No Title")
        url   = art.get("url", "")

        # Fetch full article content before translation/summarisation
        fetched_text, source_type = fetch_article_content(url, state)

        if fetched_text:
            article_text = f"{title}\n{fetched_text}"
        else:
            desc         = art.get("snippet") or art.get("content", "")
            article_text = f"{title}\n{desc}"

        result = process_article(article_text, state, _api_keys)
        return i, {
            **art,
            "Summary":      result["summary"],
            "_language":    result["original_language"],
            "_source_type": source_type,
        }

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_process, i, a): i for i, a in enumerate(ranked_articles)}
        for future in as_completed(futures):
            i, row = future.result()
            rows[i] = row
            completed += 1
            label = f"Summarising article {completed} of {total}..."
            if progress_bar is not None:
                progress_bar.progress(completed / total, text=label)
            if status_text is not None:
                status_text.caption(label)

    return rows


# ---------------------------------------------------------------------------
# PDF Generation
# ---------------------------------------------------------------------------

class PolitiScanPDF(FPDF):
    def __init__(self, region_label: str, scan_date: str):
        super().__init__()
        self.region_label = region_label
        self.scan_date = scan_date

    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.cell(0, 10, "PolitiScan", ln=True, align="C")
        self.set_font("Helvetica", "", 11)
        self.cell(0, 7, f"Region: {self.region_label}", ln=True, align="C")
        self.cell(0, 7, f"Date: {self.scan_date}", ln=True, align="C")
        self.ln(4)
        self.set_draw_color(180, 180, 180)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, "Confidential - For Internal Use Only", align="C")
        self.set_text_color(0, 0, 0)

def generate_pdf(articles: list, region_label: str) -> bytes:
    def safe(text: str) -> str:
        return (text or "").encode("latin-1", errors="replace").decode("latin-1")

    scan_date = datetime.now().strftime("%d %B %Y")
    pdf = PolitiScanPDF(region_label=region_label, scan_date=scan_date)
    pdf.set_margins(left=20, top=15, right=20)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    W = 170  # explicit content width — never use w=0 on multi_cell

    for i, art in enumerate(articles, start=1):
        rank       = art.get("Rank", i)
        score      = art.get("Score", "")
        tag        = art.get("Tag", "")
        rtype      = art.get("_report_type", "CONFIRMED")
        score_tag  = f"  [Score: {score}]  [{tag}]  [{rtype}]" if (score or tag) else f"  [{rtype}]"
        headline   = safe(f"#{rank}{score_tag}  {art.get('Headline', '')}")
        sc            = art.get("_source_count", 1)
        sources_list  = art.get("_sources_list", [art.get("News Outlet", "Unknown")])
        if sc >= 2:
            source_line = safe(f"Covered by {sc} outlets: {', '.join(sources_list)}")
        else:
            source_line = safe(f"Source: {(sources_list[0] if sources_list else art.get('News Outlet', 'Unknown')) or 'Unknown'}")
        summary  = safe(art.get("Summary", ""))
        raw_url  = art.get("Link", "") or ""
        url      = safe(raw_url if len(raw_url) <= 80 else raw_url[:77] + "...")

        try:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(w=W, h=6, txt=headline, ln=True)
        except Exception:
            pass

        try:
            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(w=W, h=5, txt=source_line, ln=True)
        except Exception:
            pass

        if rtype == "SPECULATIVE":
            raw_sigs = art.get("_signals", "")
            if raw_sigs:
                try:
                    pdf.set_font("Helvetica", "I", 8)
                    pdf.cell(w=W, h=4, txt=safe(f"    Signals: {raw_sigs}"), ln=True)
                except Exception:
                    pass

        try:
            pdf.set_font("Helvetica", "", 9)
            pdf.multi_cell(w=W, h=5, txt=summary)
        except Exception:
            pass

        try:
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(0, 0, 180)
            pdf.multi_cell(w=W, h=4, txt=url)
            pdf.set_text_color(0, 0, 0)
        except Exception:
            pdf.set_text_color(0, 0, 0)

        pdf.ln(5)

    return pdf.output()


def _truncate_signals(signals: list, max_len: int = 80) -> str:
    """Join speculation signals into a string, truncated to max_len chars."""
    if not signals:
        return ""
    joined = ", ".join(str(s) for s in signals)
    return joined if len(joined) <= max_len else joined[:max_len - 1] + "…"


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="PolitiScan", page_icon="🗳️", layout="wide")
st.title("PolitiScan")
st.markdown("#### Political Intelligence Dashboard")



_COL_ORDER = ["Rank", "Score", "Tag", "Region", "Report Type", "Signals",
              "Headline", "Sources", "Language", "Summary", "Link"]

_TYPE_STYLES = {
    "CONFIRMED":   "background-color: #1a472a; color: white",
    "SPECULATIVE": "background-color: #7d4e00; color: white",
    "ANALYTICAL":  "background-color: #1a3a5c; color: white",
}


def _style_report_type(col):
    """Return a Series of CSS strings for the Report Type column."""
    return col.map(lambda v: _TYPE_STYLES.get(v, ""))


def _show_results():
    """Render caption, filtered+styled table, and download button from session state."""
    import pandas as pd

    st.info(st.session_state.results_caption)

    # Source breakdown above results table
    if "source_breakdown" in st.session_state:
        bd = st.session_state.source_breakdown
        rss_total     = bd.get("rss_total", 0)
        nd_total      = bd.get("newsdata_total", 0)
        outlet_counts = bd.get("outlet_counts", {})

        header_parts = [f"**{rss_total}** articles from RSS"]
        if nd_total:
            header_parts.append(f"**{nd_total}** from NewsData.io")

        top_outlets = sorted(outlet_counts.items(), key=lambda x: -x[1])[:8]
        outlet_str  = "   ".join(f"**{k}:** {v}" for k, v in top_outlets)

        breakdown_line = "   ".join(header_parts)
        if outlet_str:
            breakdown_line += "   —   " + outlet_str
        st.caption(breakdown_line)

    all_rows       = st.session_state.results_rows
    selected_tags  = st.session_state.get("selected_tags", [])
    selected_types = st.session_state.get("selected_report_types", ["CONFIRMED", "SPECULATIVE", "ANALYTICAL"])

    filtered = all_rows
    if selected_tags:
        filtered = [r for r in filtered if r.get("Tag") in selected_tags]
    if selected_types:
        filtered = [r for r in filtered if r.get("_report_type", "CONFIRMED") in selected_types]

    # Sort by Score descending and re-sequence Rank
    filtered = sorted(filtered, key=lambda r: r.get("Score", 0), reverse=True)
    for i, r in enumerate(filtered, start=1):
        r["Rank"] = i

    # Build DataFrame with exact column order; drop internal _ keys
    df = pd.DataFrame([{c: r.get(c, "") for c in _COL_ORDER} for r in filtered])

    styled = df.style.apply(_style_report_type, subset=["Report Type"])

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Score":    st.column_config.NumberColumn("Score", format="%.1f"),
            "Headline": st.column_config.TextColumn("Headline", width="medium"),
            "Summary":  st.column_config.TextColumn("Summary",  width="medium"),
            "Link":     st.column_config.LinkColumn("Link", display_text="Read"),
        },
    )
    st.divider()
    st.download_button(
        label="Download PDF Report",
        data=st.session_state.pdf_buffer,
        file_name=st.session_state.pdf_filename,
        mime="application/pdf",
        type="secondary",
    )


with st.sidebar:
    st.header("Scan Parameters")
    state    = st.selectbox("State / UT", sorted(REGIONS.keys()))
    district = st.selectbox("District", REGIONS[state])
    zone     = st.text_input("Administrative Zone", placeholder="e.g. North Zone")

    state_outlet_options = ["All Outlets"] + STATE_OUTLETS.get(state, [])
    selected_outlets = st.multiselect(
        "News Outlets",
        options=state_outlet_options,
        default=["All Outlets"],
        placeholder="Select outlets to filter...",
    )
    # "All Outlets" in selection (or nothing selected) means no outlet filter
    active_outlets = [o for o in selected_outlets if o != "All Outlets"]

    scan_clicked = st.button("Scan News", type="primary", use_container_width=True)

    # Tag filter + Story Sources — only shown when results are available
    if "results_rows" in st.session_state and st.session_state.results_rows:
        st.divider()
        st.subheader("Filter Results")
        available_tags = sorted({r.get("Tag", "") for r in st.session_state.results_rows if r.get("Tag")})
        selected_tags = st.multiselect(
            "Tag Filter",
            options=available_tags,
            default=st.session_state.get("selected_tags", []),
            placeholder="Show all tags",
        )
        st.session_state.selected_tags = selected_tags

        selected_report_types = st.multiselect(
            "Show Report Types",
            options=["CONFIRMED", "SPECULATIVE", "ANALYTICAL"],
            default=st.session_state.get("selected_report_types", ["CONFIRMED", "SPECULATIVE", "ANALYTICAL"]),
        )
        st.session_state.selected_report_types = selected_report_types

        st.divider()
        with st.expander("Story Sources"):
            multi_source_rows = [
                r for r in st.session_state.results_rows
                if r.get("_source_count", 1) >= 2
            ]
            if not multi_source_rows:
                st.caption("No stories with multiple sources found.")
            else:
                headlines = [r.get("Headline", f"Story {i+1}") for i, r in enumerate(multi_source_rows)]
                selected_hl = st.selectbox("Select story", headlines, label_visibility="collapsed")
                chosen = next((r for r in multi_source_rows if r.get("Headline") == selected_hl), None)
                if chosen:
                    for src in chosen.get("_sources_list", []):
                        st.markdown(f"- {src}")


if scan_clicked:
    # Clear previous results so a fresh scan always re-runs fully
    for key in ("results_rows", "results_caption", "pdf_buffer", "pdf_filename",
                "selected_tags", "selected_report_types", "source_breakdown"):
        st.session_state.pop(key, None)

    api_key      = os.getenv("ANTHROPIC_API_KEY", "")
    region_label = f"{district}, {state}" + (f" ({zone})" if zone.strip() else "")

    with st.spinner("Fetching news from Google News RSS..."):
        raw_entries, scope = fetch_all_feeds(district, state, active_outlets)
        recent, _  = filter_recent(raw_entries, hours=36)
        unique     = deduplicate(recent, threshold=0.70)
        total_fetched = len(unique)

    if not unique:
        st.warning("No recent articles found for the selected region. Try a different district or check back later.")
    else:
        article_dicts = entries_to_dicts(unique, channel="rss")

        # Compute source breakdown from RSS articles before merging
        outlet_counts = Counter(
            a["source_name"] for a in article_dicts
            if a.get("source_name") and a["source_name"] not in ("Unknown", "Google News", "")
        )
        rss_total = len(article_dicts)

        # Fetch NewsData.io articles when specific outlets are selected
        newsdata_dicts: list = []
        if active_outlets:
            nd_api_key  = os.getenv("NEWSDATA_API_KEY", "")
            nd_domains  = [OUTLET_DOMAINS[o] for o in active_outlets if o in OUTLET_DOMAINS]
            if nd_api_key and nd_domains:
                with st.spinner(f"Fetching from NewsData.io ({len(nd_domains)} outlets)..."):
                    newsdata_dicts = fetch_newsdata_articles(district, state, nd_domains, nd_api_key)
                article_dicts = article_dicts + newsdata_dicts

        st.session_state.source_breakdown = {
            "rss_total":      rss_total,
            "newsdata_total": len(newsdata_dicts),
            "outlet_counts":  dict(outlet_counts),
        }

        pre_dedup_count = len(article_dicts)

        with st.spinner("Deduplicating stories across sources..."):
            article_dicts = deduplicate_all(article_dicts, api_key=api_key)
        post_dedup_count = len(article_dicts)

        # Run rank_articles in a background thread and animate a progress bar
        # over an estimated 60 seconds while it works.
        rank_result = [None]
        rank_exc    = [None]

        def _rank_worker():
            try:
                rank_result[0] = rank_articles(
                    article_dicts, state=state, district=district, api_key=api_key
                )
            except Exception as e:
                rank_exc[0] = e

        rank_thread = threading.Thread(target=_rank_worker, daemon=True)
        rank_thread.start()

        ESTIMATE_SECS = 60
        TICK          = 0.25          # seconds between UI updates
        steps         = int(ESTIMATE_SECS / TICK)
        rank_bar      = st.progress(0, text="Analysing article content and ranking by importance... 0% complete")

        for step in range(1, steps + 1):
            if not rank_thread.is_alive():
                break
            time.sleep(TICK)
            pct = min(int(step / steps * 99), 99)   # cap at 99% until truly done
            rank_bar.progress(pct / 100, text=f"Analysing article content and ranking by importance... {pct}% complete")

        rank_thread.join()
        rank_bar.progress(1.0, text="Analysing article content and ranking by importance... 100% complete")
        rank_bar.empty()

        if rank_exc[0] is not None:
            st.error(f"Ranking failed: {rank_exc[0]}")
            st.stop()

        ranked = rank_result[0] or []

        non_political = total_fetched - len(ranked)
        scope_note    = f" (state-level results for {state})" if scope == "state" else ""

        _api_keys    = {"anthropic": api_key, "sarvam": os.getenv("SARVAM_API_KEY", "")}
        progress_bar = st.progress(0, text=f"Summarising article 0 of {len(ranked)}...")
        status_text  = st.empty()
        summarized   = summarize_all(
            ranked,
            state=state,
            api_keys=_api_keys,
            progress_bar=progress_bar,
            status_text=status_text,
        )
        progress_bar.empty()
        status_text.empty()

        # Build display rows — ALL ranked articles with real summaries
        summarized_map = {
            a["url"]: {
                "summary":     a.get("Summary", ""),
                "language":    a.get("_language", "English"),
                "source_type": a.get("_source_type", "html"),
            }
            for a in summarized
        }
        rows = []
        for i, art in enumerate(ranked, start=1):
            sc              = art.get("source_count", 1)
            report_type     = art.get("report_type", "CONFIRMED")
            signals_str     = _truncate_signals(art.get("speculation_signals", []))
            sources_display = art.get("source_name", "Unknown") if sc <= 1 else f"{sc} outlets"
            sm              = summarized_map.get(art.get("url", ""), {})
            source_type     = sm.get("source_type", "html")
            summary_text    = sm.get("summary", "")
            if source_type == "failed":
                summary_text = "[Manual Review Required]  " + summary_text
            rows.append({
                "Rank":        i,
                "Score":       round(art.get("final_score", 0), 1),
                "Tag":         art.get("primary_tag", ""),
                "Region":      "✓" if art.get("affects_client_region") else "-",
                "Report Type": report_type,
                "Signals":     signals_str,
                "Headline":    art.get("headline", ""),
                "Sources":     sources_display,
                "Language":    sm.get("language", "English"),
                "Summary":     summary_text,
                "Link":        art.get("url", ""),
                # internal keys for sidebar expander, PDF, and report-type filter
                "_source_count": sc,
                "_sources_list": art.get("sources_list", [art.get("source_name", "Unknown")]),
                "_report_type":  report_type,
                "_signals":      signals_str,
            })

        with st.spinner("Generating PDF..."):
            pdf_bytes = bytes(generate_pdf(rows[:15], region_label))

        dupes_merged = pre_dedup_count - post_dedup_count
        caption = (
            f"**{len(rows)} unique stories** from **{len(ranked)} political articles**{scope_note}.  "
            f"{dupes_merged} duplicates merged.  {total_fetched} total fetched.  "
            f"PDF contains top 15."
        )

        st.session_state.results_rows    = rows
        st.session_state.results_caption = caption
        st.session_state.pdf_buffer      = pdf_bytes
        st.session_state.pdf_filename    = (
            f"PolitiScan_{district}_{state}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        )
        _show_results()

elif "results_rows" in st.session_state:
    # Rerun from download click or tag filter change — restore without rescanning
    _show_results()
