"""Agent tools - explicit tool functions for the agentic workflow."""
import logging
from typing import Optional
from app.search.web_search import web_search
from app.search.extractor import extract_products_from_url, extract_product_from_snippet
from app.schemas import Product, SearchRequirements
from app.retrieval.ranking import semantic_rank, apply_hard_constraints, rerank_products

logger = logging.getLogger(__name__)


def tool_web_search(query: str, max_results: int = 10) -> list[dict]:
    """
    TOOL: Web Search
    Searches the web for products matching the query.
    Returns a list of search results with title, URL, and snippet.
    """
    logger.info(f"[TOOL] web_search(query='{query}', max_results={max_results})")
    results = web_search(query, max_results=max_results)
    logger.info(f"[TOOL] web_search returned {len(results)} results")
    return results


def tool_extract_products(
    search_results: list[dict],
    category: Optional[str] = None,
    max_extract: int = 15,
) -> list[Product]:
    """
    TOOL: Product Extraction
    Extracts product information from search result URLs.
    Falls back to snippet-based extraction when page scraping fails.
    """
    logger.info(f"[TOOL] extract_products(count={len(search_results)}, category={category})")
    products = []
    attempted = 0

    # E-commerce domains where snippet fallback is OK
    ecom_domains = {"amazon.", "flipkart.", "myntra.", "snapdeal.", "croma.", "reliance", "vijaysales", "tatacliq"}

    for result in search_results[:max_extract]:
        url = result.get("url", "")
        title = result.get("title", "")
        snippet = result.get("snippet", "")

        if not url:
            continue

        # Skip ad redirect URLs
        if "duckduckgo.com/y.js" in url or "bing.com/aclick" in url:
            continue

        attempted += 1

        # Extract products (may return multiple from listing pages)
        extracted = extract_products_from_url(url, category=category)

        if extracted:
            # Filter out junk "products"
            valid = [p for p in extracted if _is_valid_product(p, category)]
            if valid:
                logger.info(f"[TOOL] Extracted {len(valid)} product(s) from: {url[:60]}")
                products.extend(valid)
        else:
            # Only use snippet fallback for e-commerce domains
            is_ecom = any(d in url.lower() for d in ecom_domains)
            if is_ecom:
                product = extract_product_from_snippet(title, snippet, url, category=category)
                if product and _is_valid_product(product, category):
                    logger.info(f"[TOOL] Created product from snippet: {product.name}")
                    products.append(product)

    logger.info(f"[TOOL] extract_products: {len(products)} products from {attempted} URLs")
    return products


def _is_valid_product(product: Product, category: Optional[str] = None) -> bool:
    """Check if extracted product is actually a valid product, not junk."""
    name = (product.name or "").lower()

    # Too short or too long
    if len(name) < 5 or len(name) > 500:
        return False

    # Junk product names
    junk_patterns = [
        "download", "install", "sign up", "sign in", "login",
        "whatsapp", "cookie", "privacy policy", "terms of service",
        "subscribe", "newsletter", "free shipping", "customer service",
        "online shopping india", "buy mobiles", "best price",
    ]
    if any(j in name for j in junk_patterns):
        return False

    # If it's a generic page title (no specific product info)
    generic_titles = [
        "flipkart.com", "amazon.in", "online shopping",
        "home page", "welcome to", "official site",
    ]
    if any(g in name for g in generic_titles):
        return False

    return True


def tool_compare_products(
    products: list[Product],
    requirements: SearchRequirements,
    top_k: int = 5,
) -> list[Product]:
    """
    TOOL: Product Comparison
    Semantically ranks products, applies hard constraints, and reranks.
    Returns the top matching products.
    """
    logger.info(f"[TOOL] compare_products(count={len(products)}, budget_max={requirements.budget_max})")

    # Step 1: Semantic ranking
    ranked = semantic_rank(products, requirements)
    logger.info(f"[TOOL] After semantic ranking: {len(ranked)} products")

    # Step 2: Apply hard constraints (budget, etc.) - deterministic, not LLM
    filtered = apply_hard_constraints(ranked, requirements)
    logger.info(f"[TOOL] After hard constraint filtering: {len(filtered)} products")

    # Step 3: Final reranking
    top = rerank_products(filtered, requirements, top_k=top_k)
    logger.info(f"[TOOL] Final top {len(top)} products selected")

    return top
