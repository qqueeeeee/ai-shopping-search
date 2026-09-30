"""Pydantic schemas for request/response validation."""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class SearchRequirements(BaseModel):
    """Structured requirements extracted from natural language query."""
    category: str = Field(description="Product category (e.g., laptop, phone, book, shoes)")
    query: str = Field(description="Refined search query for web search")
    budget_min: Optional[float] = Field(None, description="Minimum budget")
    budget_max: Optional[float] = Field(None, description="Maximum budget")
    currency: str = Field(default="INR", description="Currency code (always INR)")
    hard_constraints: dict = Field(default_factory=dict, description="Must-have constraints")
    preferences: dict = Field(default_factory=dict, description="Nice-to-have preferences")


class Product(BaseModel):
    """Generic product representation."""
    name: str
    category: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    description: Optional[str] = None
    attributes: dict = Field(default_factory=dict)
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    relevance_score: Optional[float] = None
    match_reason: Optional[str] = None


class SearchRequest(BaseModel):
    """API search request."""
    query: str


class ActivityEvent(BaseModel):
    """An activity event in the agent pipeline."""
    step: str
    status: str  # "running", "done", "error"
    detail: Optional[str] = None


class SearchResponse(BaseModel):
    """API search response."""
    query: str
    requirements: Optional[SearchRequirements] = None
    products: list[Product] = []
    recommendation: Optional[str] = None
    activity: list[ActivityEvent] = []


class SearchHistoryItem(BaseModel):
    """Search history entry."""
    id: int
    query: str
    num_results: int
    created_at: datetime

    class Config:
        from_attributes = True
