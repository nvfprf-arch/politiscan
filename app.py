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

from theme import apply_newspaper_theme

# SET TO FALSE BEFORE DEPLOYING
DEV_MODE = False

import streamlit as st
import feedparser
import anthropic
from fpdf import FPDF
from fpdf.enums import XPos, YPos

from regions import REGIONS, KANNADA_DISTRICTS, STATE_REGIONAL_QUERIES
from outlets import STATE_OUTLETS, OUTLET_DOMAINS
from ranker import rank_articles
from deduplicator import deduplicate_all
from translation import process_article
from pdf_handler import fetch_article_content
from feedback_store import record_promotion, should_generate_profile
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


def _build_regional_queries(district: str, state: str) -> list[str]:
    """Return 2 regional-language RSS queries for states with major regional outlets.

    For Karnataka the district name is substituted in Kannada script when a
    mapping exists; for all other states the English district name is used.
    Returns an empty list for states without a regional query definition.
    """
    templates = STATE_REGIONAL_QUERIES.get(state, [])
    if not templates:
        return []
    if state == "Karnataka":
        district_name = KANNADA_DISTRICTS.get(district, district)
    else:
        district_name = district
    return [t.replace("{district}", district_name) for t in templates]


def _run_feeds(queries: list[str]) -> list:
    """Fetch all queries in parallel and return combined entries."""
    base = "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q="
    urls = [base + q.replace(" ", "+") for q in queries]
    print(f"\n[DEBUG] RSS query URLs ({len(urls)} queries):")
    for u in urls:
        print(f"  {u}")
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
    queries.extend(_build_regional_queries(district, state))
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
    state_queries.extend(_build_regional_queries(district, state))
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
    """Extract news outlet name from feed entry source or link.

    Priority 1: RSS <source> tag — Google News always sets the real publisher
    name here (e.g. 'NDTV', 'The Indian Express'). Feedparser exposes this as
    entry.source, a FeedParserDict.  Try both .get() and attribute access, and
    both 'title' and 'value' key names, to be robust across feedparser versions.

    Priority 2: URL host — only used when the source tag is absent or unhelpful.
    For news.google.com redirect URLs we return 'Unknown' rather than a misleading
    'Google News', so the outlet filter can never accidentally match it.
    """
    source = getattr(entry, "source", None)
    if source:
        title = None
        if hasattr(source, "get"):
            title = source.get("title") or source.get("value")
        if not title:
            title = getattr(source, "title", None) or getattr(source, "value", None)
        if title:
            title = str(title).strip()
            if title and title.lower() != "google news":
                return title

    link = getattr(entry, "link", "") or ""
    if "news.google.com" in link:
        return "Unknown"
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


def _fetch_newsdata_one_domain(domain: str, district: str, state: str, api_key: str, language: str) -> list:
    """Fetch NewsData.io articles for a single domain. Returns raw article dicts."""
    location = f"{district} {state}"
    base_url  = "https://newsdata.io/api/1/latest"
    articles  = []
    for q in (f"{location} politics", f"{location} election BJP Congress MLA minister"):
        params = {
            "apikey":    api_key,
            "q":         q,
            "country":   "in",
            "language":  language,
            "category":  "politics",
            "domainurl": domain,
        }
        url = base_url + "?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PolitiScan/1.1"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                for item in data.get("results", []):
                    articles.append({
                        "headline":       item.get("title", ""),
                        "snippet":        (item.get("description") or item.get("content") or "")[:600],
                        "source_name":    item.get("source_id", "Unknown"),
                        "published_iso":  item.get("pubDate", ""),
                        "url":            item.get("link", ""),
                        "source_channel": "newsdata",
                    })
        except Exception:
            pass
    return articles


