"""Shopping Agent - orchestrates the agentic workflow."""
import logging
import json
import re
from typing import Optional

from app.schemas import SearchRequirements, Product, ActivityEvent, SearchResponse
from app.llm.client import llm_json, llm_chat
from app.agent.tools import tool_web_search, tool_extract_products, tool_compare_products

logger = logging.getLogger(__name__)


def _budget_max_from_query(query: str) -> Optional[float]:
    """Parse common upper-budget phrases, including shorthand such as 50k."""
    match = re.search(
        r"\b(?:under|below|less than|up to|upto)\s*(?:₹|rs\.?\s*|inr\s*)?"
        r"([\d,]+(?:\.\d+)?)\s*(k|thousand|lakh|lac)?\b",
        query,
        flags=re.I,
    )
    if not match:
        return None
    amount = float(match.group(1).replace(",", ""))
    unit = (match.group(2) or "").lower()
    if unit in {"k", "thousand"}:
        amount *= 1_000
    elif unit in {"lakh", "lac"}:
        amount *= 100_000
    return amount


class ShoppingAgent:
    """
    AI Shopping Agent that orchestrates tools to find and recommend products.

    Workflow:
    1. LLM understands the query → structured requirements
    2. Web search tool → candidate URLs
    3. Product extraction tool → canonical products
    4. Comparison tool → ranked/filtered products
    5. LLM generates recommendation explanation
    """

    def __init__(self):
        self.activity: list[ActivityEvent] = []
        self.max_searches = 3

    def _log(self, step: str, status: str, detail: Optional[str] = None):
        event = ActivityEvent(step=step, status=status, detail=detail)
        self.activity.append(event)
        logger.info(f"[AGENT] {step}: {status} - {detail or ''}")

    async def run(self, query: str) -> SearchResponse:
        """Execute the full agent pipeline."""
        self.activity = []

        # STEP 1: Understand the request
        self._log("Understanding request", "running")
        try:
            requirements = self._understand_query(query)
            self._log("Understanding request", "done",
                      f"Category: {requirements.category}, Budget: {requirements.budget_max} {requirements.currency}")
        except Exception as e:
            logger.warning("LLM query understanding failed; using basic parsing: %s", e)
            requirements = self._fallback_requirements(query)
            self._log("Understanding request", "done", "Used basic query parsing")

        # STEP 2: Web search
        self._log("Searching web", "running")
        all_search_results = []
        try:
            # Primary search
            search_queries = self._generate_search_queries(requirements)
            for sq in search_queries[:self.max_searches]:
                results = tool_web_search(sq, max_results=10)
                all_search_results.extend(results)
                self._log("Searching web", "done", f"'{sq}' → {len(results)} results")
        except Exception as e:
            self._log("Searching web", "error", str(e))

        if not all_search_results:
            self._log("Searching web", "error", "No search results found")
            return SearchResponse(
                query=query,
                requirements=requirements,
                products=[],
                recommendation="Sorry, I couldn't find any products matching your request. Please try a different query.",
                activity=self.activity,
            )

        # Deduplicate by URL
        seen_urls = set()
        unique_results = []
        for r in all_search_results:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                unique_results.append(r)

        # STEP 3: Extract products
        self._log("Extracting products", "running")
        try:
            products = tool_extract_products(unique_results, category=requirements.category, max_extract=15)
            # Deduplicate products by source_url
            seen_product_urls = set()
            unique_products = []
            for p in products:
                key = p.source_url or p.name
                if key not in seen_product_urls:
                    seen_product_urls.add(key)
                    # Default currency to INR
                    if p.price and not p.currency:
                        p.currency = "INR"
                    unique_products.append(p)
            products = unique_products
            self._log("Extracting products", "done", f"Extracted {len(products)} products")
        except Exception as e:
            self._log("Extracting products", "error", str(e))
            products = []

        if not products:
            return SearchResponse(
                query=query,
                requirements=requirements,
                products=[],
                recommendation="I found some search results but couldn't extract product information. Please try again.",
                activity=self.activity,
            )

        # STEP 4: Compare and rank
        self._log("Matching & comparing products", "running")
        try:
            top_products = tool_compare_products(products, requirements, top_k=5)
            self._log("Matching & comparing products", "done",
                      f"{len(top_products)} products after filtering and ranking")
        except Exception as e:
            self._log("Matching & comparing products", "error", str(e))
            top_products = products[:5]

        # STEP 5: Generate recommendation
        self._log("Generating recommendation", "running")
        try:
            recommendation = self._generate_recommendation(top_products, requirements)
            # Also generate per-product match reasons
            top_products = self._generate_match_reasons(top_products, requirements)
            self._log("Generating recommendation", "done")
        except Exception as e:
            self._log("Generating recommendation", "error", str(e))
            recommendation = self._fallback_recommendation(top_products, requirements)

        return SearchResponse(
            query=query,
            requirements=requirements,
            products=top_products,
            recommendation=recommendation,
            activity=self.activity,
        )

    def _understand_query(self, query: str) -> SearchRequirements:
        """Use LLM to extract structured requirements from natural language."""
        system_prompt = """You are a shopping query analyzer for an Indian e-commerce assistant. Extract structured requirements from the user's shopping query.

Output a JSON object with these fields:
- category: product category (e.g., "laptop", "phone", "book", "shoes", "headphones", "camera")
- query: a short product-focused search query. MUST include the product category. Examples: "laptop for AI LLM development", "wireless noise cancelling headphones", "running shoes for marathon". Do NOT include "best", "find", "under" or prices in this field.
- budget_min: minimum budget as a number (null if not specified)
- budget_max: maximum budget as a number (null if not specified)
- currency: always "INR"
- hard_constraints: object of must-have requirements (e.g., {"min_ram": "16GB"})
- preferences: object of nice-to-have preferences. ALWAYS extract useful preferences from the query context. For example, if someone asks for a laptop for "AI LLM running", preferences should include {"use_case": "running local AI/LLM models", "ram": "high RAM", "gpu": "dedicated GPU"}.

Be precise with budget extraction. "under ₹70,000" means budget_max=70000.
If no budget is mentioned, set budget_min and budget_max to null."""

        result = llm_json(system_prompt, f"Query: {query}")
        if not isinstance(result, dict):
            raise ValueError("Query understanding did not return a JSON object")
        # Keep explicit user budgets deterministic even when the LLM misses them.
        budget_max = _budget_max_from_query(query)
        if budget_max is not None:
            result["budget_max"] = budget_max
        # Force currency to INR
        result["currency"] = "INR"
        return SearchRequirements(**result)

    def _fallback_requirements(self, query: str) -> SearchRequirements:
        """Extract the essentials locally when the LLM response is unavailable."""
        lowered = query.lower()
        category = "general"
        for pattern, value in (
            (r"\b(mobile\s*phones?|smartphones?|cell\s*phones?)\b", "mobile phone"),
            (r"\bphones?\b", "phone"),
            (r"\blaptops?\b", "laptop"),
            (r"\bheadphones?\b", "headphones"),
            (r"\btablets?\b", "tablet"),
        ):
            if re.search(pattern, lowered):
                category = value
                break

        clean_query = re.sub(r"\b(?:under|below|less than|up to|upto)\b.*$", "", query, flags=re.I)
        clean_query = re.sub(r"\b(?:best|find|show me|search for)\b", "", clean_query, flags=re.I)
        clean_query = " ".join(clean_query.split()).strip(" ,.-") or category
        return SearchRequirements(
            category=category,
            query=clean_query,
            budget_max=_budget_max_from_query(query),
        )

    def _generate_search_queries(self, req: SearchRequirements) -> list[str]:
        """Generate web search queries targeting actual product pages."""
        queries = []
        budget_str = f" under ₹{int(req.budget_max)}" if req.budget_max else ""

        # Always search Indian e-commerce
        queries.append(f"site:amazon.in {req.query}{budget_str}")
        queries.append(f"site:flipkart.com {req.query}{budget_str}")
        # Also a general search for this product in India
        queries.append(f"{req.query} buy online India{budget_str}")

        return queries

    def _generate_recommendation(self, products: list[Product], req: SearchRequirements) -> str:
        """Use LLM to generate a recommendation summary."""
        if not products:
            return "No products found matching your criteria."

        products_text = ""
        for i, p in enumerate(products, 1):
            products_text += f"\n{i}. {p.name}"
            if p.price:
                products_text += f" - {p.currency or ''} {p.price:,.0f}"
            if p.attributes:
                attrs = ", ".join(f"{k}: {v}" for k, v in p.attributes.items() if v)
                if attrs:
                    products_text += f"\n   Specs: {attrs}"
            if p.description:
                products_text += f"\n   {p.description[:200]}"

        system_prompt = """You are a helpful shopping advisor. Based on the products found and the user's requirements, provide a brief recommendation summary (2-4 sentences).

Focus on:
- Which product(s) best match the requirements and why
- Key trade-offs between top options
- Any important notes about the results

Do NOT invent or assume specifications that aren't provided. Only reference what's actually known about each product."""

        user_prompt = f"""User's requirements:
- Category: {req.category}
- Query: {req.query}
- Budget: {req.budget_max} {req.currency if req.budget_max else 'not specified'}
- Preferences: {json.dumps(req.preferences)}

Products found:{products_text}"""

        return llm_chat(system_prompt, user_prompt)

    def _generate_match_reasons(self, products: list[Product], req: SearchRequirements) -> list[Product]:
        """Generate brief match reasons for each product."""
        try:
            products_info = []
            for p in products:
                products_info.append({
                    "name": p.name,
                    "price": p.price,
                    "attributes": p.attributes,
                })

            system_prompt = """For each product, provide a brief one-sentence reason why it matches or is relevant to the user's query. Output a JSON array of strings, one reason per product. Do NOT invent specs that aren't listed."""

            user_prompt = f"""Query: {req.query}
Budget: {req.budget_max} {req.currency}
Preferences: {json.dumps(req.preferences)}

Products:
{json.dumps(products_info, default=str)}"""

            reasons = llm_json(system_prompt, user_prompt)
            if isinstance(reasons, list):
                for i, product in enumerate(products):
                    if i < len(reasons):
                        product.match_reason = str(reasons[i])
            elif isinstance(reasons, dict) and "reasons" in reasons:
                for i, product in enumerate(products):
                    if i < len(reasons["reasons"]):
                        product.match_reason = str(reasons["reasons"][i])
        except Exception as e:
            logger.error(f"Failed to generate match reasons: {e}")
            for p in products:
                p.match_reason = f"Matches your search for {req.category}"

        return products

    def _fallback_recommendation(self, products: list[Product], req: SearchRequirements) -> str:
        """Fallback recommendation without LLM."""
        if not products:
            return "No products found matching your criteria."

        top = products[0]
        rec = f"Based on your search for {req.query}, I found {len(products)} relevant products. "
        if top.price:
            rec += f"The top match is {top.name} at {top.currency or ''} {top.price:,.0f}."
        else:
            rec += f"The top match is {top.name}."
        return rec
