"""
Generic Database API for PostgreSQL with pgvector and TimescaleDB support.

This module provides a schema-agnostic API layer that preserves:
- pgvector: Vector similarity search operations
- TimescaleDB: Time-series data operations with hypertables

Usage:
    from searanch.database.api import DatabaseClient

    # Initialize client
    client = DatabaseClient(database_url="postgresql://...")

    # Vector operations
    client.vectors.create_table("embeddings", dimension=1536)
    client.vectors.insert("embeddings", {"id": 1, "embedding": [0.1, 0.2, ...]})
    results = client.vectors.search("embeddings", query_vector, limit=10)

    # Time-series operations
    client.timeseries.create_hypertable("sensor_data", time_column="timestamp")
    client.timeseries.insert("sensor_data", {"timestamp": now(), "value": 42.0})
    data = client.timeseries.query_range("sensor_data", start, end)

    # Generic document operations
    client.documents.insert("articles", {"title": "...", "content": "..."})
    docs = client.documents.find("articles", {"category": "tech"})
"""

from .client import DatabaseClient
from .vector import VectorAPI
from .timeseries import TimeSeriesAPI
from .document import DocumentAPI
from .query import QueryAPI

__all__ = [
    "DatabaseClient",
    "VectorAPI",
    "TimeSeriesAPI",
    "DocumentAPI",
    "QueryAPI",
]