def fetch_newsdata_articles(district: str, state: str, domains: list, api_key: str, language: str = "en") -> tuple:
    """Fetch recent articles from NewsData.io for each domain in parallel.
    Each domain gets its own API call so a missing domain doesn't silence others.
    Returns (articles, domain_counts) where domain_counts = {domain: raw_article_count}.
    """
    if not api_key or not domains:
        return [], {}

    per_domain: list = [[] for _ in domains]

    def _worker(idx: int, dom: str):
        per_domain[idx] = _fetch_newsdata_one_domain(dom, district, state, api_key, language)

    threads = [threading.Thread(target=_worker, args=(i, d), daemon=True) for i, d in enumerate(domains)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    domain_counts = {}
    for dom, arts in zip(domains, per_domain):
        domain_counts[dom] = len(arts)
        print(f"  [NewsData] {dom} -> {len(arts)} articles  (lang={language})")

    all_articles = [art for bucket in per_domain for art in bucket]

    from collections import Counter as _Counter
    _src_counts = _Counter(a.get("source_name", "?") for a in all_articles)
    print(f"  [ND COMBINED] Total NewsData articles before dedup: {len(all_articles)}")
    print(f"  [ND COMBINED] Sources: {dict(_src_counts)}")

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
            recent.append(art)   # keep if date unparseable

    seen: set = set()
    unique = []
    for art in recent:
        if art["url"] and art["url"] not in seen:
            seen.add(art["url"])
            unique.append(art)

    return unique, domain_counts


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
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(w=W, h=5, text=source_line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        except Exception:
            pass

        if rtype == "SPECULATIVE":
            raw_sigs = art.get("_signals", "")
            if raw_sigs:
                try:
                    pdf.set_font("Helvetica", "I", 8)
                    pdf.set_x(pdf.l_margin)
                    pdf.cell(w=W, h=4, text=safe(f"    Signals: {raw_sigs}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                except Exception:
                    pass

        try:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(w=W, h=5, text=summary, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        except Exception:
            pass

        try:
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(0, 0, 180)
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(w=W, h=4, text=url, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
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
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(w=W, h=6, text=headline, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        except Exception:
            pass

        try:
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(w=W, h=5, text=safe(f"Source: {outlet}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        except Exception:
            pass

        try:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(w=W, h=5, text=summary, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        except Exception:
            pass

        try:
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(0, 0, 180)
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(w=W, h=4, text=url, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
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
apply_newspaper_theme()

# ---------------------------------------------------------------------------
# Login gate
# ---------------------------------------------------------------------------
if DEV_MODE:
    st.session_state.logged_in  = True
    st.session_state.user_email = "dev@test.com"

if not st.session_state.get("logged_in"):
    # Hide sidebar entirely on login page
    st.markdown("""
<style>
/* Hide sidebar and header */
section[data-testid="stSidebar"], header[data-testid="stHeader"] { display: none !important; }

/* Dark outer background */
.stApp { background-color: #0a0a0a !important; }

/* Cream card */
.block-container {
    background: #f4efe3 !important;
    border: 1.5px solid #1a1a1a !important;
    box-shadow: 0 0 0 5px #f4efe3, 0 0 0 6px #b0a080 !important;
    border-radius: 2px !important;
    max-width: 580px !important;
    margin: 5vh auto !important;
    padding: 1.25rem 2.5rem 1.25rem !important;
}

/* All text dark */
.block-container, .block-container * { color: #1a1a1a !important; }

/* Kill Streamlit's default widget gaps */
.block-container .stTextInput,
.block-container .stButton,
.block-container .element-container,
.block-container [data-testid="element-container"],
.block-container [data-testid="stVerticalBlock"] > div {
    margin-bottom: 0.3rem !important;
    padding-bottom: 0 !important;
}
.block-container [data-testid="stVerticalBlock"] {
    gap: 0.3rem !important;
}

/* Newspaper elements */
.np-rule-thick { height:3px; background:#1a1a1a; margin-bottom:2px; }
.np-rule-thin  { height:1px; background:#1a1a1a; margin-bottom:0.15rem; }
.np-masthead   { font-family:"Georgia","Times New Roman",serif; font-size:42px; font-weight:700;
                 color:#1a1a1a; text-align:center; line-height:1; margin-bottom:0.2rem; }
.np-meta       { display:flex; align-items:center; gap:6px; margin-bottom:0.15rem; }
.np-meta-rule  { flex:1; height:0.5px; background:#b0a080; }
.np-meta-text  { font-family:"Georgia","Times New Roman",serif; font-size:9px;
                 letter-spacing:0.14em; text-transform:uppercase; color:#7a6a4a !important; white-space:nowrap; }
.np-divider    { border:none; border-top:2.5px double #1a1a1a; margin:0.1rem 0 0.25rem 0; }
.np-tagline    { font-family:"Georgia","Times New Roman",serif; font-size:15px;
                 font-weight:700; color:#1a1a1a !important; text-align:center;
                 margin:0.2rem 0 0.15rem 0; line-height:1.4; }
.np-subhead    { font-family:"Georgia","Times New Roman",serif; font-size:11px;
                 font-style:italic; color:#7a6a4a !important; text-align:center; margin:0 0 0.5rem 0; }
.np-label,
.block-container .stTextInput label {
    font-family:"Georgia","Times New Roman",serif !important; font-size:9px !important;
    letter-spacing:0.14em !important; text-transform:uppercase !important;
    color:#7a6a4a !important; display:block !important; margin-bottom:2px !important; margin-top:0.4rem !important;
}
.np-section-divider { border:none; border-top:1px solid #c8b898; margin:0.4rem 0 0.3rem 0; }
.np-otp-note   { font-family:"Georgia","Times New Roman",serif; font-size:11.5px;
                 font-style:italic; color:#7a6a4a !important; text-align:center; margin:0.3rem 0 0.2rem 0; }
.np-footer     { font-family:"Georgia","Times New Roman",serif; font-size:8px; letter-spacing:0.1em;
                 text-transform:uppercase; color:#b0a080 !important; text-align:center;
                 margin-top:0.6rem; padding-top:0.4rem; border-top:0.5px solid #c8b898; }

/* Inputs */
.block-container .stTextInput input {
    color: #1A1A1A !important;
    font-family: "Georgia","Times New Roman",serif !important;
    font-size: 14px !important;
}
.block-container .stTextInput input::placeholder { color: #9a8a6a !important; font-style: italic; }

/* ALL buttons — solid black by default */
.block-container button {
    background: #1a1a1a !important; color: #f4efe3 !important;
    border: 1.5px solid #1a1a1a !important; border-radius: 0 !important;
    font-family: "Georgia","Times New Roman",serif !important;
    font-size: 10.5px !important; letter-spacing: 0.18em !important;
    text-transform: uppercase !important; width: 100% !important;
}
.block-container button p,
.block-container button span { color: #f4efe3 !important; }

/* Resend — override to be borderless italic text */
.np-resend-btn button {
    background: transparent !important; border: none !important;
    box-shadow: none !important; color: #7a6a4a !important;
    font-style: italic !important; text-transform: none !important;
    letter-spacing: 0.03em !important; font-size: 11px !important;
    width: auto !important; display: block !important; margin: 0 auto !important;
}
.np-resend-btn button p,
.np-resend-btn button span { color: #7a6a4a !important; font-style: italic !important; }
</style>
""", unsafe_allow_html=True)

    today_str = datetime.now().strftime("%A, %-d %B %Y")

    st.markdown(f'''
        <div class="np-rule-thick"></div>
        <div class="np-rule-thin"></div>
        <div class="np-masthead">PolitiScan</div>
        <div class="np-meta">
            <div class="np-meta-rule"></div>
            <div class="np-meta-text">Bengaluru &middot; {today_str}</div>
            <div class="np-meta-rule"></div>
        </div>
        <hr class="np-divider">
        <div class="np-tagline">Your daily briefing on what matters in Indian politics — curated, ranked, and ready.</div>
        <div class="np-subhead">Enter your email to receive today's intelligence dispatch</div>
    ''', unsafe_allow_html=True)

    # Email — always visible
    otp_sent = st.session_state.get("otp_sent", False)

    if not otp_sent:
        email = st.text_input("EMAIL ADDRESS", key="login_email_input",
                              label_visibility="visible", placeholder="you@example.com")
        if st.button("Send Verification Code", key="send_otp_btn"):
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
        st.text_input("EMAIL ADDRESS", value=st.session_state.login_email,
                      key="login_email_display", label_visibility="visible", disabled=True)
        st.button("Send Verification Code", key="send_otp_btn_disabled", disabled=True)

        st.markdown(
            f'<div class="np-otp-note">Code sent to {st.session_state.login_email} — enter the 6 digits below. Expires in 10 minutes.</div>'
            '<hr class="np-section-divider">',
            unsafe_allow_html=True)
        code = st.text_input("VERIFICATION CODE", max_chars=6, key="otp_input",
                             label_visibility="visible", placeholder="······")

        if st.button("Verify & Enter", key="verify_btn"):
            if verify_otp(code, st.session_state.otp, st.session_state.otp_timestamp):
                st.session_state.logged_in  = True
                st.session_state.user_email = st.session_state.login_email
                for k in ("otp", "otp_timestamp", "otp_sent", "login_email"):
                    st.session_state.pop(k, None)
                st.rerun()
            else:
                st.error("Invalid or expired code. Please try again.")

        st.markdown('<div class="np-resend-btn">', unsafe_allow_html=True)
        if st.button("↺  Resend code", key="resend_btn"):
            otp = generate_otp()
            st.session_state.otp           = otp
            st.session_state.otp_timestamp = datetime.now()
            sent, send_err = send_otp_email(st.session_state.login_email, otp)
            if sent:
                st.success("New code sent.")
            else:
                st.error(f"Failed to resend: {send_err}")
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="np-footer">For authorised personnel only &middot; PolitiScan Intelligence</div>',
                unsafe_allow_html=True)
    st.stop()

# ---------------------------------------------------------------------------
# App title (shown only when logged in)
# ---------------------------------------------------------------------------

st.markdown("""
<style>
section[data-testid="stSidebarNav"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

st.title("Political Intelligence Dashboard")

# Load/refresh client profile once per session
if "profile_loaded" not in st.session_state:
    st.session_state.client_profile = check_and_refresh_profile(st.session_state.user_email)
    st.session_state.profile_loaded = True


_COL_ORDER = ["Rank", "Score", "Report Type", "Headline", "Summary", "Sources", "Language", "Link"]

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
_TH = "padding:6px 10px;text-align:left;border-bottom:1px solid #444;white-space:nowrap;color:#FFFFFF !important;"
_TD = "padding:6px 10px;vertical-align:top;"


def _render_article_table(rows: list, table_class: str = "") -> None:
    """Render a list of article row dicts as a styled HTML table."""
    cls = f" class='{table_class}'" if table_class else ""
    header_html = "".join(f"<th style='{_TH}'>{c}</th>" for c in _COL_ORDER)
    body_html = ""
    for row in rows:
        cells = ""
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
                if col == "Summary" and val.startswith("What happened: "):
                    val = val[len("What happened: "):]
                content = str(val).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            cells += f"<td style='{_TD}'>{content}</td>"
        body_html += f"<tr>{cells}</tr>"
    st.markdown(
        "<div style='overflow-x:auto;'>"
        f"<table{cls} style='width:100%;border-collapse:collapse;font-size:13px;'>"
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

        kannada_nd_total = bd.get("kannada_nd_total", 0)
        header_parts = []
        if kannada_nd_total:
            header_parts.append(f"**{kannada_nd_total}** from NewsData.io (Kannada outlets)")
        if nd_total:
            header_parts.append(f"**{nd_total}** from NewsData.io (primary)")
        header_parts.append(f"**{rss_total}** from Google RSS (secondary)")

        top_outlets = sorted(outlet_counts.items(), key=lambda x: -x[1])[:8]
        outlet_str  = "   ".join(f"**{k}:** {v}" for k, v in top_outlets)

        breakdown_line = "   ".join(header_parts)
        if outlet_str:
            breakdown_line += "   \u2014   " + outlet_str
        st.caption(breakdown_line)

    all_rows        = st.session_state.results_rows
    total_political = len(all_rows)
    selected_type   = st.session_state.get("selected_report_types", "All Report Types")
    keyword         = st.session_state.get("keyword_filter", "").strip().lower()

    def _keyword_match(r):
        if not keyword:
            return True
        return (
            keyword in (r.get("Headline", "") or "").lower()
            or keyword in (r.get("Summary", "") or "").lower()
        )

    filtered = all_rows
    if selected_type and selected_type != "All Report Types":
        filtered = [r for r in filtered if r.get("_report_type", "CONFIRMED") == selected_type]
    if keyword:
        filtered = [r for r in filtered if _keyword_match(r)]

    filtered = sorted(filtered, key=lambda r: r.get("_client_adjusted_score", r.get("Score", 0)), reverse=True)
    for i, r in enumerate(filtered, start=1):
        r["Rank"] = i

    # -------------------------------------------------------------------
    # SECTION 1 — AI Shortlist
    # -------------------------------------------------------------------
    shortlist = st.session_state.get("shortlist_articles", [])
    if selected_type and selected_type != "All Report Types":
        shortlist = [r for r in shortlist if r.get("_report_type", "CONFIRMED") == selected_type]
    if keyword:
        shortlist = [r for r in shortlist if _keyword_match(r)]
    shortlist_urls = {r.get("Link") for r in shortlist}

    # ── RENDER-TIME DIAGNOSTIC ──────────────────────────────────────────────
    _sl_raw   = st.session_state.get("shortlist_articles", [])
    _all_rows = st.session_state.get("results_rows", [])
    print(f"\n[RENDER] _show_results() shortlist diagnostic:")
    print(f"  results_rows in session state:          {len(_all_rows)} articles")
    print(f"  shortlist_articles in session state:    {len(_sl_raw)} articles")
    print(f"  selected_type active:                   {selected_type!r}")
    print(f"  keyword active:                         {keyword!r}")
    _after_type = [r for r in _sl_raw if selected_type in ("All Report Types", "", None) or r.get("_report_type", "CONFIRMED") == selected_type]
    _after_kw   = [r for r in _after_type if not keyword or keyword in (r.get("Headline","") or "").lower() or keyword in (r.get("Summary","") or "").lower()]
    print(f"  shortlist after type filter:            {len(_after_type)} articles")
    print(f"  shortlist after keyword filter:         {len(_after_kw)} articles")
    print(f"  final 'shortlist' variable at render:   {len(shortlist)} articles")
    if _sl_raw and not shortlist:
        print(f"  !! {len(_sl_raw)} articles in session state were filtered to 0 by display filters")
        for r in _sl_raw[:5]:
            print(f"     type={r.get('_report_type','?')!r}  score={r.get('_client_adjusted_score',0):.2f}  {r.get('Headline','')[:60]}")
    # ── END DIAGNOSTIC ───────────────────────────────────────────────────────

    _sl_total = len(st.session_state.get("shortlist_articles", []))
    if not shortlist and _sl_total:
        st.subheader(f"AI Shortlist (0 of {_sl_total} articles shown — hidden by 'Show Report Types' filter)")
        st.caption("Adjust the **Show Report Types** filter in the sidebar to **All Report Types** to see results.")
    else:
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
            _editor_cols = ["Rank", "Score", "Report Type", "Headline", "Summary", "Sources"]

            def _strip_prefix(v):
                if isinstance(v, str) and v.startswith("What happened: "):
                    return v[len("What happened: "):]
                return v

            def _safe_str(v):
                """Coerce any value to a plain str, flattening lists/sets."""
                if v is None:
                    return ""
                if isinstance(v, (list, tuple)):
                    return ", ".join(str(i) for i in v)
                if isinstance(v, set):
                    return ", ".join(str(i) for i in sorted(v))
                return str(v)

            editor_rows = [
                {
                    "Add?":        False,
                    "Rank":        int(row.get("Rank") or 0),
                    "Score":       float(row.get("Score") or 0.0),
                    "Report Type": _safe_str(row.get("Report Type")),
                    "Headline":    _safe_str(row.get("Headline")),
                    "Summary":     _safe_str(_strip_prefix(row.get("Summary") or "")),
                    "Sources":     _safe_str(row.get("Sources")),
                }
                for row in non_shortlist
            ]
            edit_df = pd.DataFrame(editor_rows)[["Add?"] + _editor_cols]

            try:
                edited = st.data_editor(
                    edit_df,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Add?":        st.column_config.CheckboxColumn("Add?", default=False),
                        "Score":       st.column_config.NumberColumn("Score", format="%.1f"),
                        "Headline":    st.column_config.TextColumn("Headline", width="large"),
                        "Summary":     st.column_config.TextColumn("Summary",  width="large"),
                    },
                    key="all_articles_editor",
                )
            except Exception:
                # Fallback: render each article as an expander card
                edited = edit_df.copy()
                for i, row in enumerate(non_shortlist):
                    label = _safe_str(row.get("Headline")) or f"Article {i + 1}"
                    with st.expander(label):
                        st.caption(f"Score: {float(row.get('Score') or 0):.1f}  |  {_safe_str(row.get('Report Type'))}  |  {_safe_str(row.get('Sources'))}")
                        st.write(_safe_str(_strip_prefix(row.get("Summary") or "")))
                        checked = st.checkbox("Add to Shortlist", key=f"fallback_add_{i}")
                        edited.at[i, "Add?"] = checked

            if st.button("Add to Shortlist", key="add_shortlist_btn"):
                selected_indices = edited.loc[edited["Add?"] == True].index.tolist()
                count = 0
                for idx in selected_indices:
                    if idx < len(non_shortlist):
                        row = non_shortlist[idx]
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
    st.markdown(
        f"""<div style="border:1px solid #1A1A1A;padding:12px;margin-bottom:4px;">
<p style="font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:#6B6B63;margin:0 0 6px 0;">Signed in as</p>
<p style="font-size:16px;font-weight:700;color:#1A1A1A;margin:0 0 12px 0;">{st.session_state.user_email}</p>
</div>""",
        unsafe_allow_html=True,
    )
    if st.button("LOGOUT", key="sidebar_logout", use_container_width=True):
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

    # Story Sources — only shown when results are available
    if "results_rows" in st.session_state and st.session_state.results_rows:
        st.divider()
        st.subheader("Filter Results")
        st.selectbox(
            "Show Report Types",
            options=["All Report Types", "CONFIRMED", "SPECULATIVE", "ANALYTICAL"],
            key="selected_report_types",
        )

        keyword = st.text_input(
            "Filter by Keyword",
            placeholder="e.g. DK Shivakumar",
        )
        st.session_state.keyword_filter = keyword

        st.divider()
        with st.expander("Story Sources"):
            shortlist = st.session_state.get("shortlist_articles", [])
            shortlist_links = {a.get("Link", "") for a in shortlist if a.get("Link")}
            shortlist_headlines = {a.get("Headline", "") for a in shortlist if a.get("Headline")}
            multi_source_rows = [
                r for r in st.session_state.results_rows
                if r.get("_source_count", 1) >= 2
                and (
                    r.get("Link", "") in shortlist_links
                    or r.get("Headline", "") in shortlist_headlines
                )
            ]
            if not multi_source_rows:
                st.caption("No shortlisted stories with multiple sources found.")
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
                "source_breakdown", "shortlist_articles", "show_all_articles"):
        st.session_state.pop(key, None)

    api_key      = os.getenv("ANTHROPIC_API_KEY", "")
    region_label = f"{district}, {state}"
    st.session_state.region_label = region_label

    rss_result = [None, None]
    nd_result  = [[], 0, {}]   # [articles, kannada_nd_count, domain_counts]

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

            # Kannada outlets are not in Google News RSS; route them through
            # NewsData.io with language="kn,en" using confirmed working domains.
            _KANNADA_ND_DOMAINS = {
                "Vijaya Karnataka": "vijaykarnataka.com",
                "Prajavani":        "prajavani.net",
                "Udayavani":        "udayavani.com",
                "Kannada Prabha":   "kannadaprabha.com",
                "TV9 Kannada":      "tv9kannada.com",
            }

            if active_outlets:
                _kannada_selected = [o for o in active_outlets if o in _KANNADA_ND_DOMAINS]
                _other_selected   = [o for o in active_outlets if o not in _KANNADA_ND_DOMAINS]

                _all_nd = []

                # Kannada outlets → NewsData.io with kn,en language
                if _kannada_selected:
                    _kn_domains = [_KANNADA_ND_DOMAINS[o] for o in _kannada_selected]
                    _kn_arts, _kn_counts = fetch_newsdata_articles(district, state, _kn_domains, _key, language="kn,en")
                    nd_result[1] = len(_kn_arts)   # store Kannada ND count separately
                    nd_result[2].update(_kn_counts) # store per-domain counts for UI debug
                    _all_nd.extend(_kn_arts)

                # Non-Kannada outlets → NewsData.io with en language (existing behaviour)
                if _other_selected:
                    _en_domains = [d for d in (OUTLET_DOMAINS.get(o) for o in _other_selected) if d]
                    if _en_domains:
                        _en_arts, _ = fetch_newsdata_articles(district, state, _en_domains, _key)
                        _all_nd.extend(_en_arts)

                nd_result[0] = _all_nd
            else:
                nd_result[0] = fetch_newsdata_primary(district, state, _key)
        except Exception as _e:
            print(f"[NewsData Thread Error] {_e}", file=sys.stderr)
            nd_result[0] = []

    with st.spinner("Fetching news from NewsData.io and Google News RSS simultaneously..."):
        t_rss = threading.Thread(target=_rss_worker, daemon=True)
        t_nd  = threading.Thread(target=_nd_worker,  daemon=True)
        t_rss.start(); t_nd.start()
        t_rss.join();  t_nd.join()

    raw_entries      = rss_result[0] or []
    scope            = rss_result[1] or "district"
    newsdata_dicts   = nd_result[0] or []
    kannada_nd_count = nd_result[1] or 0
    nd_domain_counts = nd_result[2] or {}    # {domain: raw_count} from Kannada fetch

    recent, _  = filter_recent(raw_entries, hours=36)
    unique_rss = deduplicate(recent, threshold=0.70)
    rss_dicts  = entries_to_dicts(unique_rss, channel="rss")
    rss_total_raw = len(rss_dicts)

    # Diagnostic: print any source names that look like Kannada outlets,
    # so we can see exactly how Google News labels them regardless of outlet filter.
    _kannada_signals = ("vijay", "prajav", "udaya", "kannada")
    _kannada_hits = [
        a.get("source_name", "") for a in rss_dicts
        if any(sig in (a.get("source_name") or "").lower() for sig in _kannada_signals)
    ]
    if _kannada_hits:
        print(f"\n[KANNADA SOURCE DEBUG] source_names matching Kannada outlet signals:")
        for _s in _kannada_hits:
            print(f"  {_s!r}")
    else:
        print(f"\n[KANNADA SOURCE DEBUG] no source_names matched Kannada signals in {len(rss_dicts)} RSS articles")

    _rss_dicts_unfiltered = list(rss_dicts)   # snapshot before outlet filter

    # Filter RSS results by selected outlets (source name or domain match)
    if active_outlets:
        _outlet_names_lower = [o.lower() for o in active_outlets]
        _outlet_domains_map = {o: (OUTLET_DOMAINS.get(o) or "").lower() for o in active_outlets}

        # Kannada outlets need looser matching because Google News may label them
        # inconsistently. Map each Kannada outlet name to known URL substrings.
        _KANNADA_URL_FRAGMENTS = {
            "vijaya karnataka": ["vijaykarnataka.com"],
            "prajavani":        ["prajavani.net"],
            "udayavani":        ["udayavani.com"],
            "kannada prabha":   ["kannadaprabha.com"],
        }
        _active_kannada = {k: v for k, v in _KANNADA_URL_FRAGMENTS.items()
                           if k in _outlet_names_lower}

        def _rss_matches_outlet(art):
            src = (art.get("source_name") or "").lower().strip()
            url_host = ""
            try:
                url_host = urllib.parse.urlparse(art.get("url") or "").netloc.lower()
            except Exception:
                pass

            # Name match: exact, or source has a leading "The " ("Indian Express" → "The Indian Express").
            # Avoids false positives like "NDTV" matching "NDTV Food".
            for name in _outlet_names_lower:
                if src == name or src == "the " + name:
                    return True

            # Domain match: exact hostname only (www. prefix allowed).
            # Avoids subdomains like food.ndtv.com matching ndtv.com.
            for domain in _outlet_domains_map.values():
                if domain and (url_host == domain or url_host == "www." + domain):
                    return True

            # Kannada-outlet fallbacks (URL substring + headline suffix).
            # Only runs when a Kannada outlet is in the selected set.
            if _active_kannada:
                headline = (art.get("headline") or "").lower()
                for outlet_key, url_fragments in _active_kannada.items():
                    # Fallback 1: URL host contains a known Kannada domain fragment
                    if any(frag in url_host for frag in url_fragments):
                        return True
                    # Fallback 2: headline/title contains outlet name as substring
                    # (Google RSS often appends "- Vijaya Karnataka" to titles)
                    if outlet_key in headline:
                        return True

            return False

        print(f"\n[DEBUG] Outlet filter — selected: {list(active_outlets)}")
        print(f"  {'Keep':<6} {'Source name':<35} {'URL host':<35} {'Match reason'}")
        _kept, _dropped = [], []
        for _a in rss_dicts:
            _src  = (_a.get("source_name") or "").lower()
            try:
                _host = urllib.parse.urlparse(_a.get("url") or "").netloc.lower()
            except Exception:
                _host = ""
            _reason = ""
            _pass = False
            for _name in _outlet_names_lower:
                if _name in _src or _src in _name:
                    _reason = f"name '{_name}' ↔ src '{_src}'"
                    _pass = True
                    break
            if not _pass:
                for _oname, _dom in _outlet_domains_map.items():
                    if _dom and _dom in _host:
                        _reason = f"domain '{_dom}' in host '{_host}'"
                        _pass = True
                        break
            if not _reason:
                _reason = f"no match (src='{_src}', host='{_host}')"
            tag = "KEEP" if _pass else "DROP"
            print(f"  {tag:<6} {(_a.get('source_name') or '')[:34]:<35} {_host[:34]:<35} {_reason}")
            (_kept if _pass else _dropped).append(_a)
        print(f"  → {len(_kept)} kept, {len(_dropped)} dropped")
        rss_dicts = _kept
        print(f"[PIPELINE] After outlet filter: {len(rss_dicts)} RSS articles remain")

    rss_total = len(rss_dicts)

    unique_nd     = deduplicate_dicts(newsdata_dicts, threshold=0.70)
    nd_count      = len(unique_nd)
    total_fetched = rss_total_raw + nd_count   # pre-filter total for display
    article_dicts = rss_dicts + unique_nd

    print(f"\n[PIPELINE] Before dedup: {rss_total} RSS articles, {nd_count} NewsData articles")
    print(f"[PIPELINE] newsdata_dicts length (raw from _nd_worker): {len(newsdata_dicts)}")
    print(f"[PIPELINE] Combined article_dicts total: {len(article_dicts)}")

    # --- TEMPORARY DEBUG UI (remove after Kannada outlet investigation) ---
    _KANNADA_ND_OUTLET_NAMES = {"Vijaya Karnataka", "Prajavani", "Udayavani", "Kannada Prabha", "TV9 Kannada"}
    if active_outlets and any(o in _KANNADA_ND_OUTLET_NAMES for o in active_outlets):
        st.warning(
            "**DEBUG — NewsData fetch results:**\n\n"
            f"- vijaykarnataka.com: **{nd_domain_counts.get('vijaykarnataka.com', 0)}** articles\n"
            f"- prajavani.net: **{nd_domain_counts.get('prajavani.net', 0)}** articles\n"
            f"- udayavani.com: **{nd_domain_counts.get('udayavani.com', 0)}** articles\n"
            f"- tv9kannada.com: **{nd_domain_counts.get('tv9kannada.com', 0)}** articles\n"
            f"- kannadaprabha.com: **{nd_domain_counts.get('kannadaprabha.com', 0)}** articles\n"
            f"- Total NewsData (raw): **{sum(nd_domain_counts.values())}**  |  "
            f"after dedup: **{nd_count}**\n"
            f"- Total RSS (after outlet filter): **{rss_total}**\n"
            f"- Combined (RSS + NewsData): **{len(article_dicts)}**"
        )
    # --- END TEMPORARY DEBUG UI ---

    if not article_dicts and active_outlets:
        st.warning(
            "No articles found matching selected outlets. "
            "The selected outlets may not have published on this topic in the last 36 hours. "
            "Try selecting All Outlets."
        )
    elif not article_dicts:
        st.warning("No recent articles found for the selected region. Try a different district or check back later.")
    else:
        outlet_counts = Counter(
            a["source_name"] for a in rss_dicts
            if a.get("source_name") and a["source_name"] not in ("Unknown", "Google News", "")
        )

        st.session_state.source_breakdown = {
            "rss_total":        rss_total,
            "newsdata_total":   nd_count,
            "kannada_nd_total": kannada_nd_count,
            "outlet_counts":    dict(outlet_counts),
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
                "_client_adjusted_score":  client_adj,
                "_affects_client_region":  art.get("affects_client_region", False),
                "_profile_boosted":        art.get("profile_boosted", False),
            })

        # Debug: raw ranked output — region_tier + both score fields before row-building strips them
        print(f"\n[RANKED RAW] {state}/{district} — {len(ranked)} political articles from rank_articles():")
        print(f"  {'#':<3} {'tier':<10} {'acr':<5} {'final_sc':<9} {'cli_adj':<8} {'headline'[:40]}")
        for _i, _a in enumerate(ranked, 1):
            print(f"  {_i:<3} {_a.get('region_tier','???'):<10} "
                  f"{'T' if _a.get('affects_client_region') else 'F':<5} "
                  f"{_a.get('final_score',0):<9.2f} "
                  f"{_a.get('client_adjusted_score',0):<8.2f} "
                  f"{_a.get('headline','')[:40]}")

        # Debug: show every article's region flag, score, headline, and Location from AI summary
        SHORTLIST_THRESHOLD = 7.0   # articles >= this score qualify directly; others fill via fallback
        print(f"\n[DEBUG] Full article list after ranking/filtering — {state}/{district}  (threshold={SHORTLIST_THRESHOLD}):")
        print(f"  {'Rk':<3} {'Score':<6} {'>=7?':<5} {'Region':<14} {'Headline':<55}  Location (from summary)")
        for r in rows:
            summ = r.get("Summary", "")
            if "Location:" in summ:
                loc_text = summ.split("Location:")[1].split("Political significance:")[0].strip()[:60]
            else:
                loc_text = "—"
            region_label  = "IN-REGION " if r.get("_affects_client_region") else "OUT-OF-REGION"
            passes_thresh = "YES" if r.get("_client_adjusted_score", 0) >= SHORTLIST_THRESHOLD else "no"
            print(f"  {r['Rank']:<3} {r['_client_adjusted_score']:<6.2f} {passes_thresh:<5} {region_label:<14} {r['Headline'][:55]:<55}  {loc_text}")

        # Shortlist: articles scoring >= 7.0, OR top 10 if fewer than 5 clear the threshold.
        # Everything else stays in "not in shortlist" for the user to review and promote.
        _above = [r for r in rows if r.get("_client_adjusted_score", 0) >= SHORTLIST_THRESHOLD]
        if len(_above) < 5:
            _shortlist = rows[:10]
        else:
            _shortlist = _above
        st.session_state.shortlist_articles = _shortlist

        print(f"\n[DEBUG] Shortlist build:")
        print(f"  Total rows:             {len(rows)}")
        print(f"  Articles >= {SHORTLIST_THRESHOLD}:       {len(_above)}")
        print(f"  Final shortlist size:   {len(_shortlist)}")
        for r in _shortlist:
            marker = "* " if r.get("_client_adjusted_score", 0) >= SHORTLIST_THRESHOLD else "  "
            print(f"  {marker}score={r.get('_client_adjusted_score',0):.2f}  {r.get('Headline','')[:70]}")

        # Debug: print counts at each pipeline stage
        dupes_merged = pre_dedup_count - post_dedup_count
        print("\n[DEBUG] Pipeline counts:")
        print(f"  Total fetched (pre-outlet-filter): {total_fetched}  (rss_raw={rss_total_raw}, nd={nd_count})")
        print(f"  After outlet filter (pre-dedup):   {pre_dedup_count}  (rss={rss_total}, nd={nd_count})")
        print(f"  After deduplication:               {post_dedup_count}  ({dupes_merged} duplicates merged)")
        print(f"  After ranking (political filter):  {len(ranked)}")
        print(f"  Shortlist (>= {SHORTLIST_THRESHOLD} or top-10 fallback): {len(st.session_state.shortlist_articles)}")

        if active_outlets:
            filter_note = f"  {pre_dedup_count} articles after outlet filter (from {total_fetched} total fetched)."
        else:
            filter_note = f"  {total_fetched} total fetched — {nd_count} from NewsData.io, {rss_total} from Google RSS."
        caption = (
            f"**{len(ranked)} political articles ranked**{scope_note}.  "
            f"{dupes_merged} duplicates merged from {pre_dedup_count} candidates.{filter_note}"
        )

        st.session_state.results_rows    = rows
        st.session_state.results_caption = caption
        _show_results()

elif "results_rows" in st.session_state:
    _show_results()
