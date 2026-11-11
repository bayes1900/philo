"""
Vector API - pgvector operations for similarity search.

Provides schema-agnostic vector operations:
- Create tables with vector columns
- Insert vectors with metadata
- Similarity search (cosine, L2, inner product)
- Vector index management (HNSW, IVFFlat)
"""

from typing import Optional, List, Dict, Any, Union, Tuple
from datetime import datetime

from sqlalchemy import text


class VectorAPI:
    """
    API for pgvector operations.
    
    This class provides a schema-agnostic interface for vector similarity
    search using PostgreSQL's pgvector extension.
    
    Supported distance metrics:
    - cosine: Cosine distance (default, good for normalized vectors)
    - l2: Euclidean distance
    - inner_product: Negative inner product (for maximum inner product search)
    
    Example:
        # Create a vector table
        client.vectors.create_table(
            "document_embeddings",
            dimension=1536,
            metadata_columns={
                "title": "TEXT",
                "source": "TEXT",
                "created_at": "TIMESTAMPTZ DEFAULT NOW()"
            }
        )
        
        # Insert vectors
        client.vectors.insert("document_embeddings", {
            "id": "doc1",
            "embedding": [0.1, 0.2, ...],
            "title": "Document Title",
            "source": "web"
        })
        
        # Search similar vectors
        results = client.vectors.search(
            "document_embeddings",
            query_vector=[0.1, 0.2, ...],
            limit=10,
            distance_threshold=0.3
        )
        
        # Create index for better performance
        client.vectors.create_index("document_embeddings", index_type="hnsw")
    """
    
    def __init__(self, client):
        """
        Initialize VectorAPI.
        
        Args:
            client: DatabaseClient instance
        """
        self._client = client
    
    def create_table(
        self,
        table_name: str,
        dimension: int = 1536,
        id_column: str = "id",
        id_type: str = "SERIAL PRIMARY KEY",
        vector_column: str = "embedding",
        vector_type: str = "vector",
        metadata_columns: Optional[Dict[str, str]] = None,
        if_not_exists: bool = True,
    ) -> None:
        """
        Create a table with a vector column.
        
        Args:
            table_name: Name of the table to create
            dimension: Dimension of the vector column
            id_column: Name of the ID column
            id_type: Type of the ID column (e.g., "SERIAL PRIMARY KEY", "TEXT PRIMARY KEY")
            vector_column: Name of the vector column
            vector_type: Vector type - 'vector' (float32) or 'halfvec' (float16)
            metadata_columns: Additional columns as {column_name: column_definition}
                             e.g., {"title": "TEXT", "created_at": "TIMESTAMPTZ DEFAULT NOW()"}
            if_not_exists: Add IF NOT EXISTS clause
            
        Example:
            client.vectors.create_table(
                "embeddings",
                dimension=768,
                metadata_columns={
                    "content": "TEXT",
                    "metadata": "JSONB",
                    "created_at": "TIMESTAMPTZ DEFAULT NOW()"
                }
            )
            
            # Use halfvec for 50% storage savings
            client.vectors.create_table(
                "embeddings",
                dimension=768,
                vector_type="halfvec"
            )
        """
        self._validate_vector_type(vector_type)
        exists_clause = "IF NOT EXISTS" if if_not_exists else ""
        
        columns = [f"{id_column} {id_type}"]
        columns.append(f"{vector_column} {vector_type}({dimension})")
        
        if metadata_columns:
            for col_name, col_def in metadata_columns.items():
                columns.append(f"{col_name} {col_def}")
        
        sql = f"""
            CREATE TABLE {exists_clause} {table_name} (
                {', '.join(columns)}
            );
        """
        
        with self._client.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
    
    def insert(
        self,
        table_name: str,
        data: Dict[str, Any],
        vector_column: str = "embedding",
        vector_type: str = "vector",
        id_column: str = "id",
    ) -> Any:
        """
        Insert a single record with a vector.
        
        Args:
            table_name: Name of the table
            data: Dictionary containing the data, including the vector
                  The vector should be a list of floats
            vector_column: Name of the vector column
            vector_type: Vector type - 'vector' (float32) or 'halfvec' (float16)
            
        Returns:
            The inserted record's ID (if applicable)
            
        Example:
            client.vectors.insert("embeddings", {
                "embedding": [0.1, 0.2, 0.3, ...],
                "title": "Document Title",
                "metadata": {"source": "web"}
            })
        """
        self._validate_vector_type(vector_type)
        columns = []
        values = []
        params = {}
        
        for key, value in data.items():
            columns.append(key)
            if key == vector_column and isinstance(value, list):
                values.append(f"CAST(:{key} AS {vector_type})")
                params[key] = self._vector_to_string(value)
            else:
                values.append(f":{key}")
                params[key] = value
        
        sql = f"""
            INSERT INTO {table_name} ({', '.join(columns)})
            VALUES ({', '.join(values)})
            RETURNING {id_column};
        """
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            row = result.fetchone()
            return row[0] if row else None
    
    def insert_many(
        self,
        table_name: str,
        data_list: List[Dict[str, Any]],
        vector_column: str = "embedding",
        vector_type: str = "vector",
    ) -> int:
        """
        Insert multiple records with vectors.
        
        Args:
            table_name: Name of the table
            data_list: List of dictionaries containing the data
            vector_column: Name of the vector column
            vector_type: Vector type - 'vector' (float32) or 'halfvec' (float16)
            
        Returns:
            Number of records inserted
            
        Example:
            client.vectors.insert_many("embeddings", [
                {"embedding": [0.1, ...], "title": "Doc 1"},
                {"embedding": [0.2, ...], "title": "Doc 2"},
            ])
        """
        if not data_list:
            return 0
        
        self._validate_vector_type(vector_type)
        count = 0
        with self._client.session_scope() as session:
            for data in data_list:
                columns = []
                values = []
                params = {}
                
                for key, value in data.items():
                    columns.append(key)
                    if key == vector_column and isinstance(value, list):
                        values.append(f"CAST(:{key} AS {vector_type})")
                        params[key] = self._vector_to_string(value)
                    else:
                        values.append(f":{key}")
                        params[key] = value
                
                sql = f"""
                    INSERT INTO {table_name} ({', '.join(columns)})
                    VALUES ({', '.join(values)});
                """
                session.execute(text(sql), params)
                count += 1
        
        return count
    
    def search(
        self,
        table_name: str,
        query_vector: List[float],
        vector_column: str = "embedding",
        limit: int = 10,
        distance_threshold: Optional[float] = None,
        distance_metric: str = "cosine",
        vector_type: str = "vector",
        columns: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        order_by_distance: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Search for similar vectors.
        
        Args:
            table_name: Name of the table
            query_vector: Query vector (list of floats)
            vector_column: Name of the vector column
            limit: Maximum number of results
            distance_threshold: Maximum distance threshold (optional)
            distance_metric: Distance metric - 'cosine', 'l2', or 'inner_product'
            vector_type: Vector type - 'vector' (float32) or 'halfvec' (float16)
            columns: Columns to return (default: all columns)
            filters: Additional filters as {column: value}
            order_by_distance: Order results by distance (ascending)
            
        Returns:
            List of dictionaries containing the results with distance
            
        Example:
            results = client.vectors.search(
                "embeddings",
                query_vector=[0.1, 0.2, ...],
                limit=10,
                distance_threshold=0.3,
                filters={"category": "tech"}
            )
            for r in results:
                print(f"ID: {r['id']}, Distance: {r['distance']}")
        """
        self._validate_vector_type(vector_type)
        # Build distance operator
        distance_op = self._get_distance_operator(distance_metric)
        
        # Select columns
        if columns:
            select_cols = ", ".join(columns)
        else:
            select_cols = "*"
        
        vector_str = self._vector_to_string(query_vector)
        
        sql = f"""
            SELECT {select_cols}, 
                   {vector_column} {distance_op} CAST(:query_vector AS {vector_type}) AS distance
            FROM {table_name}
            WHERE {vector_column} IS NOT NULL
        """
        params = {"query_vector": vector_str}
        
        # Add filters
        if filters:
            for key, value in filters.items():
                sql += f" AND {key} = :filter_{key}"
                params[f"filter_{key}"] = value
        
        # Add distance threshold
        if distance_threshold is not None:
            sql += f" AND {vector_column} {distance_op} CAST(:query_vector AS {vector_type}) < :threshold"
            params["threshold"] = distance_threshold
        
        # Order by distance
        if order_by_distance:
            sql += f" ORDER BY distance ASC"
        
        sql += f" LIMIT :limit"
        params["limit"] = limit
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            rows = result.fetchall()
            
            # Convert to list of dicts
            results = []
            for row in rows:
                row_dict = dict(row._mapping)
                results.append(row_dict)
            
            return results
    
    def search_by_id(
        self,
        table_name: str,
        record_id: Any,
        vector_column: str = "embedding",
        id_column: str = "id",
        limit: int = 10,
        distance_metric: str = "cosine",
        vector_type: str = "vector",
        exclude_self: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Search for similar vectors by record ID.
        
        Uses the vector from an existing record to find similar records.
        
        Args:
            table_name: Name of the table
            record_id: ID of the record to use as query
            vector_column: Name of the vector column
            id_column: Name of the ID column
            limit: Maximum number of results
            distance_metric: Distance metric
            vector_type: Vector type - 'vector' (float32) or 'halfvec' (float16)
            exclude_self: Exclude the query record from results
            
        Returns:
            List of similar records with distances
        """
        self._validate_vector_type(vector_type)
        distance_op = self._get_distance_operator(distance_metric)
        
        sql = f"""
            SELECT t2.*, 
                   t1.{vector_column} {distance_op} t2.{vector_column} AS distance
            FROM {table_name} t1, {table_name} t2
            WHERE t1.{id_column} = :record_id
            AND t2.{vector_column} IS NOT NULL
        """
        params = {"record_id": record_id}
        
        if exclude_self:
            sql += f" AND t2.{id_column} != :record_id"
        
        sql += f" ORDER BY distance ASC LIMIT :limit"
        params["limit"] = limit
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            rows = result.fetchall()
            
            results = []
            for row in rows:
                row_dict = dict(row._mapping)
                results.append(row_dict)
            
            return results
    
    def create_index(
        self,
        table_name: str,
        vector_column: str = "embedding",
        index_type: str = "hnsw",
        distance_metric: str = "cosine",
        vector_type: str = "vector",
        index_name: Optional[str] = None,
        m: int = 16,
        ef_construction: int = 64,
        lists: int = 100,
    ) -> None:
        """
        Create a vector index for faster similarity search.
        
        Args:
            table_name: Name of the table
            vector_column: Name of the vector column
            index_type: Index type - 'hnsw' or 'ivfflat'
            distance_metric: Distance metric - 'cosine', 'l2', or 'inner_product'
            vector_type: Vector type - 'vector' (float32) or 'halfvec' (float16)
            index_name: Custom index name (default: auto-generated)
            m: HNSW parameter - number of connections per node (default: 16)
            ef_construction: HNSW parameter - size of dynamic candidate list (default: 64)
            lists: IVFFlat parameter - number of clusters (default: 100)
            
        Note:
            - HNSW: Better recall, slower build, more memory
            - IVFFlat: Faster build, less memory, requires clustering
            
        Example:
            # Create HNSW index (recommended for most cases)
            client.vectors.create_index("embeddings", index_type="hnsw")
            
            # Create IVFFlat index (for very large datasets)
            client.vectors.create_index("embeddings", index_type="ivfflat", lists=1000)
            
            # Create index for halfvec column
            client.vectors.create_index("embeddings", vector_type="halfvec")
        """
        self._validate_vector_type(vector_type)
        if index_name is None:
            index_name = f"idx_{table_name}_{vector_column}_{index_type}"
        
        ops = self._get_index_ops(distance_metric, vector_type)
        
        if index_type.lower() == "hnsw":
            sql = f"""
                CREATE INDEX IF NOT EXISTS {index_name}
                ON {table_name}
                USING hnsw ({vector_column} {ops})
                WITH (m = {m}, ef_construction = {ef_construction});
            """
        elif index_type.lower() == "ivfflat":
            sql = f"""
                CREATE INDEX IF NOT EXISTS {index_name}
                ON {table_name}
                USING ivfflat ({vector_column} {ops})
                WITH (lists = {lists});
            """
        else:
            raise ValueError(f"Unknown index type: {index_type}. Use 'hnsw' or 'ivfflat'.")
        
        with self._client.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
    
    def drop_index(self, index_name: str, if_exists: bool = True) -> None:
        """Drop a vector index."""
        exists_clause = "IF EXISTS" if if_exists else ""
        sql = f"DROP INDEX {exists_clause} {index_name};"
        
        with self._client.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
    
    def update(
        self,
        table_name: str,
        record_id: Any,
        data: Dict[str, Any],
        id_column: str = "id",
        vector_column: str = "embedding",
        vector_type: str = "vector",
    ) -> bool:
        """
        Update a record including its vector.
        
        Args:
            table_name: Name of the table
            record_id: ID of the record to update
            data: Dictionary of columns to update
            id_column: Name of the ID column
            vector_column: Name of the vector column
            vector_type: Vector type - 'vector' (float32) or 'halfvec' (float16)
            
        Returns:
            True if updated, False if not found
        """
        self._validate_vector_type(vector_type)
        set_clauses = []
        params = {"record_id": record_id}
        
        for key, value in data.items():
            if key == vector_column and isinstance(value, list):
                set_clauses.append(f"{key} = CAST(:{key} AS {vector_type})")
                params[key] = self._vector_to_string(value)
            else:
                set_clauses.append(f"{key} = :{key}")
                params[key] = value
        
        sql = f"""
            UPDATE {table_name}
            SET {', '.join(set_clauses)}
            WHERE {id_column} = :record_id;
        """
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            return result.rowcount > 0
    
    def delete(
        self,
        table_name: str,
        record_id: Any,
        id_column: str = "id",
    ) -> bool:
        """
        Delete a record by ID.
        
        Args:
            table_name: Name of the table
            record_id: ID of the record to delete
            id_column: Name of the ID column
            
        Returns:
            True if deleted, False if not found
        """
        sql = f"DELETE FROM {table_name} WHERE {id_column} = :record_id;"
        params = {"record_id": record_id}
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            return result.rowcount > 0
    
    def get_by_id(
        self,
        table_name: str,
        record_id: Any,
        id_column: str = "id",
        columns: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get a record by ID.
        
        Args:
            table_name: Name of the table
            record_id: ID of the record
            id_column: Name of the ID column
            columns: Columns to return (default: all)
            
        Returns:
            Dictionary containing the record, or None if not found
        """
        select_cols = ", ".join(columns) if columns else "*"
        
        sql = f"""
            SELECT {select_cols}
            FROM {table_name}
            WHERE {id_column} = :record_id;
        """
        params = {"record_id": record_id}
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            row = result.fetchone()
            
            if row:
                return dict(row._mapping)
            return None
    
    def count(
        self,
        table_name: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Count records in a table.
        
        Args:
            table_name: Name of the table
            filters: Optional filters as {column: value}
            
        Returns:
            Number of records
        """
        sql = f"SELECT COUNT(*) FROM {table_name}"
        params = {}
        
        if filters:
            where_clauses = []
            for key, value in filters.items():
                where_clauses.append(f"{key} = :{key}")
                params[key] = value
            sql += " WHERE " + " AND ".join(where_clauses)
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            return result.scalar()
    
    def get_vector_dimension(
        self,
        table_name: str,
        vector_column: str = "embedding",
    ) -> int:
        """
        Get the dimension of a vector column.
        
        Args:
            table_name: Name of the table
            vector_column: Name of the vector column
            
        Returns:
            Dimension of the vector column
        """
        sql = f"""
            SELECT a.atttypmod
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            WHERE c.relname = :table_name
            AND a.attname = :vector_column;
        """
        params = {"table_name": table_name, "vector_column": vector_column}
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            row = result.fetchone()
            if row:
                # atttypmod contains dimension info
                return row[0] if row[0] > 0 else 0
            return 0
    
    # ==================== Helper Methods ====================
    
    @staticmethod
    def _vector_to_string(vector: List[float]) -> str:
        """Convert a vector list to PostgreSQL vector format string."""
        return "[" + ",".join(str(v) for v in vector) + "]"
    
    @staticmethod
    def _string_to_vector(vector_str: str) -> List[float]:
        """Convert PostgreSQL vector format string to a list."""
        if not vector_str:
            return []
        clean = vector_str.strip("[]()")
        return [float(v) for v in clean.split(",")]
    
    @staticmethod
    def _get_distance_operator(metric: str) -> str:
        """Get the distance operator for a given metric."""
        operators = {
            "cosine": "<=>",      # cosine distance
            "l2": "<->",          # Euclidean distance
            "inner_product": "<#>",  # negative inner product
        }
        if metric not in operators:
            raise ValueError(f"Unknown distance metric: {metric}. Use 'cosine', 'l2', or 'inner_product'.")
        return operators[metric]
    
    @staticmethod
    def _validate_vector_type(vector_type: str) -> None:
        """Validate the vector type."""
        valid_types = {"vector", "halfvec"}
        if vector_type not in valid_types:
            raise ValueError(f"Unknown vector type: {vector_type}. Use 'vector' or 'halfvec'.")
    
    @staticmethod
    def _get_index_ops(metric: str, vector_type: str = "vector") -> str:
        """Get the index operator class for a given metric and vector type."""
        ops = {
            "vector": {
                "cosine": "vector_cosine_ops",
                "l2": "vector_l2_ops",
                "inner_product": "vector_ip_ops",
            },
            "halfvec": {
                "cosine": "halfvec_cosine_ops",
                "l2": "halfvec_l2_ops",
                "inner_product": "halfvec_ip_ops",
            },
        }
        if vector_type not in ops:
            raise ValueError(f"Unknown vector type: {vector_type}. Use 'vector' or 'halfvec'.")
        if metric not in ops[vector_type]:
            raise ValueError(f"Unknown distance metric: {metric}. Use 'cosine', 'l2', or 'inner_product'.")
        return ops[vector_type][metric]
