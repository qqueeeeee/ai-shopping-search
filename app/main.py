"""FastAPI main application."""
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import init_db, get_db
from app.models import Search, SearchResult
from app.schemas import SearchRequest, SearchResponse, SearchHistoryItem
from app.agent.agent import ShoppingAgent

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    init_db()
    logger.info("Database initialized")
    yield


app = FastAPI(
    title="AI Shopping Agent",
    description="An AI-powered shopping assistant that finds and recommends products",
    version="1.0.0",
    lifespan=lifespan,
)

# Serve static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    """Serve the frontend."""
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.post("/api/search", response_model=SearchResponse)
async def search_products(request: SearchRequest, db: Session = Depends(get_db)):
    """
    Main search endpoint.
    Accepts a natural language shopping query and returns product recommendations.
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    logger.info(f"Search request: {request.query}")

    # Run the agent pipeline
    agent = ShoppingAgent()
    response = await agent.run(request.query)

    # Save to database
    try:
        search = Search(
            query=request.query,
            requirements_json=response.requirements.model_dump() if response.requirements else None,
            recommendation=response.recommendation,
            activity_log=[a.model_dump() for a in response.activity],
        )
        db.add(search)
        db.flush()

        for i, product in enumerate(response.products):
            result = SearchResult(
                search_id=search.id,
                name=product.name,
                category=product.category,
                price=product.price,
                currency=product.currency,
                description=product.description,
                attributes=product.attributes,
                source_url=product.source_url,
                source_name=product.source_name,
                relevance_score=product.relevance_score,
                match_reason=product.match_reason,
                rank=i + 1,
            )
            db.add(result)

        db.commit()
        logger.info(f"Saved search #{search.id} with {len(response.products)} results")
    except Exception as e:
        logger.error(f"Failed to save search to database: {e}")
        db.rollback()

    return response


@app.get("/api/history")
async def get_history(db: Session = Depends(get_db)):
    """Get recent search history."""
    searches = db.query(Search).order_by(Search.created_at.desc()).limit(20).all()
    history = []
    for s in searches:
        history.append({
            "id": s.id,
            "query": s.query,
            "num_results": len(s.results),
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })
    return history


@app.get("/api/search/{search_id}")
async def get_search_detail(search_id: int, db: Session = Depends(get_db)):
    """Get details of a previous search."""
    search = db.query(Search).filter(Search.id == search_id).first()
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")

    results = []
    for r in search.results:
        results.append({
            "name": r.name,
            "category": r.category,
            "price": r.price,
            "currency": r.currency,
            "description": r.description,
            "attributes": r.attributes,
            "source_url": r.source_url,
            "source_name": r.source_name,
            "relevance_score": r.relevance_score,
            "match_reason": r.match_reason,
            "rank": r.rank,
        })

    return {
        "id": search.id,
        "query": search.query,
        "requirements": search.requirements_json,
        "recommendation": search.recommendation,
        "activity": search.activity_log,
        "products": results,
        "created_at": search.created_at.isoformat() if search.created_at else None,
    }


if __name__ == "__main__":
    import socket
    import uvicorn

    host = "0.0.0.0"
    port = int(os.getenv("PORT", "8000"))
    requested_port = port
    while port < requested_port + 20:
        with socket.socket() as probe:
            try:
                probe.bind((host, port))
                break
            except OSError:
                port += 1
    else:
        raise RuntimeError(f"No free port found between {requested_port} and {port - 1}")

    if port != requested_port:
        logger.warning("Port %s is already in use; starting on port %s instead", requested_port, port)
    uvicorn.run("app.main:app", host=host, port=port, reload=True)
