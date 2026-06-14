# NEWS SOURCE: NewsData.io primary + Google News RSS secondary

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

# SET TO FALSE BEFORE DEPLOYING
DEV_MODE = False

import streamlit as st
import feedparser
import anthropic
from fpdf import FPDF
from fpdf.enums import XPos, YPos

from regions import REGIONS
from outlets import STATE_OUTLETS, OUTLET_DOMAINS
from ranker import rank_articles
from deduplicator import deduplicate_all
from translation import process_article
from pdf_handler import fetch_article_content
from feedback_store import record_promotion, get_profile_status, should_generate_profile
from profile_analyzer import check_and_refresh_profile, load_client_profile
from allowed_users import ALLOWED_EMAILS
from auth import generate_otp, send_otp_email, verify_otp

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


@st.cache_data(ttl=1800)
def fetch_all_feeds(district: str, state: str, selected_outlets: tuple = ()) -> tuple[list, str]:
    """Fetch news with district+state queries, falling back to state-only if needed.
    When selected_outlets is provided, also runs 4 site-filtered queries per outlet.
    Returns (combined_entries, scope_used) where scope_used is 'district' or 'state'.
    Cached for 30 minutes per district/state/outlets combination.
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
            recent.append(art)

    seen: set = set()
    unique = []
    for art in recent:
        if art["url"] and art["url"] not in seen:
            seen.add(art["url"])
            unique.append(art)

    return unique


def deduplicate_dicts(articles: list, threshold: float = 0.70) -> list:
    """Remove dict articles whose headlines share > threshold word overlap with kept ones."""
    unique = []
    for art in articles:
        title = art.get("headline", "") or ""
        duplicate = False
        for kept in unique:
            if word_overlap(title, kept.get("headline", "") or "") > threshold:
                duplicate = True
                break
        if not duplicate:
            unique.append(art)
    return unique


@st.cache_data(ttl=1800)
def fetch_newsdata_primary(district: str, state: str, api_key: str) -> list:
    """Fetch recent articles from NewsData.io as primary news source.
    Returns a list of ranker-compatible dicts with source_channel='newsdata'.
    Cached for 30 minutes per district/state combination.
    """
    if not api_key:
        return []

    base_params = urllib.parse.urlencode({
        "apikey":   api_key,
        "q":        f"{district} {state} politics",
        "country":  "in",
    })
    url = f"https://newsdata.io/api/1/news?{base_params}&language=en,hi"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PolitiScan/1.3"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        import sys
        print(f"[NewsData] fetch error: {e}", file=sys.stderr)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
    seen: set = set()
    articles = []
    for item in data.get("results", []):
        url_link = item.get("link", "")
        if url_link and url_link in seen:
            continue
        if url_link:
            seen.add(url_link)

        pub_str = item.get("pubDate", "")
        try:
            pub = datetime.fromisoformat(pub_str.replace(" ", "T").replace("Z", "+00:00"))
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            if pub < cutoff:
                continue
            pub_iso = pub.isoformat()
        except Exception:
            pub_iso = pub_str

        full_content = item.get("content") or item.get("description") or ""
        articles.append({
            "headline":       item.get("title", ""),
            "snippet":        (item.get("description") or "")[:600],
            "full_content":   full_content,
            "source_name":    item.get("source_id", "Unknown"),
            "published_iso":  pub_iso,
            "url":            url_link,
            "source_channel": "newsdata",
        })
    return articles


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

        if art.get("source_channel") == "newsdata" and art.get("full_content"):
            article_text = f"{title}\n{art['full_content']}"
            source_type  = "newsdata_full"
        else:
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

    with ThreadPoolExecutor(max_workers=20) as executor:
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
        self.cell(0, 10, "PolitiScan", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        self.set_font("Helvetica", "", 11)
        self.cell(0, 7, f"Region: {self.region_label}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        self.cell(0, 7, f"Date: {self.scan_date}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        self.ln(4)
        self.set_draw_color(180, 180, 180)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, "Confidential - For Internal Use Only", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        self.set_text_color(0, 0, 0)


def generate_pdf(articles: list, region_label: str) -> bytes:
    def safe(text: str) -> str:
        return (text or "").encode("latin-1", errors="replace").decode("latin-1")

    scan_date = datetime.now().strftime("%d %B %Y")
    pdf = PolitiScanPDF(region_label=region_label, scan_date=scan_date)
    pdf.set_margins(left=20, top=15, right=20)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    W = 170

    for i, art in enumerate(articles, start=1):
        rank       = art.get("Rank", i)
        score      = art.get("Score", "")
        tag        = art.get("Tag", "")
        rtype      = art.get("_report_type", "CONFIRMED")
        score_tag  = f"  [Score: {score}]  [{tag}]  [{rtype}]" if (score or tag) else f"  [{rtype}]"
        headline   = safe(f"#{rank}{score_tag}  {art.get('Headline', '')}")
        sc           = art.get("_source_count", 1)
        sources_list = art.get("_sources_list", [art.get("News Outlet", "Unknown")])
        if sc >= 2:
            source_line = safe(f"Covered by {sc} outlets: {', '.join(sources_list)}")
        else:
            source_line = safe(f"Source: {(sources_list[0] if sources_list else art.get('News Outlet', 'Unknown')) or 'Unknown'}")
        summary  = safe(art.get("Summary", ""))
        raw_url  = art.get("Link", "") or ""
        url      = safe(raw_url if len(raw_url) <= 80 else raw_url[:77] + "...")

        try:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(w=W, h=6, text=headline, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        except Exception:
            pass

        try:
            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(w=W, h=5, text=source_line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        except Exception:
            pass

        if rtype == "SPECULATIVE":
            raw_sigs = art.get("_signals", "")
            if raw_sigs:
                try:
                    pdf.set_font("Helvetica", "I", 8)
                    pdf.cell(w=W, h=4, text=safe(f"    Signals: {raw_sigs}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                except Exception:
                    pass

        try:
            pdf.set_font("Helvetica", "", 9)
            pdf.multi_cell(w=W, h=5, text=summary)
        except Exception:
            pass

        try:
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(0, 0, 180)
            pdf.multi_cell(w=W, h=4, text=url)
            pdf.set_text_color(0, 0, 0)
        except Exception:
            pdf.set_text_color(0, 0, 0)

        pdf.ln(5)

    return pdf.output()


class PolitiScanShortlistPDF(FPDF):
    def __init__(self, region_label: str, email: str, scan_date: str):
        super().__init__()
        self.region_label = region_label
        self.email = email
        self.scan_date = scan_date

    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.cell(0, 10, "PolitiScan Intelligence Report", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        self.set_font("Helvetica", "", 10)
        self.cell(0, 6, self.email, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        self.cell(0, 6, f"Region: {self.region_label}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        self.cell(0, 6, f"Date: {self.scan_date}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        self.ln(4)
        self.set_draw_color(180, 180, 180)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, "Confidential - For Internal Use Only", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        self.set_text_color(0, 0, 0)


def generate_pdf_shortlist(articles: list, region_label: str, email: str) -> bytes:
    def safe(text: str) -> str:
        return (text or "").encode("latin-1", errors="replace").decode("latin-1")

    scan_date = datetime.now().strftime("%d %B %Y")
    pdf = PolitiScanShortlistPDF(region_label=region_label, email=email, scan_date=scan_date)
    pdf.set_margins(left=20, top=15, right=20)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    W = 170

    for i, art in enumerate(articles, start=1):
        rank    = art.get("Rank", i)
        score   = art.get("Score", "")
        tag     = art.get("Tag", "")
        rtype   = art.get("_report_type", "CONFIRMED")
        boosted = art.get("_profile_boosted", False)

        meta_parts = [f"#{rank}", f"Score: {score}", f"[{tag}]", f"[{rtype}]"]
        if boosted:
            meta_parts.append("[Personalised]")
        meta_line = safe("  ".join(meta_parts))

        headline = safe(art.get("Headline", ""))
        outlet   = safe(art.get("Sources", "Unknown"))
        summary  = safe(art.get("Summary", ""))
        raw_url  = art.get("Link", "") or ""
        url      = safe(raw_url if len(raw_url) <= 80 else raw_url[:77] + "...")

        try:
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(w=W, h=5, text=meta_line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        except Exception:
            pass

        try:
            pdf.set_font("Helvetica", "B", 10)
            pdf.multi_cell(w=W, h=6, text=headline)
        except Exception:
            pass

        try:
            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(w=W, h=5, text=safe(f"Source: {outlet}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        except Exception:
            pass

        try:
            pdf.set_font("Helvetica", "", 9)
            pdf.multi_cell(w=W, h=5, text=summary)
        except Exception:
            pass

        try:
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(0, 0, 180)
            pdf.multi_cell(w=W, h=4, text=url)
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
    return joined if len(joined) <= max_len else joined[:max_len - 1] + "\u2026"


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="PolitiScan", page_icon="\U0001f5f3\ufe0f", layout="wide")

# ---------------------------------------------------------------------------
# Login gate
# ---------------------------------------------------------------------------
if DEV_MODE:
    st.session_state.logged_in  = True
    st.session_state.user_email = "dev@test.com"

if not st.session_state.get("logged_in"):
    st.title("PolitiScan")
    st.subheader("Political Intelligence Dashboard")

    if not st.session_state.get("otp_sent"):
        email = st.text_input("Email address", key="login_email_input")
        if st.button("Send OTP", type="primary"):
            if email not in ALLOWED_EMAILS:
                st.error("Access denied. Contact your administrator.")
            else:
                otp = generate_otp()
                st.session_state.otp           = otp
                st.session_state.otp_timestamp = datetime.now()
                st.session_state.login_email   = email
                sent, send_err = send_otp_email(email, otp)
                if sent:
                    st.session_state.otp_sent = True
                    st.rerun()
                else:
                    st.error(f"Failed to send OTP: {send_err}")
    else:
        st.success(f"OTP sent to {st.session_state.login_email}. Enter the 6-digit code below.")
        code = st.text_input("6-digit code", max_chars=6, key="otp_input")
        if st.button("Verify", type="primary"):
            if verify_otp(code, st.session_state.otp, st.session_state.otp_timestamp):
                st.session_state.logged_in  = True
                st.session_state.user_email = st.session_state.login_email
                # Clear login state
                for k in ("otp", "otp_timestamp", "otp_sent", "login_email"):
                    st.session_state.pop(k, None)
                st.rerun()
            else:
                st.error("Invalid or expired code. Please try again.")

    st.stop()

# ---------------------------------------------------------------------------
# App title (shown only when logged in)
# ---------------------------------------------------------------------------
st.title("PolitiScan")
st.markdown("#### Political Intelligence Dashboard")

# Load/refresh client profile once per session
if "profile_loaded" not in st.session_state:
    st.session_state.client_profile = check_and_refresh_profile(st.session_state.user_email)
    st.session_state.profile_loaded = True


_COL_ORDER = ["Rank", "Score", "Headline", "Summary", "Sources", "Language", "Report Type", "Link"]

_TYPE_STYLES = {
    "CONFIRMED":   "background-color: #1a472a; color: white",
    "SPECULATIVE": "background-color: #7d4e00; color: white",
    "ANALYTICAL":  "background-color: #1a3a5c; color: white",
}


def _style_report_type(col):
    """Return a Series of CSS strings for the Report Type column."""
    return col.map(lambda v: _TYPE_STYLES.get(v, ""))


_BADGE_CSS = {
    "CONFIRMED":   "background:#1a472a;color:white;padding:2px 8px;border-radius:4px;white-space:nowrap;",
    "SPECULATIVE": "background:#7d4e00;color:white;padding:2px 8px;border-radius:4px;white-space:nowrap;",
    "ANALYTICAL":  "background:#1a3a5c;color:white;padding:2px 8px;border-radius:4px;white-space:nowrap;",
}
_TH = "padding:6px 10px;text-align:left;border-bottom:1px solid #444;white-space:nowrap;"
_TD = "padding:6px 10px;vertical-align:top;"


def _render_article_table(rows: list, show_checkboxes: bool = False) -> None:
    """Render a list of article row dicts as a styled HTML table.
    When show_checkboxes=True, a leading checkbox column is added per row.
    """
    col_headers = ([""] if show_checkboxes else []) + list(_COL_ORDER)
    header_html = "".join(f"<th style='{_TH}'>{c}</th>" for c in col_headers)
    body_html = ""
    for row in rows:
        cells = ""
        if show_checkboxes:
            link = (row.get("Link", "") or "").replace('"', "&quot;")
            cells += (
                f"<td style='{_TD};text-align:center;'>"
                f"<input type='checkbox' class='article-check' value=\"{link}\">"
                f"</td>"
            )
        for col in _COL_ORDER:
            val = row.get(col, "") or ""
            if col == "Report Type":
                s = _BADGE_CSS.get(val, "")
                content = f'<span style="{s}">{val}</span>'
            elif col == "Link":
                content = f'<a href="{val}" target="_blank" style="color:#4da6ff;">Read</a>' if val else ""
            elif col == "Score":
                content = f"{val:.1f}" if isinstance(val, (int, float)) else str(val)
            else:
                content = str(val).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            cells += f"<td style='{_TD}'>{content}</td>"
        body_html += f"<tr>{cells}</tr>"
    st.markdown(
        "<div style='overflow-x:auto;'>"
        "<table style='width:100%;border-collapse:collapse;font-size:13px;'>"
        f"<thead><tr style='background:#2a2a2a;'>{header_html}</tr></thead>"
        f"<tbody>{body_html}</tbody>"
        "</table></div>",
        unsafe_allow_html=True,
    )


def _show_results():
    """Render AI Shortlist section, Read All section, and Export to PDF."""
    import pandas as pd

    st.info(st.session_state.results_caption)

    # Source breakdown
    if "source_breakdown" in st.session_state:
        bd = st.session_state.source_breakdown
        rss_total     = bd.get("rss_total", 0)
        nd_total      = bd.get("newsdata_total", 0)
        outlet_counts = bd.get("outlet_counts", {})

        header_parts = []
        if nd_total:
            header_parts.append(f"**{nd_total}** from NewsData.io (primary)")
        header_parts.append(f"**{rss_total}** from Google RSS (secondary)")

        top_outlets = sorted(outlet_counts.items(), key=lambda x: -x[1])[:8]
        outlet_str  = "   ".join(f"**{k}:** {v}" for k, v in top_outlets)

        breakdown_line = "   ".join(header_parts)
        if outlet_str:
            breakdown_line += "   \u2014   " + outlet_str
        st.caption(breakdown_line)

    all_rows       = st.session_state.results_rows
    total_political = len(all_rows)
    selected_type = st.session_state.get("selected_report_types", "All Report Types")

    filtered = all_rows
    if selected_type and selected_type != "All Report Types":
        filtered = [r for r in filtered if r.get("_report_type", "CONFIRMED") == selected_type]

    filtered = sorted(filtered, key=lambda r: r.get("_client_adjusted_score", r.get("Score", 0)), reverse=True)
    for i, r in enumerate(filtered, start=1):
        r["Rank"] = i

    # -------------------------------------------------------------------
    # SECTION 1 — AI Shortlist
    # -------------------------------------------------------------------
    shortlist = st.session_state.get("shortlist_articles", [])
    if selected_type and selected_type != "All Report Types":
        shortlist = [r for r in shortlist if r.get("_report_type", "CONFIRMED") == selected_type]
    shortlist_urls = {r.get("Link") for r in shortlist}

    st.subheader(f"AI Shortlist ({len(shortlist)} articles)")
    if shortlist:
        _render_article_table(shortlist)
    else:
        st.caption("No articles above shortlist threshold yet. Promote articles below to train your shortlist.")

    st.divider()

    # -------------------------------------------------------------------
    # SECTION 2 — Read All button + non-shortlist articles
    # -------------------------------------------------------------------
    non_shortlist = [r for r in filtered if r.get("Link") not in shortlist_urls]

    if st.button(f"Read All \u2014 {total_political} articles scanned"):
        st.session_state.show_all_articles = not st.session_state.get("show_all_articles", False)

    if st.session_state.get("show_all_articles", False):
        st.subheader("All Scanned Articles \u2014 not in shortlist")
        if non_shortlist:
            # JS: use a MutationObserver so the sticky class survives Streamlit re-renders
            st.markdown("""
