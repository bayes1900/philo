"""
Document API - Generic JSONB document storage operations.

Provides schema-agnostic document operations:
- Create tables with JSONB columns
- Insert and query JSON documents
- JSONB path queries
- Full-text search on JSON fields
"""

from typing import Optional, List, Dict, Any, Union
from datetime import datetime
import json
import re

from sqlalchemy import text


def _make_safe_param_name(key: str, prefix: str = "") -> str:
    """
    Generate a safe parameter name from a JSONB path key.
    
    Args:
        key: The JSONB path key (e.g., "data->>'category'")
        prefix: Optional prefix for the parameter name
        
    Returns:
        A safe parameter name for SQL queries
    """
    # Replace JSONB operators with readable names
    safe_name = key.replace("->>", "_text_").replace("->", "_json_")
    # Remove single quotes
    safe_name = safe_name.replace("'", "")
    return f"{prefix}{safe_name}" if prefix else safe_name


class DocumentAPI:
    """
    API for generic document storage using PostgreSQL JSONB.
    
    This class provides a schema-agnostic interface for storing and
    querying JSON documents in PostgreSQL.
    
    Features:
    - Dynamic schema creation with JSONB columns
    - JSONB path queries and operators
    - Full-text search on document fields
    - Bulk insert and update operations
    - Index creation for JSONB fields
    
    Example:
        # Create a document table
        client.documents.create_table(
            "articles",
            additional_columns={
                "title": "TEXT",
                "created_at": "TIMESTAMPTZ DEFAULT NOW()"
            }
        )
        
        # Insert documents
        client.documents.insert("articles", {
            "title": "News Article",
            "data": {"category": "tech", "tags": ["ai", "ml"]},
            "author": "John"
        })
        
        # Query documents
        articles = client.documents.find("articles", {
            "data->>'category'": "tech"
        })
        
        # Full-text search
        results = client.documents.search("articles", "machine learning", "title")
    """
    
    def __init__(self, client):
        """
        Initialize DocumentAPI.
        
        Args:
            client: DatabaseClient instance
        """
        self._client = client
    
    def create_table(
        self,
        table_name: str,
        id_column: str = "id",
        id_type: str = "SERIAL PRIMARY KEY",
        document_column: str = "data",
        additional_columns: Optional[Dict[str, str]] = None,
        if_not_exists: bool = True,
    ) -> None:
        """
        Create a table for storing JSON documents.
        
        Args:
            table_name: Name of the table to create
            id_column: Name of the ID column
            id_type: Type of the ID column
            document_column: Name of the JSONB column for document storage
            additional_columns: Additional columns as {column_name: column_definition}
            if_not_exists: Add IF NOT EXISTS clause
            
        Example:
            client.documents.create_table(
                "articles",
                additional_columns={
                    "title": "TEXT",
                    "author": "TEXT",
                    "created_at": "TIMESTAMPTZ DEFAULT NOW()"
                }
            )
        """
        exists_clause = "IF NOT EXISTS" if if_not_exists else ""
        
        columns = [f"{id_column} {id_type}"]
        columns.append(f"{document_column} JSONB DEFAULT '{{}}'")
        
        if additional_columns:
            for col_name, col_def in additional_columns.items():
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
        document: Dict[str, Any],
        document_column: str = "data",
        additional_data: Optional[Dict[str, Any]] = None,
        id_column: str = "id",
    ) -> Any:
        """
        Insert a single document.
        
        Args:
            table_name: Name of the table
            document: The JSON document to insert
            document_column: Name of the JSONB column
            additional_data: Additional columns to populate
            
        Returns:
            The inserted record's ID
            
        Example:
            client.documents.insert("articles", {
                "category": "tech",
                "tags": ["ai", "ml"],
                "views": 100
            }, additional_data={"title": "Article Title"})
        """
        columns = [document_column]
        values = [f":{document_column}::jsonb"]
        params = {document_column: json.dumps(document)}
        
        if additional_data:
            for key, value in additional_data.items():
                columns.append(key)
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
        documents: List[Dict[str, Any]],
        document_column: str = "data",
        additional_data_list: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """
        Insert multiple documents.
        
        Args:
            table_name: Name of the table
            documents: List of JSON documents to insert
            document_column: Name of the JSONB column
            additional_data_list: List of additional column data
            
        Returns:
            Number of documents inserted
        """
        if not documents:
            return 0
        
        count = 0
        with self._client.session_scope() as session:
            for i, doc in enumerate(documents):
                columns = [document_column]
                values = [f":{document_column}::jsonb"]
                params = {document_column: json.dumps(doc)}
                
                if additional_data_list and i < len(additional_data_list):
                    for key, value in additional_data_list[i].items():
                        columns.append(key)
                        values.append(f":{key}")
                        params[key] = value
                
                sql = f"""
                    INSERT INTO {table_name} ({', '.join(columns)})
                    VALUES ({', '.join(values)});
                """
                session.execute(text(sql), params)
                count += 1
        
        return count
    
    def find(
        self,
        table_name: str,
        filters: Optional[Dict[str, Any]] = None,
        columns: Optional[List[str]] = None,
        order_by: Optional[str] = None,
        order_dir: str = "ASC",
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Find documents matching filters.
        
        Args:
            table_name: Name of the table
            filters: Filters as {column_or_path: value}
                    For JSONB paths, use: "data->>'field'" for text comparison
                    or "data->'field'" for JSON comparison
            columns: Columns to return (default: all)
            order_by: Column to order by
            order_dir: Order direction - 'ASC' or 'DESC'
            limit: Maximum number of results
            offset: Number of results to skip
            
        Returns:
            List of matching documents
            
        Example:
            # Simple filter
            docs = client.documents.find("articles", {"author": "John"})
            
            # JSONB path filter
            docs = client.documents.find("articles", {
                "data->>'category'": "tech"
            })
            
            # Array contains
            docs = client.documents.find("articles", {
                "data->'tags'": ["ai"]  # tags contains "ai"
            })
        """
        select_cols = ", ".join(columns) if columns else "*"
        
        sql = f"SELECT {select_cols} FROM {table_name}"
        params = {}
        
        if filters:
            where_clauses = []
            for key, value in filters.items():
                # Generate a safe parameter name
                param_name = _make_safe_param_name(key)
                
                if "->>" in key:
                    # ->> returns TEXT, use equality comparison
                    where_clauses.append(f"{key} = :{param_name}")
                    params[param_name] = value
                elif "->" in key:
                    # -> returns JSONB, can use @> operator for contains
                    if isinstance(value, (list, dict)):
                        # JSONB contains query - need ::jsonb cast
                        where_clauses.append(f"{key} @> :{param_name}::jsonb")
                        params[param_name] = json.dumps(value)
                    else:
                        # For scalar values, compare as text using ->>
                        # Convert -> to ->> for text comparison
                        text_key = key.replace("->", "->>", 1) if "->>" not in key else key
                        where_clauses.append(f"{text_key} = :{param_name}")
                        params[param_name] = value
                else:
                    where_clauses.append(f"{key} = :{key}")
                    params[key] = value
            sql += " WHERE " + " AND ".join(where_clauses)
        
        if order_by:
            sql += f" ORDER BY {order_by} {order_dir}"
        
        if limit:
            sql += f" LIMIT :limit"
            params["limit"] = limit
        
        if offset:
            sql += f" OFFSET :offset"
            params["offset"] = offset
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            rows = result.fetchall()
            
            return [dict(row._mapping) for row in rows]
    
    def find_one(
        self,
        table_name: str,
        filters: Optional[Dict[str, Any]] = None,
        columns: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Find a single document matching filters.
        
        Args:
            table_name: Name of the table
            filters: Filters as {column_or_path: value}
            columns: Columns to return
            
        Returns:
            Matching document or None
        """
        results = self.find(table_name, filters, columns, limit=1)
        return results[0] if results else None
    
    def find_by_id(
        self,
        table_name: str,
        record_id: Any,
        id_column: str = "id",
        columns: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Find a document by ID.
        
        Args:
            table_name: Name of the table
            record_id: ID of the record
            id_column: Name of the ID column
            columns: Columns to return
            
        Returns:
            Document dictionary or None
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
    
    def update(
        self,
        table_name: str,
        record_id: Any,
        updates: Dict[str, Any],
        id_column: str = "id",
        document_column: str = "data",
        merge_document: bool = True,
    ) -> bool:
        """
        Update a document.
        
        Args:
            table_name: Name of the table
            record_id: ID of the record to update
            updates: Dictionary of updates
            id_column: Name of the ID column
            document_column: Name of the JSONB column
            merge_document: If True, merge with existing document; if False, replace
            
        Returns:
            True if updated, False if not found
            
        Example:
            # Merge update (default)
            client.documents.update("articles", 1, {
                "data": {"views": 200, "new_field": "value"}
            })
            # Result: existing data merged with new fields
            
            # Replace update
            client.documents.update("articles", 1, {
                "data": {"views": 200}
            }, merge_document=False)
            # Result: data is replaced entirely
        """
        set_clauses = []
        params = {"record_id": record_id}
        
        for key, value in updates.items():
            if key == document_column and isinstance(value, dict):
                if merge_document:
                    set_clauses.append(f"{document_column} = {document_column} || :{document_column}::jsonb")
                else:
                    set_clauses.append(f"{document_column} = :{document_column}::jsonb")
                params[document_column] = json.dumps(value)
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
    
    def update_many(
        self,
        table_name: str,
        filters: Dict[str, Any],
        updates: Dict[str, Any],
        document_column: str = "data",
        merge_document: bool = True,
    ) -> int:
        """
        Update multiple documents matching filters.
        
        Args:
            table_name: Name of the table
            filters: Filters to match documents
            updates: Dictionary of updates
            document_column: Name of the JSONB column
            merge_document: If True, merge with existing document
            
        Returns:
            Number of documents updated
        """
        set_clauses = []
        params = {}
        
        for key, value in updates.items():
            if key == document_column and isinstance(value, dict):
                if merge_document:
                    set_clauses.append(f"{document_column} = {document_column} || :{document_column}::jsonb")
                else:
                    set_clauses.append(f"{document_column} = :{document_column}::jsonb")
                params[document_column] = json.dumps(value)
            else:
                set_clauses.append(f"{key} = :{key}")
                params[key] = value
        
        sql = f"UPDATE {table_name} SET {', '.join(set_clauses)}"
        
        if filters:
            where_clauses = []
            for key, value in filters.items():
                param_name = _make_safe_param_name(key, "filter_")
                
                if "->>" in key:
                    where_clauses.append(f"{key} = :{param_name}")
                    params[param_name] = value
                elif "->" in key:
                    if isinstance(value, (list, dict)):
                        where_clauses.append(f"{key} @> :{param_name}::jsonb")
                        params[param_name] = json.dumps(value)
                    else:
                        text_key = key.replace("->", "->>", 1) if "->>" not in key else key
                        where_clauses.append(f"{text_key} = :{param_name}")
                        params[param_name] = value
                else:
                    where_clauses.append(f"{key} = :{param_name}")
                    params[param_name] = value
            sql += " WHERE " + " AND ".join(where_clauses)
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            return result.rowcount
    
    def delete(
        self,
        table_name: str,
        record_id: Any,
        id_column: str = "id",
    ) -> bool:
        """
        Delete a document by ID.
        
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
    
    def delete_many(
        self,
        table_name: str,
        filters: Dict[str, Any],
    ) -> int:
        """
        Delete multiple documents matching filters.
        
        Args:
            table_name: Name of the table
            filters: Filters to match documents
            
        Returns:
            Number of documents deleted
        """
        sql = f"DELETE FROM {table_name}"
        params = {}
        
        if filters:
            where_clauses = []
            for key, value in filters.items():
                param_name = _make_safe_param_name(key, "filter_")
                
                if "->>" in key:
                    where_clauses.append(f"{key} = :{param_name}")
                    params[param_name] = value
                elif "->" in key:
                    if isinstance(value, (list, dict)):
                        where_clauses.append(f"{key} @> :{param_name}::jsonb")
                        params[param_name] = json.dumps(value)
                    else:
                        text_key = key.replace("->", "->>", 1) if "->>" not in key else key
                        where_clauses.append(f"{text_key} = :{param_name}")
                        params[param_name] = value
                else:
                    where_clauses.append(f"{key} = :{param_name}")
                    params[param_name] = value
            sql += " WHERE " + " AND ".join(where_clauses)
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            return result.rowcount
    
    def search(
        self,
        table_name: str,
        query: str,
        columns: Union[str, List[str]],
        language: str = "english",
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Full-text search on document columns.
        
        Args:
            table_name: Name of the table
            query: Search query
            columns: Column(s) to search in (can be string or list)
            language: Text search language
            limit: Maximum number of results
            
        Returns:
            List of matching documents with search rank
            
        Example:
            results = client.documents.search(
                "articles",
                "machine learning",
                columns=["title", "data->>'content'"]
            )
        """
        if isinstance(columns, str):
            columns = [columns]
        
        # Build tsvector expression
        tsvector_parts = [f"to_tsvector('{language}', {col})" for col in columns]
        tsvector_expr = " || ".join(tsvector_parts)
        
        sql = f"""
            SELECT *, ts_rank({tsvector_expr}, query) as rank
            FROM {table_name}, to_tsquery('{language}', :query) query
            WHERE {tsvector_expr} @@ query
            ORDER BY rank DESC
            LIMIT :limit;
        """
        params = {"query": query, "limit": limit}
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            rows = result.fetchall()
            
            return [dict(row._mapping) for row in rows]
    
    def create_search_index(
        self,
        table_name: str,
        columns: Union[str, List[str]],
        index_name: Optional[str] = None,
        language: str = "english",
    ) -> None:
        """
        Create a full-text search index.
        
        Args:
            table_name: Name of the table
            columns: Column(s) to index
            index_name: Custom index name
            language: Text search language
        """
        if isinstance(columns, str):
            columns = [columns]
        
        if index_name is None:
            index_name = f"idx_{table_name}_search"
        
        tsvector_parts = [f"to_tsvector('{language}', {col})" for col in columns]
        tsvector_expr = " || ".join(tsvector_parts)
        
        sql = f"""
            CREATE INDEX IF NOT EXISTS {index_name}
            ON {table_name}
            USING GIN ({tsvector_expr});
        """
        
        with self._client.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
    
    def create_jsonb_index(
        self,
        table_name: str,
        jsonb_path: str,
        index_name: Optional[str] = None,
        index_type: str = "gin",
    ) -> None:
        """
        Create an index on a JSONB field.
        
        Args:
            table_name: Name of the table
            jsonb_path: JSONB path to index (e.g., "data->'tags'")
            index_name: Custom index name
            index_type: Index type - 'gin' or 'btree'
            
        Example:
            # GIN index for contains queries
            client.documents.create_jsonb_index("articles", "data->'tags'")
            
            # B-tree index for scalar values
            client.documents.create_jsonb_index("articles", "data->>'category'", index_type="btree")
        """
        if index_name is None:
            safe_path = jsonb_path.replace("->", "_").replace(">", "").replace("'", "")
            index_name = f"idx_{table_name}_{safe_path}"
        
        sql = f"""
            CREATE INDEX IF NOT EXISTS {index_name}
            ON {table_name}
            USING {index_type} ({jsonb_path});
        """
        
        with self._client.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
    
    def query_jsonb(
        self,
        table_name: str,
        jsonb_path: str,
        query_type: str = "contains",
        value: Any = None,
        document_column: str = "data",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Advanced JSONB query.
        
        Args:
            table_name: Name of the table
            jsonb_path: JSONB path within the document (e.g., "tags" or "metadata.author")
            query_type: Query type - 'contains', 'exists', 'path_exists', 'path_query'
            value: Value for comparison
            document_column: Name of the JSONB column
            limit: Maximum number of results
            
        Returns:
            List of matching documents
            
        Example:
            # Contains query
            docs = client.documents.query_jsonb("articles", "tags", "contains", ["ai"])
            
            # Field exists
            docs = client.documents.query_jsonb("articles", "views", "exists")
            
            # Path query
            docs = client.documents.query_jsonb("articles", "$.tags[*] ? (@ == 'ai')", "path_query")
        """
        # Build the full path
        path_parts = jsonb_path.split(".")
        jsonb_expr = document_column
        for part in path_parts:
            jsonb_expr += f"->'{part}'"
        
        if query_type == "contains":
            nestedValue = value
            for part in reversed(path_parts):
                nestedValue = {part: nestedValue}
            sql = f"""
                SELECT * FROM {table_name}
                WHERE {document_column} @> :value::jsonb
                LIMIT :limit;
            """
            params = {"value": json.dumps(nestedValue), "limit": limit}
        
        elif query_type == "exists":
            sql = f"""
                SELECT * FROM {table_name}
                WHERE {jsonb_expr} IS NOT NULL
                LIMIT :limit;
            """
            params = {"limit": limit}
        
        elif query_type == "path_exists":
            sql = f"""
                SELECT * FROM {table_name}
                WHERE jsonb_path_exists({document_column}, :path)
                LIMIT :limit;
            """
            params = {"path": f"$.{jsonb_path}", "limit": limit}
        
        elif query_type == "path_query":
            sql = f"""
                SELECT * FROM {table_name}
                WHERE jsonb_path_query({document_column}, :path) IS NOT NULL
                LIMIT :limit;
            """
            params = {"path": jsonb_path, "limit": limit}
        
        else:
            raise ValueError(f"Unknown query type: {query_type}")
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            rows = result.fetchall()
            
            return [dict(row._mapping) for row in rows]
    
    def count(
        self,
        table_name: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Count documents in a table.
        
        Args:
            table_name: Name of the table
            filters: Optional filters
            
        Returns:
            Number of documents
        """
        sql = f"SELECT COUNT(*) FROM {table_name}"
        params = {}
        
        if filters:
            where_clauses = []
            for key, value in filters.items():
                param_name = _make_safe_param_name(key, "filter_")
                
                if "->>" in key:
                    where_clauses.append(f"{key} = :{param_name}")
                    params[param_name] = value
                elif "->" in key:
                    if isinstance(value, (list, dict)):
                        where_clauses.append(f"{key} @> :{param_name}::jsonb")
                        params[param_name] = json.dumps(value)
                    else:
                        text_key = key.replace("->", "->>", 1) if "->>" not in key else key
                        where_clauses.append(f"{text_key} = :{param_name}")
                        params[param_name] = value
                else:
                    where_clauses.append(f"{key} = :{param_name}")
                    params[param_name] = value
            sql += " WHERE " + " AND ".join(where_clauses)
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            return result.scalar()
    
    def aggregate(
        self,
        table_name: str,
        aggregations: Dict[str, str],
        group_by: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Aggregate documents.
        
        Args:
            table_name: Name of the table
            aggregations: Aggregation expressions as {alias: expression}
                         e.g., {"total": "COUNT(*)", "avg_views": "AVG((data->>'views')::int)"}
            group_by: Columns to group by
            filters: Optional filters
            
        Returns:
            List of aggregation results
            
        Example:
            results = client.documents.aggregate(
                "articles",
                aggregations={
                    "count": "COUNT(*)",
                    "avg_views": "AVG((data->>'views')::float)"
                },
                group_by=["data->>'category'"]
            )
        """
        agg_exprs = [f"{expr} AS {alias}" for alias, expr in aggregations.items()]
        
        sql = f"SELECT {', '.join(agg_exprs)} FROM {table_name}"
        params = {}
        
        if filters:
            where_clauses = []
            for key, value in filters.items():
                param_name = _make_safe_param_name(key, "filter_")
                
                if "->>" in key:
                    where_clauses.append(f"{key} = :{param_name}")
                    params[param_name] = value
                elif "->" in key:
                    if isinstance(value, (list, dict)):
                        where_clauses.append(f"{key} @> :{param_name}::jsonb")
                        params[param_name] = json.dumps(value)
                    else:
                        text_key = key.replace("->", "->>", 1) if "->>" not in key else key
                        where_clauses.append(f"{text_key} = :{param_name}")
                        params[param_name] = value
                else:
                    where_clauses.append(f"{key} = :{param_name}")
                    params[param_name] = value
            sql += " WHERE " + " AND ".join(where_clauses)
        
        if group_by:
            sql += f" GROUP BY {', '.join(group_by)}"
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            rows = result.fetchall()
            
            return [dict(row._mapping) for row in rows]
