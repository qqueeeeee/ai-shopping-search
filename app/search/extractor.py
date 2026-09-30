"""Product extraction from web pages - supports Amazon, Flipkart, and generic pages."""
import logging
import json
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

from app.schemas import Product

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}


def extract_products_from_url(url: str, category: Optional[str] = None) -> list[Product]:
    """
    Extract product(s) from a URL.
    For listing pages (Amazon search, Flipkart category), returns multiple products.
    For single product pages, returns a list with one product.
    """
    if not _is_valid_url(url):
        return []

    try:
        resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            logger.warning(f"HTTP {resp.status_code} for {url}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        final_url = str(resp.url)
        domain = urlparse(final_url).netloc

        # Detect site and use appropriate extractor
        if "amazon." in domain:
            products = _extract_amazon(soup, final_url, domain, category)
            if products:
                return products

        if "flipkart.com" in domain:
            products = _extract_flipkart(soup, final_url, domain, category)
            if products:
                return products

        # Generic single-product extraction
        product = _extract_generic(soup, final_url, domain, category)
        return [product] if product else []

    except Exception as e:
        logger.error(f"Failed to extract from {url}: {e}")
        return []


def extract_product(url: str, category: Optional[str] = None) -> Optional[Product]:
    """Extract a single product (backward compatible)."""
    products = extract_products_from_url(url, category)
    return products[0] if products else None


def extract_product_from_snippet(title: str, snippet: str, url: str, category: Optional[str] = None) -> Optional[Product]:
    """Create a basic product from search result snippet."""
    if not title:
        return None
    price = _extract_price_from_text(f"{title} {snippet}")
    domain = urlparse(url).netloc if url else "unknown"
    return Product(
        name=title.strip(),
        category=category,
        price=price,
        currency="INR" if price else None,
        description=snippet.strip() if snippet else None,
        attributes={},
        source_url=url,
        source_name=domain,
        retrieved_at=datetime.now(timezone.utc),
    )


# ---- Amazon extraction ----

def _extract_amazon(soup: BeautifulSoup, url: str, domain: str, category: Optional[str] = None) -> list[Product]:
    """Extract products from Amazon search/listing or product pages."""
    products = []

    # Check if it's a search results / listing page
    result_divs = soup.select("div[data-component-type='s-search-result']")
    if not result_divs:
        # Also try alternative selectors
        result_divs = soup.select("div.s-result-item[data-asin]")

    if result_divs:
        # It's a search/listing page - extract individual products
        for div in result_divs[:15]:
            asin = div.get("data-asin", "")
            if not asin or asin == "":
                continue

            # Title
            title_el = div.select_one("h2 a span") or div.select_one("h2 span")
            if not title_el:
                continue
            name = title_el.get_text(strip=True)
            if not name or len(name) < 5:
                continue

            # Product URL - build from ASIN as reliable fallback
            link_el = div.select_one("h2 a")
            product_url = f"https://{domain}/dp/{asin}"
            if link_el and link_el.get("href"):
                href = link_el["href"]
                if href.startswith("/"):
                    product_url = f"https://{domain}{href}"
                elif href.startswith("http"):
                    product_url = href

            # Price
            price = None
            price_whole = div.select_one("span.a-price-whole")
            if price_whole:
                price_text = price_whole.get_text(strip=True).replace(",", "").replace(".", "")
                try:
                    price = float(price_text)
                except ValueError:
                    pass

            if price is None:
                # Try alternative price selectors
                price_el = div.select_one("span.a-price span.a-offscreen")
                if price_el:
                    price = _extract_price_from_text(price_el.get_text())

            # Rating
            attrs = {}
            rating_el = div.select_one("span.a-icon-alt")
            if rating_el:
                attrs["rating"] = rating_el.get_text(strip=True)

            reviews_el = div.select_one("span.a-size-base.s-underline-text")
            if reviews_el:
                attrs["reviews"] = reviews_el.get_text(strip=True)

            products.append(Product(
                name=name,
                category=category,
                price=price,
                currency="INR" if price else None,
                attributes=attrs,
                source_url=product_url or url,
                source_name=domain,
                retrieved_at=datetime.now(timezone.utc),
            ))

        logger.info(f"Extracted {len(products)} products from Amazon listing")
        return products

    # Single product page - try JSON-LD first
    product = _extract_jsonld(soup, url, domain, category)
    if product:
        return [product]

    # Amazon single product page fallback
    title_el = soup.select_one("#productTitle")
    if title_el:
        name = title_el.get_text(strip=True)
        price = None
        price_el = soup.select_one("span.a-price-whole") or soup.select_one("#priceblock_ourprice") or soup.select_one("#priceblock_dealprice")
        if price_el:
            price = _extract_price_from_text(price_el.get_text())

        attrs = {}
        # Extract from feature bullets
        bullets = soup.select("#feature-bullets li span")
        for i, b in enumerate(bullets[:5]):
            attrs[f"feature_{i+1}"] = b.get_text(strip=True)[:100]

        # Tech specs table
        for row in soup.select("#productDetails_techSpec_section_1 tr, table.a-keyvalue tr"):
            th = row.select_one("th")
            td = row.select_one("td")
            if th and td:
                key = th.get_text(strip=True).lower().replace(" ", "_")
                attrs[key] = td.get_text(strip=True)

        return [Product(
            name=name,
            category=category,
            price=price,
            currency="INR" if price else None,
            attributes=attrs,
            source_url=url,
            source_name=domain,
            retrieved_at=datetime.now(timezone.utc),
        )]

    return []


# ---- Flipkart extraction ----

def _extract_flipkart(soup: BeautifulSoup, url: str, domain: str, category: Optional[str] = None) -> list[Product]:
    """Extract products from Flipkart search/listing or product pages."""
    products = []

    # Flipkart listing page - product cards
    # Flipkart uses dynamic class names, so we look for common patterns
    product_cards = soup.select("div[data-id]")
    if not product_cards:
        # Alternative: look for product links in listing
        product_cards = soup.select("a[href*='/p/']")

    # Try to find products from the listing structure
    # Flipkart uses various class patterns, try to find title + price combos
    all_links = soup.find_all("a", href=True)
    seen_urls = set()

    for link in all_links:
        href = link.get("href", "")
        if "/p/" not in href and "/dl/" not in href:
            continue

        # Build full URL
        if href.startswith("/"):
            product_url = f"https://www.flipkart.com{href}"
        else:
            product_url = href

        # Deduplicate
        base_url = product_url.split("?")[0]
        if base_url in seen_urls:
            continue
        seen_urls.add(base_url)

        # Find the product card container
        parent = link
        for _ in range(5):
            parent = parent.parent
            if parent is None:
                break

        if parent is None:
            continue

        # Try to extract title from link text or nearby elements
        name = link.get_text(strip=True)
        if not name or len(name) < 5 or len(name) > 300:
            # Look for title in parent
            title_candidates = parent.find_all(["div", "span", "a"], string=True)
            for tc in title_candidates:
                text = tc.get_text(strip=True)
                if 10 < len(text) < 200:
                    name = text
                    break

        if not name or len(name) < 5:
            continue

        # Find price
        price = None
        price_els = parent.find_all(string=re.compile(r'₹'))
        for pel in price_els:
            p = _extract_price_from_text(pel.strip())
            if p and p > 100:  # Skip tiny numbers
                price = p
                break

        products.append(Product(
            name=name[:200],
            category=category,
            price=price,
            currency="INR" if price else None,
            attributes={},
            source_url=product_url,
            source_name="flipkart.com",
            retrieved_at=datetime.now(timezone.utc),
        ))

        if len(products) >= 15:
            break

    if products:
        logger.info(f"Extracted {len(products)} products from Flipkart listing")
        return products

    # Single product page
    product = _extract_generic(soup, url, domain, category)
    return [product] if product else []


# ---- Generic extraction ----

def _extract_generic(soup: BeautifulSoup, url: str, domain: str, category: Optional[str] = None) -> Optional[Product]:
    """Generic product extraction using JSON-LD, meta tags, page text."""
    # Try JSON-LD
    product = _extract_jsonld(soup, url, domain, category)
    if product:
        return product

    # Try meta tags
    product = _extract_meta(soup, url, domain, category)
    if product:
        return product

    # Fallback: page text
    return _extract_from_text(soup, url, domain, category)


def _extract_jsonld(soup: BeautifulSoup, url: str, domain: str, category: Optional[str] = None) -> Optional[Product]:
    """Extract product info from JSON-LD structured data."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict) and item.get("@graph"):
                    items.extend(item["@graph"])

            for item in items:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("@type", "")
                if isinstance(item_type, list):
                    item_type = " ".join(item_type)
                if "Product" in item_type:
                    name = item.get("name", "")
                    price = None
                    currency = None
                    offers = item.get("offers", {})
                    if isinstance(offers, list) and offers:
                        offers = offers[0]
                    if isinstance(offers, dict):
                        price_str = offers.get("price") or offers.get("lowPrice")
                        if price_str:
                            try:
                                price = float(str(price_str).replace(",", ""))
                            except (ValueError, TypeError):
                                pass
                        currency = offers.get("priceCurrency", "INR")

                    desc = item.get("description", "")
                    if isinstance(desc, list):
                        desc = " ".join(desc)

                    attrs = {}
                    for key in ["brand", "color", "model", "sku", "weight"]:
                        val = item.get(key)
                        if val:
                            if isinstance(val, dict):
                                val = val.get("name", str(val))
                            attrs[key] = str(val)

                    return Product(
                        name=name,
                        category=category,
                        price=price,
                        currency=currency,
                        description=desc[:1000] if desc else None,
                        attributes=attrs,
                        source_url=url,
                        source_name=domain,
                        retrieved_at=datetime.now(timezone.utc),
                    )
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _extract_meta(soup: BeautifulSoup, url: str, domain: str, category: Optional[str] = None) -> Optional[Product]:
    """Extract from OpenGraph / meta tags."""
    og_title = _get_meta(soup, "og:title") or _get_meta(soup, "twitter:title")
    if not og_title:
        title_tag = soup.find("title")
        og_title = title_tag.get_text(strip=True) if title_tag else None
    if not og_title:
        return None

    og_desc = _get_meta(soup, "og:description") or _get_meta(soup, "description")
    og_price = _get_meta(soup, "product:price:amount") or _get_meta(soup, "og:price:amount")
    og_currency = _get_meta(soup, "product:price:currency")

    price = None
    if og_price:
        try:
            price = float(og_price.replace(",", ""))
        except (ValueError, TypeError):
            pass
    if not price:
        price = _extract_price_from_text(soup.get_text()[:3000])

    return Product(
        name=og_title,
        category=category,
        price=price,
        currency=og_currency or ("INR" if price else None),
        description=og_desc[:1000] if og_desc else None,
        attributes={},
        source_url=url,
        source_name=domain,
        retrieved_at=datetime.now(timezone.utc),
    )


def _extract_from_text(soup: BeautifulSoup, url: str, domain: str, category: Optional[str] = None) -> Optional[Product]:
    """Fallback: extract from page text."""
    h1 = soup.find("h1")
    title_tag = soup.find("title")
    name = h1.get_text(strip=True) if h1 else (title_tag.get_text(strip=True) if title_tag else None)
    if not name:
        return None

    desc = _get_meta(soup, "description")
    if not desc:
        p = soup.find("p")
        desc = p.get_text(strip=True)[:500] if p else None

    price = _extract_price_from_text(soup.get_text()[:5000])

    return Product(
        name=name[:300],
        category=category,
        price=price,
        currency="INR" if price else None,
        description=desc[:1000] if desc else None,
        attributes={},
        source_url=url,
        source_name=domain,
        retrieved_at=datetime.now(timezone.utc),
    )


# ---- Utilities ----

def _is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _get_meta(soup: BeautifulSoup, name: str) -> Optional[str]:
    tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


def _extract_price_from_text(text: str) -> Optional[float]:
    patterns = [
        r'₹\s*([\d,]+(?:\.\d{2})?)',
        r'Rs\.?\s*([\d,]+(?:\.\d{2})?)',
        r'INR\s*([\d,]+(?:\.\d{2})?)',
        r'\$\s*([\d,]+(?:\.\d{2})?)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                val = float(match.group(1).replace(",", ""))
                if val > 100:  # Skip tiny matches
                    return val
            except ValueError:
                continue
    return None
