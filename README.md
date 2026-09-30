# AI Shopping Agent

An AI-powered shopping assistant that accepts natural language queries, searches the web for products, extracts and compares them, and returns personalized recommendations with source links.

## Architecture

```
USER QUERY
    ↓
LLM QUERY UNDERSTANDING  (Groq/Gemini)
    ↓
Structured Requirements  (Pydantic-validated)
    ↓
WEB SEARCH TOOL          (DuckDuckGo)
    ↓
Candidate URLs
    ↓
PRODUCT EXTRACTION TOOL  (httpx + BeautifulSoup)
    ↓
Canonical Product objects (JSON-LD / OpenGraph / meta / text fallback)
    ↓
SEMANTIC RETRIEVAL       (TF-IDF cosine similarity)
    ↓
HARD CONSTRAINT FILTER   (Deterministic: budget, specs)
    ↓
RERANKING                (Multi-signal scoring)
    ↓
LLM RECOMMENDATION       (Groq/Gemini)
    ↓
RESULTS + SOURCE LINKS
    ↓
SQLite DATABASE
```

## Agentic Workflow

The system uses an explicit tool-calling architecture:

1. **`tool_web_search(query)`** – Searches DuckDuckGo for products. Runs up to 2 queries (semantic + budget-qualified).
2. **`tool_extract_products(urls, category)`** – Fetches each URL and extracts product info using JSON-LD structured data, OpenGraph meta tags, or page text. Falls back to search snippet data if pages are blocked.
3. **`tool_compare_products(products, requirements)`** – Performs semantic ranking (TF-IDF cosine similarity), applies deterministic hard constraints (budget filtering), and reranks.

The agent orchestrates these tools in a bounded loop (max 2 searches, max 12 product extractions).

### Key Design Principles

- **LLM for ambiguity** (understanding "good for AI development") — **Code for facts** (enforcing ₹70,000 max)
- Missing product attributes = unknown, NOT zero/false
- Every product retains source URL and provenance
- Scraped content is treated as untrusted data

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python, FastAPI |
| Database | SQLite + SQLAlchemy |
| LLM | Groq (Llama 3.3 70B) or Gemini 2.5 Flash |
| Web Search | DuckDuckGo (duckduckgo-search library) |
| Extraction | httpx + BeautifulSoup4 |
| Similarity | scikit-learn TF-IDF (or pure Python fallback) |
| Frontend | Vanilla HTML/CSS/JS |

## Data Model

Products use a **generic schema** with JSON attributes — works for laptops, phones, books, shoes, headphones, or any category:

```python
Product:
    name, category, price, currency, description,
    attributes: dict,   # {"cpu": "...", "ram": "..."} or {"author": "...", "pages": "..."}
    source_url, source_name, retrieved_at
```

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API keys

Copy `.env.example` to `.env` and add at least one LLM API key:

```bash
cp .env.example .env
# Edit .env with your GROQ_API_KEY or GEMINI_API_KEY
```

### 3. Run the server

```bash
python -m app.main
```

Or:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Open the app

Navigate to [http://localhost:8000](http://localhost:8000)

## API

### `POST /api/search`

```json
{
    "query": "Find the best laptop for AI development under ₹70,000"
}
```

Returns: `{ query, requirements, products, recommendation, activity }`

### `GET /api/history`

Returns recent search history.

### `GET /api/search/{id}`

Returns details of a previous search.

## Project Structure

```
app/
    main.py              # FastAPI application
    models.py            # SQLAlchemy models
    schemas.py           # Pydantic schemas
    database.py          # Database setup

    agent/
        agent.py         # Shopping agent orchestrator
        tools.py         # Explicit tool functions

    search/
        web_search.py    # DuckDuckGo web search
        extractor.py     # Product extraction from pages

    retrieval/
        ranking.py       # Semantic ranking + hard constraints

    llm/
        client.py        # Groq/Gemini LLM client

    static/
        index.html       # Frontend
        style.css        # Styling
        app.js           # Frontend logic
```

## Known Limitations

- Web scraping may be blocked by some e-commerce sites (fallback to search snippets)
- No streaming — the full pipeline runs server-side before returning results
- TF-IDF similarity is a lexical approximation (not true semantic embeddings)
- Price extraction uses regex patterns and may miss uncommon formats
- DuckDuckGo rate limits may apply with frequent searches
