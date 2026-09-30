"""Web search tool - multiple search backends with strict filtering."""
import logging
import html
import urllib.parse
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Domains to skip entirely
BLOCKED_DOMAINS = {
    "duckduckgo.com", "bing.com", "google.com", "youtube.com",
    "facebook.com", "twitter.com", "instagram.com", "whatsapp.com",
    "wikipedia.org", "reddit.com", "quora.com", "pinterest.com",
    "linkedin.com", "tiktok.com",
}


def web_search(query: str, max_results: int = 10) -> list[dict]:
    """
    Search the web for products. Tries multiple backends.
    Returns list of {title, url, snippet}.
    """
    # Try another provider when a backend returns only redirects, ads, or junk.
    backends = (
        ("DuckDuckGo", _search_duckduckgo_html),
        ("Bing", _search_bing),
        ("Google", _search_google),
    )
    for backend_name, search_backend in backends:
        results = search_backend(query, max_results * 2)
        filtered = _filter_results(results)
        logger.info(
            "Search '%s' via %s: %s raw -> %s after filtering",
            query[:50], backend_name, len(results), len(filtered),
        )
        if filtered:
            return filtered[:max_results]

    return []


def _is_blocked_url(url: str) -> bool:
    """Check if URL is from a blocked domain."""
    try:
        domain = (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
        if any(domain == blocked or domain.endswith("." + blocked) for blocked in BLOCKED_DOMAINS):
            return True
        # Block DDG ad redirects
        if "duckduckgo.com/y.js" in url or "/aclick" in url:
            return True
    except Exception:
        pass
    return False


def _destination_url(url: str) -> str:
    """Unwrap search-engine redirect URLs to the actual result URL."""
    url = html.unescape(url).strip()
    if url.startswith("//"):
        url = "https:" + url

    for _ in range(2):
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if host not in {"duckduckgo.com", "bing.com", "google.com"}:
            break
        params = urllib.parse.parse_qs(parsed.query)
        destination = next((params[key][0] for key in ("uddg", "url", "q", "u") if params.get(key)), None)
        if not destination:
            break
        url = urllib.parse.unquote(destination)
    return url


def _filter_results(results: list[dict]) -> list[dict]:
    """Filter out ads, non-product pages, and junk results."""
    filtered = []
    seen_urls = set()

    for r in results:
        url = _destination_url(r.get("url", ""))
        title = r.get("title", "").lower()

        # Skip empty or blocked
        if not url or _is_blocked_url(url):
            continue

        # Skip duplicate base URLs
        base = url.split("?")[0].rstrip("/")
        if base in seen_urls:
            continue
        seen_urls.add(base)

        # Skip obvious non-product results
        junk_keywords = [
            "download", "install", "login", "sign up", "sign in",
            "whatsapp", "apk", "app store", "play store",
            "wiki", "definition", "meaning",
        ]
        if any(kw in title for kw in junk_keywords):
            continue

        filtered.append({**r, "url": url})

    return filtered


def _search_duckduckgo_html(query: str, max_results: int = 20) -> list[dict]:
    """Search using DuckDuckGo HTML endpoint directly."""
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"

        resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        for result in soup.select(".result.results_links"):
            title_el = result.select_one(".result__a")
            snippet_el = result.select_one(".result__snippet")

            if not title_el:
                continue

            href = title_el.get("href", "")
            # DDG wraps URLs through redirect
            if "uddg=" in href:
                try:
                    href = urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
                except Exception:
                    pass
            elif href.startswith("//"):
                href = "https:" + href

            if not href.startswith("http"):
                continue

            results.append({
                "title": title_el.get_text(strip=True),
                "url": href,
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
            })

            if len(results) >= max_results:
                break

        return results

    except Exception as e:
        logger.error(f"DDG HTML search failed: {e}")
        return []


def _search_bing(query: str, max_results: int = 20) -> list[dict]:
    """Search using Bing HTML scraping."""
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.bing.com/search?q={encoded}&count={max_results}"

        resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        for li in soup.select("li.b_algo"):
            title_el = li.select_one("h2 a")
            snippet_el = li.select_one(".b_caption p") or li.select_one("p")

            if not title_el:
                continue

            href = title_el.get("href", "")
            if not href.startswith("http"):
                continue

            results.append({
                "title": title_el.get_text(strip=True),
                "url": href,
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
            })

            if len(results) >= max_results:
                break

        return results

    except Exception as e:
        logger.error(f"Bing search failed: {e}")
        return []


def _search_google(query: str, max_results: int = 20) -> list[dict]:
    """Search using Google HTML scraping (last resort)."""
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.google.com/search?q={encoded}&num={max_results}"

        resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        for div in soup.select("div.g"):
            a_tag = div.select_one("a[href]")
            title_el = div.select_one("h3")
            snippet_el = div.select_one("div.VwiC3b") or div.select_one("span.aCOpRe")

            if not a_tag or not title_el:
                continue

            href = a_tag.get("href", "")
            if not href.startswith("http"):
                continue

            results.append({
                "title": title_el.get_text(strip=True),
                "url": href,
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
            })

            if len(results) >= max_results:
                break

        return results

    except Exception as e:
        logger.error(f"Google search failed: {e}")
        return []
