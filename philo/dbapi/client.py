"""
Database Client - Main entry point for the generic database API.

Provides a unified interface for:
- Vector operations (pgvector)
- Time-series operations (TimescaleDB)
- Document operations (generic JSONB storage)
- Raw query execution
"""

import os
from typing import Optional, Union
from contextlib import contextmanager

from sqlalchemy import create_engine, Engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv

from .vector import VectorAPI
from .timeseries import TimeSeriesAPI
from .document import DocumentAPI
from .query import QueryAPI

load_dotenv()


class DatabaseClient:
    """
    Generic database client for PostgreSQL with pgvector and TimescaleDB.

    This client provides a schema-agnostic API that allows you to work with
    any table structure while leveraging the power of pgvector for similarity
    search and TimescaleDB for time-series data.

    Features:
    - Dynamic table creation without predefined schemas
    - Vector similarity search with pgvector
    - Time-series operations with TimescaleDB hypertables
    - JSONB document storage and querying
    - Connection pooling and session management

    Example:
        # Initialize with connection string
        client = DatabaseClient("postgresql://user:pass@localhost:5432/mydb")

        # Or use environment variable DATABASE_URL
        client = DatabaseClient()

        # Initialize extensions
        client.initialize()

        # Use vector operations
        client.vectors.create_table("embeddings", dimension=1536)
        client.vectors.insert("embeddings", {
            "id": "doc1",
            "embedding": [0.1, 0.2, ...],
            "metadata": {"source": "web"}
        })
        similar = client.vectors.search("embeddings", query_vec, limit=5)

        # Use time-series operations
        client.timeseries.create_hypertable("metrics", time_column="timestamp")
        client.timeseries.insert("metrics", {
            "timestamp": datetime.now(),
            "metric_name": "cpu_usage",
            "value": 75.5
        })
        data = client.timeseries.query_range("metrics", start_time, end_time)

        # Use document operations
        client.documents.insert("articles", {
            "title": "News Title",
            "content": "...",
            "tags": ["tech", "ai"]
        })
        articles = client.documents.find("articles", {"tags": "tech"})
    """

    def __init__(
        self,
        database_url: Optional[str] = None,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_pre_ping: bool = True,
        echo: bool = False,
    ):
        """
        Initialize the database client.

        Args:
            database_url: PostgreSQL connection string. If not provided,
                         uses DATABASE_URL environment variable.
            pool_size: Connection pool size
            max_overflow: Maximum overflow connections
            pool_pre_ping: Enable connection health checks
            echo: Echo SQL statements for debugging
        """
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/postgres"
        )

        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker] = None
        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._pool_pre_ping = pool_pre_ping
        self._echo = echo or os.getenv("SQL_ECHO", "").strip().lower() in ("1", "true", "yes", "on")

        # Lazy-loaded API instances
        self._vectors: Optional[VectorAPI] = None
        self._timeseries: Optional[TimeSeriesAPI] = None
        self._documents: Optional[DocumentAPI] = None
        self._query: Optional[QueryAPI] = None

    @property
    def engine(self) -> Engine:
        """Get or create the database engine."""
        if self._engine is None:
            self._engine = create_engine(
                self.database_url,
                pool_size=self._pool_size,
                max_overflow=self._max_overflow,
                pool_pre_ping=self._pool_pre_ping,
                echo=self._echo,
            )
        return self._engine

    @property
    def session_factory(self) -> sessionmaker:
        """Get or create the session factory."""
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                bind=self.engine,
                autocommit=False,
                autoflush=False,
            )
        return self._session_factory

    def get_session(self) -> Session:
        """Get a new database session."""
        return self.session_factory()

    @contextmanager
    def session_scope(self):
        """
        Provide a transactional scope around a series of operations.

        Usage:
            with client.session_scope() as session:
                # Perform database operations
                session.execute(text("INSERT INTO ..."))
        """
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @property
    def vectors(self) -> VectorAPI:
        """Access vector operations API (pgvector)."""
        if self._vectors is None:
            self._vectors = VectorAPI(self)
        return self._vectors

    @property
    def timeseries(self) -> TimeSeriesAPI:
        """Access time-series operations API (TimescaleDB)."""
        if self._timeseries is None:
            self._timeseries = TimeSeriesAPI(self)
        return self._timeseries

    @property
    def documents(self) -> DocumentAPI:
        """Access document operations API (JSONB storage)."""
        if self._documents is None:
            self._documents = DocumentAPI(self)
        return self._documents

    @property
    def query(self) -> QueryAPI:
        """Access raw query API."""
        if self._query is None:
            self._query = QueryAPI(self)
        return self._query

    def initialize(self, extensions: Optional[list] = None) -> None:
        """
        Initialize database extensions.

        Args:
            extensions: List of extensions to enable.
                       Default: ['vector', 'timescaledb']
        """
        if extensions is None:
            extensions = ['vector', 'timescaledb']

        with self.engine.connect() as conn:
            for ext in extensions:
                try:
                    if ext == 'vector':
                        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                        conn.commit()
                        print("pgvector extension enabled.")
                    elif ext == 'timescaledb':
                        conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"))
                        conn.commit()
                        print("TimescaleDB extension enabled.")
                    else:
                        conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext};"))
                        conn.commit()
                        print(f"Extension '{ext}' enabled.")
                except SQLAlchemyError as e:
                    print(f"Warning: Could not enable extension '{ext}': {e}")

    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        with self.engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = :table_name
                    );
                """),
                {"table_name": table_name}
            )
            return result.scalar()

    def drop_table(self, table_name: str, if_exists: bool = True) -> None:
        """
        Drop a table from the database.

        Args:
            table_name: Name of the table to drop
            if_exists: Add IF EXISTS clause to prevent errors
        """
        if_exists_clause = "IF EXISTS" if if_exists else ""
        with self.engine.connect() as conn:
            conn.execute(text(f"DROP TABLE {if_exists_clause} {table_name};"))
            conn.commit()

    def execute(self, sql: str, params: Optional[dict] = None) -> list:
        """
        Execute raw SQL and return results.

        Args:
            sql: SQL statement to execute
            params: Parameters for the SQL statement

        Returns:
            List of result rows
        """
        with self.session_scope() as session:
            result = session.execute(text(sql), params or {})
            return result.fetchall()

    def execute_many(self, sql: str, params_list: list) -> int:
        """
        Execute raw SQL with multiple parameter sets.

        Args:
            sql: SQL statement to execute
            params_list: List of parameter dictionaries

        Returns:
            Number of rows affected
        """
        with self.session_scope() as session:
            result = session.execute(text(sql), params_list)
            return result.rowcount

    def close(self) -> None:
        """Close all connections and cleanup."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None
            self._vectors = None
            self._timeseries = None
            self._documents = None
            self._query = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def __repr__(self) -> str:
        return f"<DatabaseClient(url='{self.database_url.split('@')[-1] if '@' in self.database_url else self.database_url}')>"