"""Semantic retrieval and ranking - TF-IDF with scikit-learn fallback to pure Python."""
import logging
import math
import re
from collections import Counter
from typing import Optional

from app.schemas import Product, SearchRequirements

logger = logging.getLogger(__name__)

# Try to import scikit-learn; fall back to pure Python
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity as sk_cosine
    HAS_SKLEARN = True
    logger.info("Using scikit-learn for TF-IDF similarity")
except ImportError:
    HAS_SKLEARN = False
    logger.info("scikit-learn not available, using pure Python similarity")


def product_to_text(product: Product) -> str:
    """Convert a product to a text representation for similarity."""
    parts = []
    if product.name:
        parts.append(product.name)
    if product.category:
        parts.append(f"Category: {product.category}")
    if product.description:
        parts.append(product.description[:500])
    if product.price:
        parts.append(f"Price: {product.currency or ''} {product.price}")
    for key, value in product.attributes.items():
        parts.append(f"{key}: {value}")
    return " ".join(parts)


# ---- Pure Python fallback similarity ----

def _tokenize(text: str) -> list[str]:
    """Simple tokenizer."""
    return re.findall(r'\b\w+\b', text.lower())


def _cosine_similarity_pure(vec_a: dict, vec_b: dict) -> float:
    """Cosine similarity between two term-frequency dicts."""
    common = set(vec_a.keys()) & set(vec_b.keys())
    dot = sum(vec_a[k] * vec_b[k] for k in common)
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _compute_similarities_pure(query_text: str, product_texts: list[str]) -> list[float]:
    """Compute cosine similarities using pure Python TF approach."""
    query_vec = Counter(_tokenize(query_text))
    similarities = []
    for pt in product_texts:
        prod_vec = Counter(_tokenize(pt))
        sim = _cosine_similarity_pure(query_vec, prod_vec)
        similarities.append(sim)
    return similarities


def _compute_similarities_sklearn(query_text: str, product_texts: list[str]) -> list[float]:
    """Compute cosine similarities using scikit-learn TF-IDF."""
    all_texts = [query_text] + product_texts
    vectorizer = TfidfVectorizer(
        max_features=5000,
        stop_words="english",
        ngram_range=(1, 2),
    )
    tfidf_matrix = vectorizer.fit_transform(all_texts)
    query_vec = tfidf_matrix[0:1]
    product_vecs = tfidf_matrix[1:]
    return sk_cosine(query_vec, product_vecs).flatten().tolist()


def semantic_rank(
    products: list[Product],
    requirements: SearchRequirements,
) -> list[Product]:
    """
    Rank products by semantic similarity to the query.
    Uses scikit-learn TF-IDF if available, otherwise pure Python term frequency.
    """
    if not products:
        return []

    # Build query text from requirements
    query_parts = [requirements.query]
    if requirements.category:
        query_parts.append(requirements.category)
    for key, value in requirements.preferences.items():
        query_parts.append(f"{key}: {value}")
    query_text = " ".join(query_parts)

    # Build product texts
    product_texts = [product_to_text(p) for p in products]

    try:
        if HAS_SKLEARN:
            similarities = _compute_similarities_sklearn(query_text, product_texts)
        else:
            similarities = _compute_similarities_pure(query_text, product_texts)

        # Assign scores
        for i, product in enumerate(products):
            product.relevance_score = float(similarities[i])

        # Sort by relevance
        products.sort(key=lambda p: p.relevance_score or 0, reverse=True)
        return products

    except Exception as e:
        logger.error(f"Semantic ranking failed: {e}")
        return products


def apply_hard_constraints(
    products: list[Product],
    requirements: SearchRequirements,
) -> list[Product]:
    """
    Apply deterministic hard constraints (budget, etc).
    This is CODE-based, not LLM-based.
    """
    filtered = []

    for product in products:
        # Budget max constraint
        if requirements.budget_max is not None and product.price is not None:
            if product.price > requirements.budget_max:
                logger.info(f"Filtered out '{product.name}' - price {product.price} > budget {requirements.budget_max}")
                continue

        # Budget min constraint
        if requirements.budget_min is not None and product.price is not None:
            if product.price < requirements.budget_min:
                logger.info(f"Filtered out '{product.name}' - price {product.price} < minimum {requirements.budget_min}")
                continue

        # Hard constraints from requirements
        passes = True
        for constraint_key, constraint_value in requirements.hard_constraints.items():
            prod_val = product.attributes.get(constraint_key)
            if prod_val is not None:
                # Simple string containment check
                if str(constraint_value).lower() not in str(prod_val).lower():
                    logger.info(f"Filtered '{product.name}' - constraint {constraint_key}: {constraint_value} not matched")
                    passes = False
                    break
            # If product doesn't have the attribute, don't filter it out (unknown != bad)

        if passes:
            filtered.append(product)

    return filtered


def rerank_products(
    products: list[Product],
    requirements: SearchRequirements,
    top_k: int = 5,
) -> list[Product]:
    """
    Final reranking combining semantic score with other signals.
    """
    for product in products:
        score = product.relevance_score or 0.0

        # Use completeness only as a tie-breaker; large bonuses can let a
        # detailed but irrelevant listing outrank a closer match.
        attr_count = len([v for v in product.attributes.values() if v])
        score += min(attr_count * 0.005, 0.025)

        # Small completeness bonuses should not outweigh query relevance.
        if product.price is not None:
            score += 0.01

        # A description adds useful context, but is not itself a match.
        if product.description:
            score += 0.01

        product.relevance_score = score

    products.sort(key=lambda p: p.relevance_score or 0, reverse=True)
    return products[:top_k]
