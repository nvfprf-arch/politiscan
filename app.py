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
from outlets import STATE_OUTLETS, OUTLET_DOMAINS, NATIVE_RSS_FEEDS
from ranker import rank_articles

# ---------------------------------------------------------------------------
# NewsData.io debug logger — writes timestamped entries to newsdata_debug.log
# ---------------------------------------------------------------------------
import logging
import traceback as _traceback

_nd_logger = logging.getLogger("newsdata_debug")
_nd_logger.setLevel(logging.DEBUG)
if not _nd_logger.handlers:
    _nd_fh = logging.FileHandler("newsdata_debug.log", encoding="utf-8")
    _nd_fh.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _nd_logger.addHandler(_nd_fh)
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
def fetch_all_feeds(district: str, state: str, selected_outlets: tuple = ()) -> tuple[list, str, dict]:
    """Fetch news with district+state queries plus per-outlet site-restricted queries.

    For each selected outlet, fires:
      • One English-language site-restricted query (site:domain location)
      • One Kannada-language site-restricted query (hl=kn-IN) for Kannada outlets

    General (non-site-restricted) political queries are also run and all results
    are combined, so articles that surface via the general query are preserved.

    Returns (combined_entries, scope_used, outlet_site_counts) where:
      scope_used        — 'district' or 'state'
      outlet_site_counts — {outlet_name: {"site_en": N, "site_kn": M}}
    Cached for 30 minutes per district/state/outlets combination.
    """
    location = f"{district} {state}"

    # Split selected outlets into native-feed vs Google site-restricted groups.
    # Outlets in NATIVE_RSS_FEEDS are fetched directly; all others use site: queries.
    _selected = list(selected_outlets or [])
    native_pairs = [
        (o, NATIVE_RSS_FEEDS[o])
        for o in _selected
        if o in NATIVE_RSS_FEEDS
    ]
    site_pairs = [
        (o, OUTLET_DOMAINS[o])
        for o in _selected
        if o not in NATIVE_RSS_FEEDS and OUTLET_DOMAINS.get(o)
    ]

    # ── Fetch native RSS feeds in parallel ───────────────────────────────────
    native_entries: list = []
    native_counts: dict[str, dict] = {}
    if native_pairs:
        _native_raw: list = [None] * len(native_pairs)
        _native_threads = [
            threading.Thread(target=fetch_feed, args=(url, _native_raw, i))
            for i, (_, url) in enumerate(native_pairs)
        ]
        for _t in _native_threads:
            _t.start()
        for _t in _native_threads:
            _t.join()
        for (outlet_name, _url), entries in zip(native_pairs, _native_raw):
            entries = entries or []
            # Tag each entry so get_outlet() returns the canonical outlet name
            for _e in entries:
                _e["_forced_source"] = outlet_name
            native_counts[outlet_name] = {"native": len(entries)}
            native_entries.extend(entries)

    # ── General queries (unchanged) ───────────────────────────────────────────
    general_queries = _build_queries(location)
    general_queries.extend(_build_regional_queries(district, state))
    general_entries = _run_feeds(general_queries)

    # ── Site-restricted queries for non-native outlets ────────────────────────
    site_entries, outlet_site_counts = _fetch_outlet_site_entries(site_pairs, location)

    all_outlet_counts = {**native_counts, **outlet_site_counts}
    combined = general_entries + native_entries + site_entries
    recent, _ = filter_recent(combined, hours=36)
    if recent:
        return combined, "district", all_outlet_counts

    # ── Fallback: state-only queries ──────────────────────────────────────────
    state_queries = _build_queries(state)
    state_queries.extend(_build_regional_queries(district, state))
    state_general_entries = _run_feeds(state_queries)
    state_site_entries, state_site_counts = _fetch_outlet_site_entries(site_pairs, state)

    state_all_outlet_counts = {**native_counts, **state_site_counts}
    combined_state = state_general_entries + native_entries + state_site_entries
    return combined_state, "state", state_all_outlet_counts


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