<style>
.ps-sticky-btn {
    position: fixed !important;
    bottom: 30px !important;
    right: 30px !important;
    z-index: 9999 !important;
}
.ps-sticky-btn button {
    background-color: #FF4B4B !important;
    color: white !important;
    padding: 12px 28px !important;
    border-radius: 8px !important;
    font-size: 15px !important;
    font-weight: 600 !important;
    box-shadow: 0 4px 14px rgba(0,0,0,0.35) !important;
    border: none !important;
}
</style>
<script>
(function() {
    function tagBtn() {
        var btns = document.querySelectorAll('button');
        for (var i = 0; i < btns.length; i++) {
            if (btns[i].textContent.trim() === 'Add to Shortlist') {
                var wrap = btns[i].closest('[data-testid="stButton"]');
                if (wrap && !wrap.classList.contains('ps-sticky-btn')) {
                    wrap.classList.add('ps-sticky-btn');
                }
                return;
            }
        }
    }
    tagBtn();
    new MutationObserver(tagBtn).observe(document.body, { childList: true, subtree: true });
})();
</script>
""", unsafe_allow_html=True)

            editor_rows = [
                {"selected": False, **{c: row.get(c, "") for c in _COL_ORDER}}
                for row in non_shortlist
            ]
            edit_df = pd.DataFrame(editor_rows)[["selected"] + list(_COL_ORDER)]
            edited = st.data_editor(
                edit_df,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "selected": st.column_config.CheckboxColumn("Add?", default=False),
                    "Score":    st.column_config.NumberColumn("Score", format="%.1f"),
                    "Headline": st.column_config.TextColumn("Headline", width="large"),
                    "Summary":  st.column_config.TextColumn("Summary",  width="large"),
                    "Link":     st.column_config.LinkColumn("Link", display_text="Read"),
                },
                key="all_articles_editor",
            )

            if st.button("Add to Shortlist", key="add_shortlist_btn"):
                selected_links = set(edited.loc[edited["selected"] == True, "Link"].tolist())
                count = 0
                for row in non_shortlist:
                    if row.get("Link") in selected_links:
                        article = {
                            "url":          row.get("Link", ""),
                            "headline":     row.get("Headline", ""),
                            "primary_tag":  row.get("Tag", ""),
                            "final_score":  row.get("Score", 0),
                            "source_name":  row.get("Sources", ""),
                            "affects_client_region": False,
                        }
                        record_promotion(st.session_state.user_email, article)
                        if row not in st.session_state.shortlist_articles:
                            st.session_state.shortlist_articles.append(row)
                        count += 1
                if count > 0:
                    st.success(f"{count} article{'s' if count != 1 else ''} added to your shortlist.")
                    st.rerun()
        else:
            st.caption("All scanned articles are already in your shortlist.")

    st.divider()

    # -------------------------------------------------------------------
    # Export to PDF
    # -------------------------------------------------------------------
    shortlist_for_pdf = st.session_state.get("shortlist_articles", [])
    region_label      = st.session_state.get("region_label", "")
    email             = st.session_state.user_email

    if shortlist_for_pdf:
        pdf_bytes = bytes(generate_pdf_shortlist(shortlist_for_pdf, region_label, email))
        safe_region = region_label.replace(", ", "_").replace(" ", "_").replace("(", "").replace(")", "")
        filename = f"PolitiScan_{safe_region}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        st.download_button(
            label=f"Export to PDF ({len(shortlist_for_pdf)} articles)",
            data=pdf_bytes,
            file_name=filename,
            mime="application/pdf",
            type="secondary",
        )
    else:
        st.button("Export to PDF", disabled=True)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.caption(f"Logged in as **{st.session_state.user_email}**")
    if st.button("Logout", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
    st.divider()
    st.header("Scan Parameters")
    state    = st.selectbox("State / UT", sorted(REGIONS.keys()))
    district = st.selectbox("District", REGIONS[state])

    state_outlet_options = ["All Outlets"] + STATE_OUTLETS.get(state, [])

    # Reset outlet selection when state changes
    if st.session_state.get("_outlets_for_state") != state:
        st.session_state["_outlets_for_state"] = state
        st.session_state["_outlet_selection"] = ["All Outlets"]

    _prev = st.session_state.get("_outlet_selection", ["All Outlets"])
    # If user added a specific outlet alongside "All Outlets", drop "All Outlets"
    if len(_prev) > 1 and "All Outlets" in _prev:
        st.session_state["_outlet_selection"] = [o for o in _prev if o != "All Outlets"]
    # If user cleared everything, reset to "All Outlets"
    elif len(_prev) == 0:
        st.session_state["_outlet_selection"] = ["All Outlets"]

    selected_outlets = st.multiselect(
        "News Outlets",
        options=state_outlet_options,
        default=["All Outlets"],
        key="_outlet_selection",
    )
    active_outlets = [] if selected_outlets == ["All Outlets"] else [o for o in selected_outlets if o != "All Outlets"]

    scan_clicked = st.button("Scan News", type="primary", use_container_width=True)

    # Learning status badge
    try:
        profile_status = get_profile_status(st.session_state.user_email)
        if profile_status["status"] == "collecting":
            days_active = profile_status.get("days_active", 0)
            st.info(
                f"**Learning Mode \u2014 Day {days_active} of 30**\n\n"
                "Promote missed articles below to train your shortlist."
            )
        else:
            st.success("**Your Personal Profile is Active**")
    except Exception:
        pass

    # Story Sources — only shown when results are available
    if "results_rows" in st.session_state and st.session_state.results_rows:
        st.divider()
        st.subheader("Filter Results")
        selected_report_type = st.selectbox(
            "Show Report Types",
            options=["All Report Types", "CONFIRMED", "SPECULATIVE", "ANALYTICAL"],
        )
        st.session_state.selected_report_types = selected_report_type

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


# ---------------------------------------------------------------------------
# Scan logic
# ---------------------------------------------------------------------------

if scan_clicked:
    # Clear previous results so a fresh scan always re-runs fully
    for key in ("results_rows", "results_caption", "pdf_buffer", "pdf_filename",
                "selected_report_types", "source_breakdown",
                "shortlist_articles", "show_all_articles"):
        st.session_state.pop(key, None)

    api_key      = os.getenv("ANTHROPIC_API_KEY", "")
    region_label = f"{district}, {state}"
    st.session_state.region_label = region_label

    rss_result = [None, None]
    nd_result  = [[]]

    def _rss_worker():
        entries, scope_val = fetch_all_feeds(district, state, tuple(active_outlets))
        rss_result[0] = entries
        rss_result[1] = scope_val

    def _nd_worker():
        import sys
        try:
            try:
                _key = (st.secrets.get("NEWSDATA_API_KEY") or "").strip()
            except Exception:
                _key = ""
            if not _key:
                _key = os.getenv("NEWSDATA_API_KEY", "").strip()
            nd_result[0] = fetch_newsdata_primary(district, state, _key)
        except Exception as _e:
            print(f"[NewsData Thread Error] {_e}", file=sys.stderr)
            nd_result[0] = []

    with st.spinner("Fetching news from NewsData.io and Google News RSS simultaneously..."):
        t_rss = threading.Thread(target=_rss_worker, daemon=True)
        t_nd  = threading.Thread(target=_nd_worker,  daemon=True)
        t_rss.start(); t_nd.start()
        t_rss.join();  t_nd.join()

    raw_entries    = rss_result[0] or []
    scope          = rss_result[1] or "district"
    newsdata_dicts = nd_result[0] or []

    recent, _  = filter_recent(raw_entries, hours=36)
    unique_rss = deduplicate(recent, threshold=0.70)
    rss_dicts  = entries_to_dicts(unique_rss, channel="rss")
    rss_total  = len(rss_dicts)

    unique_nd     = deduplicate_dicts(newsdata_dicts, threshold=0.70)
    nd_count      = len(unique_nd)
    total_fetched = rss_total + nd_count
    article_dicts = rss_dicts + unique_nd

    if not article_dicts:
        st.warning("No recent articles found for the selected region. Try a different district or check back later.")
    else:
        outlet_counts = Counter(
            a["source_name"] for a in rss_dicts
            if a.get("source_name") and a["source_name"] not in ("Unknown", "Google News", "")
        )

        st.session_state.source_breakdown = {
            "rss_total":      rss_total,
            "newsdata_total": nd_count,
            "outlet_counts":  dict(outlet_counts),
        }

        pre_dedup_count = len(article_dicts)

        with st.spinner("Deduplicating stories across sources..."):
            article_dicts = deduplicate_all(article_dicts, api_key=api_key)
        post_dedup_count = len(article_dicts)

        # Capture profile before thread starts
        _client_profile = st.session_state.get("client_profile")

        rank_result = [None]
        rank_exc    = [None]

        def _rank_worker():
            try:
                rank_result[0] = rank_articles(
                    article_dicts, state=state, district=district,
                    api_key=api_key, client_profile=_client_profile,
                )
            except Exception as e:
                rank_exc[0] = e

        rank_thread = threading.Thread(target=_rank_worker, daemon=True)
        rank_thread.start()

        ESTIMATE_SECS = 60
        TICK          = 0.25
        steps         = int(ESTIMATE_SECS / TICK)
        rank_bar      = st.progress(0, text="Analysing article content and ranking by importance... 0% complete")

        for step in range(1, steps + 1):
            if not rank_thread.is_alive():
                break
            time.sleep(TICK)
            pct = min(int(step / steps * 99), 99)
            rank_bar.progress(pct / 100, text=f"Analysing article content and ranking by importance... {pct}% complete")

        rank_thread.join()
        rank_bar.progress(1.0, text="Analysing article content and ranking by importance... 100% complete")
        rank_bar.empty()

        if rank_exc[0] is not None:
            st.error(f"Ranking failed: {rank_exc[0]}")
            st.stop()

        ranked = rank_result[0] or []

        scope_note = f" (state-level results for {state})" if scope == "state" else ""

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

            client_adj = art.get("client_adjusted_score", art.get("final_score", 0))

            rows.append({
                "Rank":        i,
                "Score":       round(client_adj, 1),
                "Tag":         art.get("primary_tag", ""),
                "Region":      "\u2713" if art.get("affects_client_region") else "-",
                "Report Type": report_type,
                "Signals":     signals_str,
                "Headline":    art.get("headline", ""),
                "Sources":     sources_display,
                "Language":    sm.get("language", "English"),
                "Summary":     summary_text,
                "Link":        art.get("url", ""),
                # internal keys
                "_source_count":          sc,
                "_sources_list":          art.get("sources_list", [art.get("source_name", "Unknown")]),
                "_report_type":           report_type,
                "_signals":               signals_str,
                "_client_adjusted_score": client_adj,
                "_profile_boosted":       art.get("profile_boosted", False),
            })

        # Initialise shortlist: score >= 7.0, capped at 15
        st.session_state.shortlist_articles = [
            r for r in rows if r.get("_client_adjusted_score", 0) >= 7.0
        ][:15]

        dupes_merged = pre_dedup_count - post_dedup_count
        caption = (
            f"**{len(rows)} unique stories** from **{len(ranked)} political articles**{scope_note}.  "
            f"{dupes_merged} duplicates merged.  "
            f"{total_fetched} articles total - {nd_count} from NewsData.io, {rss_total} from Google RSS."
        )

        st.session_state.results_rows    = rows
        st.session_state.results_caption = caption
        _show_results()

elif "results_rows" in st.session_state:
    _show_results()
