"""SQLAlchemy models."""
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


class Search(Base):
    __tablename__ = "searches"

    id = Column(Integer, primary_key=True, index=True)
    query = Column(Text, nullable=False)
    requirements_json = Column(JSON, nullable=True)
    recommendation = Column(Text, nullable=True)
    activity_log = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    results = relationship("SearchResult", back_populates="search", cascade="all, delete-orphan")


class SearchResult(Base):
    __tablename__ = "search_results"

    id = Column(Integer, primary_key=True, index=True)
    search_id = Column(Integer, ForeignKey("searches.id"), nullable=False)
    name = Column(String(500), nullable=False)
    category = Column(String(100), nullable=True)
    price = Column(Float, nullable=True)
    currency = Column(String(10), nullable=True)
    description = Column(Text, nullable=True)
    attributes = Column(JSON, nullable=True)
    source_url = Column(String(1000), nullable=True)
    source_name = Column(String(200), nullable=True)
    relevance_score = Column(Float, nullable=True)
    match_reason = Column(Text, nullable=True)
    rank = Column(Integer, nullable=True)
    retrieved_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    search = relationship("Search", back_populates="results")