def normalize_source(s: str) -> str:
    """Normalize a source name or URL to a comparable lowercase form.

    Strips HTTP protocol, www. prefix, and ' - Google News' suffixes so that
    strings like 'Vijaya Karnataka - vijaykarnataka.com' or
    'https://www.prajavani.net' can be compared against plain display names
    and bare domains.
    """
    if not s:
        return ""
    s = s.strip().lower()
    # Remove Google News attribution suffixes
    for suffix in (" - google news", "- google news", " | google news"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    # If it looks like a full URL, extract just the host
    if s.startswith(("http://", "https://")):
        try:
            host = urllib.parse.urlparse(s).netloc
            if host:
                s = host
        except Exception:
            pass
    # Strip www. prefix
    if s.startswith("www."):
        s = s[4:]
    return s


def get_outlet(entry) -> str:
    """Extract news outlet name from feed entry source or link.

    Priority 0: _forced_source — set on native RSS feed entries at fetch time
    to guarantee the canonical outlet name regardless of what the feed's own
    metadata says.

    Priority 1: RSS <source> tag — Google News always sets the real publisher
    name here (e.g. 'NDTV', 'The Indian Express'). Feedparser exposes this as
    entry.source, a FeedParserDict.  Try both .get() and attribute access, and
    both 'title' and 'value' key names, to be robust across feedparser versions.

    Priority 2: URL host — only used when the source tag is absent or unhelpful.
    For news.google.com redirect URLs we return 'Unknown' rather than a misleading
    'Google News', so the outlet filter can never accidentally match it.
    """
    # Native feed override — set explicitly at fetch time
    if hasattr(entry, "get"):
        forced = entry.get("_forced_source")
        if forced:
            return str(forced)

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




_KANNADA_OUTLET_NAMES = {
    "Vijaya Karnataka", "Prajavani", "Udayavani", "Kannada Prabha", "TV9 Kannada",
}

# Domains that warrant a parallel Kannada-language (hl=kn-IN) RSS query.
_KANNADA_OUTLET_DOMAINS: set[str] = {
    OUTLET_DOMAINS[n] for n in _KANNADA_OUTLET_NAMES if n in OUTLET_DOMAINS
}


def _build_outlet_site_url_en(location: str, domain: str) -> str:
    """Single English-language site-restricted Google News RSS URL.
    Uses only site:domain + location (no extra keyword clutter) to maximise coverage.
    """
    q = "site:" + domain + "+" + location.replace(" ", "+")
    return "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN%3Aen&q=" + q


def _build_outlet_site_url_kn(location: str, domain: str) -> str:
    """Kannada-language site-restricted Google News RSS URL.
    Surfaces Kannada-script articles that the English-language endpoint may miss.
    """
    q = "site:" + domain + "+" + location.replace(" ", "+")
    return "https://news.google.com/rss/search?hl=kn-IN&gl=IN&ceid=IN%3Akn&q=" + q


def _fetch_outlet_site_entries(
    outlet_pairs: list[tuple[str, str]],
    location: str,
) -> tuple[list, dict]:
    """Fetch site-restricted RSS entries for each (outlet_name, domain) pair in parallel.

    For domains in _KANNADA_OUTLET_DOMAINS a second Kannada-language query is also fired.
    Returns (all_entries, {outlet_name: {"site_en": N, "site_kn": M}}).
    """
    if not outlet_pairs:
        return [], {}

    # Build flat list of (outlet_name, url) so we can parallelise everything at once.
    tagged_urls: list[tuple[str, str, str]] = []  # (outlet_name, lang_tag, url)
    for name, domain in outlet_pairs:
        tagged_urls.append((name, "site_en", _build_outlet_site_url_en(location, domain)))
        if domain in _KANNADA_OUTLET_DOMAINS:
            tagged_urls.append((name, "site_kn", _build_outlet_site_url_kn(location, domain)))

    urls = [u for _, _, u in tagged_urls]
    raw_results: list = [None] * len(urls)
    threads = [
        threading.Thread(target=fetch_feed, args=(url, raw_results, i))
        for i, url in enumerate(urls)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    all_entries: list = []
    per_outlet: dict[str, dict] = {}
    for (name, lang_tag, _url), entries in zip(tagged_urls, raw_results):
        entries = entries or []
        counts = per_outlet.setdefault(name, {"site_en": 0, "site_kn": 0})
        counts[lang_tag] += len(entries)
        all_entries.extend(entries)

    return all_entries, per_outlet


@st.cache_data(ttl=1800)
def fetch_newsdata_kannada(district: str, state: str, api_key: str) -> list:
    """Fetch Kannada-language news from NewsData.io with a single call (no domainurl).
    Returns a list of ranker-compatible dicts with source_channel='newsdata'.
    Cached for 30 minutes per district/state combination.
    """
    if not api_key:
        return []

    params_dict = {
        "apikey":   api_key,
        "q":        f"{district} {state} politics",
        "country":  "in",
        "language": "kn,en",
        "page":     "1",
    }
    params = urllib.parse.urlencode(params_dict)
    url = f"https://newsdata.io/api/1/news?{params}"
    _nd_logger.debug(
        "[KANNADA] REQUEST  url=%s  params(no key)=%s",
        url.split("?")[0],
        {k: v for k, v in params_dict.items() if k != "apikey"},
    )
    _t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PolitiScan/1.3"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            _status = resp.status
            _raw    = resp.read()
        _elapsed = time.time() - _t0
        _nd_logger.debug("[KANNADA] RESPONSE http_status=%s  elapsed=%.2fs  body_bytes=%d", _status, _elapsed, len(_raw))
        _nd_logger.debug("[KANNADA] BODY %s", _raw.decode(errors="replace")[:2000])
        data = json.loads(_raw.decode())
    except Exception as e:
        _elapsed = time.time() - _t0
        _nd_logger.error(
            "[KANNADA] EXCEPTION after %.2fs  type=%s  msg=%s\n%s",
            _elapsed, type(e).__name__, e, _traceback.format_exc(),
        )
        import sys
        print(f"[NewsData Kannada] fetch error: {e}", file=sys.stderr)
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

        articles.append({
            "headline":       item.get("title", ""),
            "snippet":        (item.get("description") or "")[:600],
            "full_content":   item.get("content") or item.get("description") or "",
            "source_name":    item.get("source_id", "Unknown"),
            "published_iso":  pub_iso,
            "url":            url_link,
            "source_channel": "newsdata",
        })
    _nd_logger.debug("[KANNADA] PARSED  %d articles after date filter (raw results=%d)", len(articles), len(data.get("results", [])))
    return articles


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

    base_params_dict = {
        "apikey":   api_key,
        "q":        f"{district} {state} politics",
        "country":  "in",
    }
    base_params = urllib.parse.urlencode(base_params_dict)
    url = f"https://newsdata.io/api/1/news?{base_params}&language=en,hi"
    _nd_logger.debug(
        "[PRIMARY] REQUEST  url=%s  params(no key)=%s",
        url.split("?")[0],
        {k: v for k, v in base_params_dict.items() if k != "apikey"},
    )
    _t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PolitiScan/1.3"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            _status = resp.status
            _raw    = resp.read()
        _elapsed = time.time() - _t0
        _nd_logger.debug("[PRIMARY] RESPONSE http_status=%s  elapsed=%.2fs  body_bytes=%d", _status, _elapsed, len(_raw))
        _nd_logger.debug("[PRIMARY] BODY %s", _raw.decode(errors="replace")[:2000])
        data = json.loads(_raw.decode())
    except Exception as e:
        _elapsed = time.time() - _t0
        _nd_logger.error(
            "[PRIMARY] EXCEPTION after %.2fs  type=%s  msg=%s\n%s",
            _elapsed, type(e).__name__, e, _traceback.format_exc(),
        )
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
    _nd_logger.debug("[PRIMARY] PARSED  %d articles after date filter (raw results=%d)", len(articles), len(data.get("results", [])))
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

        if nd_total > 0:
            breakdown_line = f"**{nd_total}** from NewsData.io + **{rss_total}** from Google RSS"
        else:
            breakdown_line = f"**{rss_total}** from Google RSS"
        top_outlets = sorted(outlet_counts.items(), key=lambda x: -x[1])[:8]
        outlet_str  = "   ".join(f"**{k}:** {v}" for k, v in top_outlets)
        if outlet_str:
            breakdown_line += "   \u2014   " + outlet_str
        st.caption(breakdown_line)

    if "funnel_counts" in st.session_state:
        fc = st.session_state.funnel_counts
        st.caption(
            f"{fc['post_dedup']} after dedup \u2192 {fc['political']} political \u2192 {fc['shortlist']} in shortlist"
        )

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

    state_outlet_options = ["All Outlets"] + [o["name"] for o in STATE_OUTLETS.get(state, [])]

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
    debug_mode = st.checkbox("Debug Mode", value=False, help="Show raw source names from RSS/NewsData and filter details")

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
                "source_breakdown", "shortlist_articles", "show_all_articles",
                "funnel_counts"):
        st.session_state.pop(key, None)

    api_key      = os.getenv("ANTHROPIC_API_KEY", "")
    region_label = f"{district}, {state}"
    st.session_state.region_label = region_label

    rss_result = [None, None, {}]   # [entries, scope, outlet_site_counts]
    nd_result  = [[]]              # [articles]

    def _rss_worker():
        entries, scope_val, outlet_counts = fetch_all_feeds(district, state, tuple(active_outlets))
        rss_result[0] = entries
        rss_result[1] = scope_val
        rss_result[2] = outlet_counts

    def _nd_worker():
        import sys
        try:
            try:
                _key = st.secrets["NEWSDATA_API_KEY"]
            except Exception:
                _key = os.getenv("NEWSDATA_API_KEY", "")
            _key = (_key or "").strip()

            if active_outlets:
                _kannada_selected = [o for o in active_outlets if o in _KANNADA_OUTLET_NAMES]
                _other_selected   = [o for o in active_outlets if o not in _KANNADA_OUTLET_NAMES]

                _all_nd = []

                # Kannada outlets → ONE NewsData.io call, no domainurl, filter post-fetch
                if _kannada_selected:
                    _kn_arts_raw = fetch_newsdata_kannada(district, state, _key)

                    # Build domain-prefix and full-domain sets for matching source_id
                    _kn_domain_prefixes: set = set()
                    _kn_domains_full:    set = set()
                    for _outlet in _kannada_selected:
                        _dom = OUTLET_DOMAINS.get(_outlet, "")
                        if _dom:
                            _kn_domain_prefixes.add(_dom.split(".")[0].lower())
                            _kn_domains_full.add(_dom.lower())
                    _kn_names_lower = {o.lower() for o in _kannada_selected}

                    def _nd_matches_kannada(art):
                        src = (art.get("source_name") or "").lower().strip()
                        if src in _kn_domain_prefixes or src in _kn_names_lower:
                            return True
                        try:
                            host = urllib.parse.urlparse(art.get("url") or "").netloc.lower()
                            host = host.replace("www.", "")
                            if host in _kn_domains_full:
                                return True
                        except Exception:
                            pass
                        return False

                    _all_nd.extend(a for a in _kn_arts_raw if _nd_matches_kannada(a))

                # Non-Kannada outlets → primary fetch (domainurl not available on this plan)
                if _other_selected:
                    _all_nd.extend(fetch_newsdata_primary(district, state, _key))

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

    raw_entries        = rss_result[0] or []
    scope              = rss_result[1] or "district"
    outlet_site_counts = rss_result[2] or {}
    newsdata_dicts     = nd_result[0] or []

    # ── BOILERPLATE FILTER ────────────────────────────────────────────────────
    # Strip obvious non-article pages (Terms, Privacy Policy, Contact Us, etc.)
    # that site-restricted RSS queries sometimes return for certain domains.
    # Runs always (not just in Debug Mode) so real articles are counted correctly.
    _BOILERPLATE_PATTERNS = frozenset({
        "terms & conditions", "terms and conditions", "terms of service",
        "privacy policy", "contact us", "about us", "cookie policy",
        "disclaimer", "advertise with us",
    })
    _active_outlet_names_lower = {o.lower() for o in (active_outlets or [])}

    def _is_boilerplate_entry(entry) -> bool:
        title_lower = (getattr(entry, "title", "") or "").strip().lower()
        if not title_lower:
            return False
        if any(pat in title_lower for pat in _BOILERPLATE_PATTERNS):
            return True
        # Title is nothing but the outlet's own display name with no real content
        if title_lower in _active_outlet_names_lower:
            return True
        return False

    raw_entries = [e for e in raw_entries if not _is_boilerplate_entry(e)]
    # ── END BOILERPLATE FILTER ────────────────────────────────────────────────

    recent, _  = filter_recent(raw_entries, hours=36)

    unique_rss = deduplicate(recent, threshold=0.70)

    rss_dicts  = entries_to_dicts(unique_rss, channel="rss")
    rss_total_raw = len(rss_dicts)

    # Build a name→domain map for the active outlet selection.
    # Domains come from the "domain" field baked into STATE_OUTLETS (via OUTLET_DOMAINS).
    _active_outlet_domains: dict[str, str] = {
        o: (OUTLET_DOMAINS.get(o) or "").lower()
        for o in active_outlets
    }

    if active_outlets and outlet_site_counts:
        _outlet_summary = []
        for _oname in active_outlets:
            _counts = outlet_site_counts.get(_oname, {})
            if "native" in _counts:
                _outlet_summary.append(f"{_oname}: native feed  ({_counts['native']} entries)")
            else:
                _n = _counts.get("site_en", 0) + _counts.get("site_kn", 0)
                _outlet_summary.append(f"{_oname}: Google site-restricted  ({_n} entries)")
        if debug_mode and _outlet_summary:
            st.sidebar.markdown("**Per-outlet fetch method**")
            st.sidebar.code("\n".join(_outlet_summary))

    # Filter RSS results by selected outlets using normalized domain/name matching.
    # normalize_source() strips protocol, www., and '- Google News' suffixes so that
    # source tags like "Vijaya Karnataka - vijaykarnataka.com" match correctly.
    if active_outlets:

        # Pre-compute normalized outlet names and domains once for efficiency.
        _outlet_name_norms = {
            outlet_name: normalize_source(outlet_name)
            for outlet_name in _active_outlet_domains
        }

        def _rss_matches_outlet(art):
            src_raw  = art.get("source_name") or ""
            src_norm = normalize_source(src_raw)

            # Fast path: exact case-insensitive name match.
            # Handles native RSS feed entries whose source_name is set directly
            # to the canonical outlet name via _forced_source at fetch time
            # (e.g. "Udayavani", "Prajavani", "Vijaya Karnataka").
            src_lower = src_raw.strip().lower()
            for outlet_name in _active_outlet_domains:
                if src_lower == outlet_name.lower():
                    return True

            try:
                url_host_norm = normalize_source(
                    urllib.parse.urlparse(art.get("url") or "").netloc
                )
            except Exception:
                url_host_norm = ""

            for outlet_name, domain in _active_outlet_domains.items():
                name_norm = _outlet_name_norms[outlet_name]

                # Normalized name match, or with leading "The " prefix
                if src_norm == name_norm or src_norm == "the " + name_norm:
                    return True

                # Outlet name appears as substring in source tag
                # (handles "Vijaya Karnataka - vijaykarnataka.com")
                if name_norm and name_norm in src_norm:
                    return True

                # URL host matches outlet domain exactly
                if domain and url_host_norm == domain:
                    return True

                # Source tag IS the domain (e.g. "vijaykarnataka.com")
                if domain and src_norm == domain:
                    return True

                # Domain string appears in source tag
                if domain and domain in src_norm:
                    return True

            return False

        rss_dicts = [a for a in rss_dicts if _rss_matches_outlet(a)]

    rss_total = len(rss_dicts)

    unique_nd     = deduplicate_dicts(newsdata_dicts, threshold=0.70)
    nd_count      = len(unique_nd)
    total_fetched = rss_total_raw + nd_count   # pre-filter total for display
    article_dicts = rss_dicts + unique_nd

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
                "_client_adjusted_score":  client_adj,
                "_affects_client_region":  art.get("affects_client_region", False),
                "_profile_boosted":        art.get("profile_boosted", False),
            })

        SHORTLIST_THRESHOLD = 5.0   # articles >= this score qualify directly

        # Shortlist: articles scoring >= 5.0, always at least the top 10 by score.
        # Everything else stays in "not in shortlist" for the user to review and promote.
        _above = [r for r in rows if r.get("_client_adjusted_score", 0) >= SHORTLIST_THRESHOLD]
        _shortlist = _above if len(_above) >= 10 else rows[:10]
        st.session_state.shortlist_articles = _shortlist
        st.session_state.funnel_counts = {
            "post_dedup": post_dedup_count,
            "political":  len(ranked),
            "shortlist":  len(_shortlist),
        }

        dupes_merged = pre_dedup_count - post_dedup_count
        filter_note = (
            f"  {nd_count} from NewsData.io + {rss_total} from Google RSS."
            if nd_count > 0 else
            f"  {rss_total} from Google RSS."
        )
        caption = (
            f"**{len(ranked)} political articles ranked**{scope_note}.  "
            f"{dupes_merged} duplicates merged from {pre_dedup_count} candidates.{filter_note}"
        )

        st.session_state.results_rows    = rows
        st.session_state.results_caption = caption
        _show_results()

elif "results_rows" in st.session_state:
    _show_results()
