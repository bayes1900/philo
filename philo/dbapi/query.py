"""
Query API - Raw SQL execution and utility functions.

Provides low-level database operations:
- Execute raw SQL queries
- Transaction management
- Table introspection
- Database metadata queries
"""

from typing import Optional, List, Dict, Any, Union, Tuple
from contextlib import contextmanager

from sqlalchemy import text


class QueryAPI:
    """
    API for raw SQL execution and database utilities.
    
    This class provides low-level database operations for cases where
    the higher-level APIs (VectorAPI, TimeSeriesAPI, DocumentAPI) are
    not sufficient.
    
    Features:
    - Execute raw SQL queries
    - Transaction management
    - Table introspection
    - Index management
    - Database statistics
    
    Example:
        # Execute raw SQL
        results = client.query.execute(
            "SELECT * FROM users WHERE age > :age",
            {"age": 18}
        )
        
        # Transaction
        with client.query.transaction() as tx:
            tx.execute("INSERT INTO ...")
            tx.execute("UPDATE ...")
        
        # Table info
        columns = client.query.get_table_columns("users")
        indexes = client.query.get_table_indexes("users")
    """
    
    def __init__(self, client):
        """
        Initialize QueryAPI.
        
        Args:
            client: DatabaseClient instance
        """
        self._client = client
    
    def execute(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a SQL query and return results.
        
        Args:
            sql: SQL statement to execute
            params: Parameters for the SQL statement
            
        Returns:
            List of result rows as dictionaries
            
        Example:
            results = client.query.execute(
                "SELECT * FROM users WHERE name = :name",
                {"name": "John"}
            )
        """
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params or {})
            if result.returns_rows:
                rows = result.fetchall()
                if rows:
                    return [dict(row._mapping) for row in rows]
            return []
    
    def execute_one(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Execute a SQL query and return a single result.
        
        Args:
            sql: SQL statement to execute
            params: Parameters for the SQL statement
            
        Returns:
            Single result row as dictionary, or None
        """
        results = self.execute(sql, params)
        return results[0] if results else None
    
    def execute_scalar(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Execute a SQL query and return a single scalar value.
        
        Args:
            sql: SQL statement to execute
            params: Parameters for the SQL statement
            
        Returns:
            Single scalar value
        """
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params or {})
            row = result.fetchone()
            
            if row:
                return row[0]
            return None
    
    def execute_many(
        self,
        sql: str,
        params_list: List[Dict[str, Any]],
    ) -> int:
        """
        Execute a SQL statement with multiple parameter sets.
        
        Args:
            sql: SQL statement to execute
            params_list: List of parameter dictionaries
            
        Returns:
            Total number of rows affected
        """
        total_affected = 0
        with self._client.session_scope() as session:
            for params in params_list:
                result = session.execute(text(sql), params)
                total_affected += result.rowcount
        
        return total_affected
    
    @contextmanager
    def transaction(self):
        """
        Context manager for explicit transaction control.
        
        Yields a transaction object that can execute multiple statements.
        Automatically commits on success, rolls back on exception.
        
        Example:
            with client.query.transaction() as tx:
                tx.execute("INSERT INTO users (name) VALUES (:name)", {"name": "John"})
                tx.execute("UPDATE stats SET count = count + 1")
        """
        session = self._client.get_session()
        tx = TransactionWrapper(session)
        try:
            yield tx
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def create_table(
        self,
        table_name: str,
        columns: Dict[str, str],
        primary_key: Optional[Union[str, List[str]]] = None,
        if_not_exists: bool = True,
        additional_constraints: Optional[List[str]] = None,
    ) -> None:
        """
        Create a table with specified columns.
        
        Args:
            table_name: Name of the table
            columns: Column definitions as {column_name: column_type}
            primary_key: Primary key column(s)
            if_not_exists: Add IF NOT EXISTS clause
            additional_constraints: Additional table constraints
            
        Example:
            client.query.create_table(
                "users",
                columns={
                    "id": "SERIAL",
                    "name": "TEXT NOT NULL",
                    "email": "TEXT UNIQUE",
                    "created_at": "TIMESTAMPTZ DEFAULT NOW()"
                },
                primary_key="id"
            )
        """
        exists_clause = "IF NOT EXISTS" if if_not_exists else ""
        
        col_defs = []
        for col_name, col_type in columns.items():
            col_defs.append(f"{col_name} {col_type}")
        
        if primary_key:
            if isinstance(primary_key, str):
                col_defs.append(f"PRIMARY KEY ({primary_key})")
            else:
                col_defs.append(f"PRIMARY KEY ({', '.join(primary_key)})")
        
        if additional_constraints:
            col_defs.extend(additional_constraints)
        
        sql = f"""
            CREATE TABLE {exists_clause} {table_name} (
                {', '.join(col_defs)}
            );
        """
        
        with self._client.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
    
    def drop_table(
        self,
        table_name: str,
        if_exists: bool = True,
        cascade: bool = False,
    ) -> None:
        """
        Drop a table.
        
        Args:
            table_name: Name of the table
            if_exists: Add IF EXISTS clause
            cascade: Add CASCADE clause
        """
        exists_clause = "IF EXISTS" if if_exists else ""
        cascade_clause = "CASCADE" if cascade else ""
        
        sql = f"DROP TABLE {exists_clause} {table_name} {cascade_clause};"
        
        with self._client.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
    
    def truncate_table(
        self,
        table_name: str,
        cascade: bool = False,
        restart_identity: bool = False,
    ) -> None:
        """
        Truncate a table (remove all rows).
        
        Args:
            table_name: Name of the table
            cascade: Add CASCADE clause
            restart_identity: Restart sequences
        """
        cascade_clause = "CASCADE" if cascade else ""
        restart_clause = "RESTART IDENTITY" if restart_identity else ""
        
        sql = f"TRUNCATE TABLE {table_name} {restart_clause} {cascade_clause};"
        
        with self._client.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
    
    def table_exists(self, table_name: str) -> bool:
        """
        Check if a table exists.
        
        Args:
            table_name: Name of the table
            
        Returns:
            True if the table exists
        """
        sql = """
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = :table_name
            );
        """
        return self.execute_scalar(sql, {"table_name": table_name})
    
    def get_table_columns(
        self,
        table_name: str,
        schema: str = "public",
    ) -> List[Dict[str, Any]]:
        """
        Get column information for a table.
        
        Args:
            table_name: Name of the table
            schema: Schema name
            
        Returns:
            List of column information dictionaries
        """
        sql = """
            SELECT 
                column_name,
                data_type,
                is_nullable,
                column_default,
                character_maximum_length,
                numeric_precision,
                numeric_scale
            FROM information_schema.columns
            WHERE table_schema = :schema
            AND table_name = :table_name
            ORDER BY ordinal_position;
        """
        params = {"schema": schema, "table_name": table_name}
        return self.execute(sql, params)
    
    def get_table_indexes(
        self,
        table_name: str,
        schema: str = "public",
    ) -> List[Dict[str, Any]]:
        """
        Get index information for a table.
        
        Args:
            table_name: Name of the table
            schema: Schema name
            
        Returns:
            List of index information dictionaries
        """
        sql = """
            SELECT 
                i.relname as index_name,
                a.attname as column_name,
                am.amname as index_type,
                ix.indisunique as is_unique,
                ix.indisprimary as is_primary
            FROM pg_class t
            JOIN pg_index ix ON t.oid = ix.indrelid
            JOIN pg_class i ON i.oid = ix.indexrelid
            JOIN pg_am am ON i.relam = am.oid
            JOIN pg_namespace n ON t.relnamespace = n.oid
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
            WHERE n.nspname = :schema
            AND t.relname = :table_name
            ORDER BY i.relname, a.attnum;
        """
        params = {"schema": schema, "table_name": table_name}
        return self.execute(sql, params)
    
    def create_index(
        self,
        table_name: str,
        columns: Union[str, List[str]],
        index_name: Optional[str] = None,
        unique: bool = False,
        index_type: str = "btree",
        if_not_exists: bool = True,
        where: Optional[str] = None,
    ) -> None:
        """
        Create an index on a table.
        
        Args:
            table_name: Name of the table
            columns: Column(s) to index
            index_name: Custom index name
            unique: Create a unique index
            index_type: Index type (btree, hash, gin, gist, etc.)
            if_not_exists: Add IF NOT EXISTS clause
            where: Partial index condition
            
        Example:
            # Simple index
            client.query.create_index("users", "email")
            
            # Composite index
            client.query.create_index("orders", ["user_id", "created_at"])
            
            # GIN index for JSONB
            client.query.create_index("articles", "data", index_type="gin")
            
            # Partial index
            client.query.create_index("orders", "status", where="status = 'pending'")
        """
        if isinstance(columns, str):
            columns = [columns]
        
        if index_name is None:
            index_name = f"idx_{table_name}_{'_'.join(columns)}"
        
        unique_clause = "UNIQUE" if unique else ""
        exists_clause = "IF NOT EXISTS" if if_not_exists else ""
        
        sql = f"""
            CREATE {unique_clause} INDEX {exists_clause} {index_name}
            ON {table_name}
            USING {index_type} ({', '.join(columns)});
        """
        
        if where:
            sql = sql.rstrip(';') + f" WHERE {where};"
        
        with self._client.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
    
    def drop_index(
        self,
        index_name: str,
        if_exists: bool = True,
    ) -> None:
        """
        Drop an index.
        
        Args:
            index_name: Name of the index
            if_exists: Add IF EXISTS clause
        """
        exists_clause = "IF EXISTS" if if_exists else ""
        sql = f"DROP INDEX {exists_clause} {index_name};"
        
        with self._client.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
    
    def get_table_size(
        self,
        table_name: str,
    ) -> Dict[str, Any]:
        """
        Get size information for a table.
        
        Args:
            table_name: Name of the table
            
        Returns:
            Dictionary with size information
        """
        sql = """
            SELECT 
                pg_size_pretty(pg_total_relation_size(:table_name)) as total_size,
                pg_size_pretty(pg_relation_size(:table_name)) as table_size,
                pg_size_pretty(pg_total_relation_size(:table_name) - pg_relation_size(:table_name)) as index_size,
                (SELECT count(*) FROM information_schema.columns WHERE table_name = :table_name) as column_count,
                (SELECT reltuples::bigint FROM pg_class WHERE relname = :table_name) as estimated_row_count;
        """
        return self.execute_one(sql, {"table_name": table_name})
    
    def get_database_size(self) -> str:
        """
        Get the total size of the current database.
        
        Returns:
            Human-readable database size
        """
        sql = "SELECT pg_size_pretty(pg_database_size(current_database()));"
        return self.execute_scalar(sql)
    
    def list_tables(
        self,
        schema: str = "public",
        include_system: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        List all tables in the database.
        
        Args:
            schema: Schema name
            include_system: Include system tables
            
        Returns:
            List of table information
        """
        sql = """
            SELECT 
                table_name,
                table_type
            FROM information_schema.tables
            WHERE table_schema = :schema
        """
        params = {"schema": schema}
        
        if not include_system:
            sql += " AND table_type = 'BASE TABLE'"
        
        sql += " ORDER BY table_name;"
        
        return self.execute(sql, params)
    
    def list_views(
        self,
        schema: str = "public",
    ) -> List[Dict[str, Any]]:
        """
        List all views in the database.
        
        Args:
            schema: Schema name
            
        Returns:
            List of view information
        """
        sql = """
            SELECT 
                table_name as view_name
            FROM information_schema.views
            WHERE table_schema = :schema
            ORDER BY table_name;
        """
        params = {"schema": schema}
        return self.execute(sql, params)
    
    def get_table_stats(
        self,
        table_name: str,
    ) -> Dict[str, Any]:
        """
        Get statistics for a table.
        
        Args:
            table_name: Name of the table
            
        Returns:
            Dictionary with table statistics
        """
        sql = """
            SELECT 
                n_live_tup as row_count,
                n_dead_tup as dead_row_count,
                last_vacuum,
                last_autovacuum,
                last_analyze,
                last_autoanalyze,
                vacuum_count,
                autovacuum_count,
                analyze_count,
                autoanalyze_count
            FROM pg_stat_user_tables
            WHERE relname = :table_name;
        """
        params = {"table_name": table_name}
        return self.execute_one(sql, params) or {}
    
    def vacuum(
        self,
        table_name: Optional[str] = None,
        full: bool = False,
        analyze: bool = True,
    ) -> None:
        """
        Run VACUUM on a table or the entire database.
        
        Args:
            table_name: Name of the table (optional, vacuums entire database if not specified)
            full: Run VACUUM FULL
            analyze: Run ANALYZE after vacuum
        """
        options = []
        if full:
            options.append("FULL")
        if analyze:
            options.append("ANALYZE")
        
        options_str = " ".join(options)
        if options_str:
            options_str = " " + options_str
        
        if table_name:
            sql = f"VACUUM{options_str} {table_name};"
        else:
            sql = f"VACUUM{options_str};"
        
        # VACUUM cannot run inside a transaction block
        conn = self._client.engine.connect()
        try:
            conn.connection.autocommit = True
            conn.execute(text(sql))
        finally:
            conn.close()
    
    def analyze(
        self,
        table_name: Optional[str] = None,
    ) -> None:
        """
        Run ANALYZE on a table or the entire database.
        
        Args:
            table_name: Name of the table (optional)
        """
        if table_name:
            sql = f"ANALYZE {table_name};"
        else:
            sql = "ANALYZE;"
        
        conn = self._client.engine.connect()
        try:
            conn.connection.autocommit = True
            conn.execute(text(sql))
        finally:
            conn.close()
    
    def explain(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
        analyze: bool = False,
        format: str = "text",
    ) -> str:
        """
        Get the execution plan for a query.
        
        Args:
            sql: SQL statement to explain
            params: Parameters for the SQL statement
            analyze: Actually execute the query
            format: Output format (text, json, yaml, xml)
            
        Returns:
            Execution plan as string
        """
        options = []
        if analyze:
            options.append("ANALYZE")
        options.append(f"FORMAT {format.upper()}")
        
        options_str = ", ".join(options)
        explain_sql = f"EXPLAIN ({options_str}) {sql}"
        
        with self._client.session_scope() as session:
            result = session.execute(text(explain_sql), params or {})
            rows = result.fetchall()
            
            return "\n".join(row[0] for row in rows)
    
    def copy_from_csv(
        self,
        table_name: str,
        csv_path: str,
        delimiter: str = ",",
        header: bool = True,
        columns: Optional[List[str]] = None,
    ) -> int:
        """
        Copy data from a CSV file to a table.
        
        Args:
            table_name: Name of the table
            csv_path: Path to the CSV file
            delimiter: CSV delimiter
            header: CSV has header row
            columns: Specific columns to copy
            
        Returns:
            Number of rows copied
        """
        header_clause = "HEADER" if header else ""
        columns_clause = f"({', '.join(columns)})" if columns else ""
        
        sql = f"""
            COPY {table_name} {columns_clause}
            FROM '{csv_path}'
            WITH (FORMAT CSV, DELIMITER '{delimiter}', {header_clause});
        """
        
        conn = self._client.engine.connect()
        try:
            conn.connection.autocommit = True
            result = conn.execute(text(sql))
            return result.rowcount
        finally:
            conn.close()
    
    def copy_to_csv(
        self,
        sql_query: str,
        csv_path: str,
        delimiter: str = ",",
        header: bool = True,
    ) -> None:
        """
        Copy query results to a CSV file.
        
        Args:
            sql_query: SQL query to execute
            csv_path: Path to the output CSV file
            delimiter: CSV delimiter
            header: Include header row
        """
        header_clause = "HEADER" if header else ""
        
        copy_sql = f"""
            COPY ({sql_query})
            TO '{csv_path}'
            WITH (FORMAT CSV, DELIMITER '{delimiter}', {header_clause});
        """
        
        conn = self._client.engine.connect()
        try:
            conn.connection.autocommit = True
            conn.execute(text(copy_sql))
        finally:
            conn.close()


class TransactionWrapper:
    """
    Wrapper for transaction execution.
    
    Provides a simple interface for executing multiple statements
    within a transaction.
    """
    
    def __init__(self, session):
        """
        Initialize TransactionWrapper.
        
        Args:
            session: SQLAlchemy session
        """
        self._session = session
    
    def execute(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a SQL statement within the transaction.
        
        Args:
            sql: SQL statement
            params: Parameters
            
        Returns:
            List of result rows
        """
        result = self._session.execute(text(sql), params or {})
        if result.returns_rows:
            rows = result.fetchall()
            if rows:
                return [dict(row._mapping) for row in rows]
        return []
    
    def execute_one(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Execute and return a single result."""
        results = self.execute(sql, params)
        return results[0] if results else None
    
    def execute_scalar(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Execute and return a single scalar value."""
        result = self._session.execute(text(sql), params or {})
        row = result.fetchone()
        return row[0] if row else None