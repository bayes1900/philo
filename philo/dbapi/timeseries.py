"""
TimeSeries API - TimescaleDB operations for time-series data.

Provides schema-agnostic time-series operations:
- Create hypertables for automatic time-based partitioning
- Insert and query time-series data
- Time-based aggregations (downsampling)
- Continuous aggregates for real-time analytics
- Data retention policies
"""

from typing import Optional, List, Dict, Any, Union, Tuple
from datetime import datetime, timedelta

from sqlalchemy import text


class TimeSeriesAPI:
    """
    API for TimescaleDB operations.
    
    This class provides a schema-agnostic interface for time-series data
    using PostgreSQL's TimescaleDB extension.
    
    Features:
    - Automatic time-based partitioning with hypertables
    - Time-range queries with efficient indexing
    - Aggregation functions (time_bucket)
    - Continuous aggregates for real-time analytics
    - Data retention policies
    
    Example:
        # Create a hypertable
        client.timeseries.create_hypertable(
            "sensor_data",
            time_column="timestamp",
            partition_interval="1 day"
        )
        
        # Insert time-series data
        client.timeseries.insert("sensor_data", {
            "timestamp": datetime.now(),
            "device_id": "sensor_001",
            "temperature": 25.5,
            "humidity": 60.0
        })
        
        # Query time range
        data = client.timeseries.query_range(
            "sensor_data",
            start_time=datetime.now() - timedelta(hours=1),
            end_time=datetime.now(),
            filters={"device_id": "sensor_001"}
        )
        
        # Aggregate data
        hourly_avg = client.timeseries.aggregate(
            "sensor_data",
            interval="1 hour",
            aggregations={"temperature": "AVG", "humidity": "AVG"}
        )
    """
    
    def __init__(self, client):
        """
        Initialize TimeSeriesAPI.
        
        Args:
            client: DatabaseClient instance
        """
        self._client = client
    
    def create_hypertable(
        self,
        table_name: str,
        time_column: str = "time",
        partition_interval: str = "1 day",
        if_not_exists: bool = True,
        migrate_data: bool = False,
        space_partition_column: Optional[str] = None,
        space_partitions: int = 4,
    ) -> None:
        """
        Convert a regular table to a TimescaleDB hypertable.
        
        Args:
            table_name: Name of the table to convert
            time_column: Name of the time column
            partition_interval: Time interval for each partition (e.g., "1 day", "1 week")
            if_not_exists: Skip if already a hypertable
            migrate_data: Migrate existing data (slower for large tables)
            space_partition_column: Column for space partitioning (e.g., "device_id")
            space_partitions: Number of space partitions
            
        Example:
            # Simple hypertable
            client.timeseries.create_hypertable("metrics", time_column="timestamp")
            
            # With space partitioning for multi-tenant data
            client.timeseries.create_hypertable(
                "sensor_data",
                time_column="timestamp",
                space_partition_column="device_id",
                space_partitions=4
            )
        """
        if_not_exists_clause = "IF NOT EXISTS" if if_not_exists else ""
        migrate_data_clause = ", migrate_data => TRUE" if migrate_data else ""
        
        # Build partitioning clause
        partitioning_clause = ""
        if space_partition_column:
            partitioning_clause = f", partitioning_column => '{space_partition_column}', number_partitions => {space_partitions}"
        
        sql = f"""
            SELECT create_hypertable(
                '{table_name}',
                '{time_column}',
                chunk_time_interval => INTERVAL '{partition_interval}'{partitioning_clause}{migrate_data_clause},
                if_not_exists => {'TRUE' if if_not_exists else 'FALSE'}
            );
        """
        
        with self._client.engine.connect() as conn:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception as e:
                if "already a hypertable" in str(e).lower():
                    if if_not_exists:
                        return
                raise
    
    def create_table(
        self,
        table_name: str,
        time_column: str = "time",
        time_type: str = "TIMESTAMPTZ DEFAULT NOW()",
        additional_columns: Optional[Dict[str, str]] = None,
        partition_interval: str = "1 day",
        primary_key: Optional[List[str]] = None,
        space_partition_column: Optional[str] = None,
    ) -> None:
        """
        Create a new table and convert it to a hypertable.
        
        Args:
            table_name: Name of the table to create
            time_column: Name of the time column
            time_type: Type of the time column
            additional_columns: Additional columns as {column_name: column_definition}
            partition_interval: Time interval for each partition
            primary_key: List of columns to use as primary key (optional)
            space_partition_column: Column for space partitioning
            
        Example:
            client.timeseries.create_table(
                "stock_prices",
                time_column="time",
                additional_columns={
                    "symbol": "TEXT NOT NULL",
                    "price": "NUMERIC(18, 6)",
                    "volume": "BIGINT"
                },
                primary_key=["time", "symbol"],
                space_partition_column="symbol"
            )
        """
        columns = [f"{time_column} {time_type}"]
        
        if additional_columns:
            for col_name, col_def in additional_columns.items():
                columns.append(f"{col_name} {col_def}")
        
        pk_clause = ""
        if primary_key:
            pk_clause = f", PRIMARY KEY ({', '.join(primary_key)})"
        
        sql = f"""
            CREATE TABLE {table_name} (
                {', '.join(columns)}{pk_clause}
            );
        """
        
        with self._client.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
        
        # Convert to hypertable
        self.create_hypertable(
            table_name,
            time_column=time_column,
            partition_interval=partition_interval,
            space_partition_column=space_partition_column,
        )
    
    def insert(
        self,
        table_name: str,
        data: Dict[str, Any],
    ) -> Any:
        """
        Insert a single time-series record.
        
        Args:
            table_name: Name of the table
            data: Dictionary containing the data
            
        Returns:
            The inserted record's ID or time
            
        Example:
            client.timeseries.insert("metrics", {
                "timestamp": datetime.now(),
                "metric_name": "cpu_usage",
                "value": 75.5
            })
        """
        columns = list(data.keys())
        values = [f":{col}" for col in columns]
        params = data.copy()
        
        # Handle datetime serialization
        for key, value in params.items():
            if isinstance(value, datetime):
                params[key] = value
        
        sql = f"""
            INSERT INTO {table_name} ({', '.join(columns)})
            VALUES ({', '.join(values)})
            RETURNING *;
        """
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            row = result.fetchone()
            if row:
                return dict(row._mapping)
            return None
    
    def insert_many(
        self,
        table_name: str,
        data_list: List[Dict[str, Any]],
    ) -> int:
        """
        Insert multiple time-series records.
        
        Args:
            table_name: Name of the table
            data_list: List of dictionaries containing the data
            
        Returns:
            Number of records inserted
            
        Example:
            client.timeseries.insert_many("metrics", [
                {"timestamp": datetime.now(), "value": 10.0},
                {"timestamp": datetime.now() + timedelta(minutes=1), "value": 11.0},
            ])
        """
        if not data_list:
            return 0
        
        count = 0
        with self._client.session_scope() as session:
            for data in data_list:
                columns = list(data.keys())
                values = [f":{col}" for col in columns]
                params = data.copy()
                
                sql = f"""
                    INSERT INTO {table_name} ({', '.join(columns)})
                    VALUES ({', '.join(values)});
                """
                session.execute(text(sql), params)
                count += 1
        
        return count
    
    def query_range(
        self,
        table_name: str,
        start_time: datetime,
        end_time: datetime,
        time_column: str = "time",
        columns: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        order_by: str = "asc",
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Query time-series data within a time range.
        
        Args:
            table_name: Name of the table
            start_time: Start of the time range
            end_time: End of the time range
            time_column: Name of the time column
            columns: Columns to return (default: all)
            filters: Additional filters as {column: value}
            order_by: Order direction - 'asc' or 'desc'
            limit: Maximum number of records to return
            
        Returns:
            List of dictionaries containing the results
            
        Example:
            data = client.timeseries.query_range(
                "sensor_data",
                start_time=datetime.now() - timedelta(hours=1),
                end_time=datetime.now(),
                filters={"device_id": "sensor_001"}
            )
        """
        select_cols = ", ".join(columns) if columns else "*"
        
        sql = f"""
            SELECT {select_cols}
            FROM {table_name}
            WHERE {time_column} >= :start_time
            AND {time_column} <= :end_time
        """
        params = {
            "start_time": start_time,
            "end_time": end_time,
        }
        
        if filters:
            for key, value in filters.items():
                sql += f" AND {key} = :filter_{key}"
                params[f"filter_{key}"] = value
        
        order_dir = "ASC" if order_by.lower() == "asc" else "DESC"
        sql += f" ORDER BY {time_column} {order_dir}"
        
        if limit:
            sql += f" LIMIT :limit"
            params["limit"] = limit
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            rows = result.fetchall()
            
            return [dict(row._mapping) for row in rows]
    
    def query_latest(
        self,
        table_name: str,
        time_column: str = "time",
        filters: Optional[Dict[str, Any]] = None,
        columns: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get the latest record from a time-series table.
        
        Args:
            table_name: Name of the table
            time_column: Name of the time column
            filters: Additional filters as {column: value}
            columns: Columns to return (default: all)
            
        Returns:
            Dictionary containing the latest record, or None if no records
        """
        select_cols = ", ".join(columns) if columns else "*"
        
        sql = f"""
            SELECT {select_cols}
            FROM {table_name}
        """
        params = {}
        
        if filters:
            where_clauses = []
            for key, value in filters.items():
                where_clauses.append(f"{key} = :{key}")
                params[key] = value
            sql += " WHERE " + " AND ".join(where_clauses)
        
        sql += f" ORDER BY {time_column} DESC LIMIT 1"
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            row = result.fetchone()
            
            if row:
                return dict(row._mapping)
            return None
    
    def query_first(
        self,
        table_name: str,
        time_column: str = "time",
        filters: Optional[Dict[str, Any]] = None,
        columns: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get the first (oldest) record from a time-series table.
        
        Args:
            table_name: Name of the table
            time_column: Name of the time column
            filters: Additional filters as {column: value}
            columns: Columns to return (default: all)
            
        Returns:
            Dictionary containing the first record, or None if no records
        """
        select_cols = ", ".join(columns) if columns else "*"
        
        sql = f"""
            SELECT {select_cols}
            FROM {table_name}
        """
        params = {}
        
        if filters:
            where_clauses = []
            for key, value in filters.items():
                where_clauses.append(f"{key} = :{key}")
                params[key] = value
            sql += " WHERE " + " AND ".join(where_clauses)
        
        sql += f" ORDER BY {time_column} ASC LIMIT 1"
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            row = result.fetchone()
            
            if row:
                return dict(row._mapping)
            return None
    
    def aggregate(
        self,
        table_name: str,
        interval: str,
        aggregations: Dict[str, str],
        time_column: str = "time",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        filters: Optional[Dict[str, Any]] = None,
        group_by: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Aggregate time-series data using time buckets.
        
        Args:
            table_name: Name of the table
            interval: Time bucket interval (e.g., "1 hour", "1 day", "5 minutes")
            aggregations: Aggregation functions as {column: function}
                         Supported functions: AVG, SUM, MIN, MAX, COUNT, STDDEV
            time_column: Name of the time column
            start_time: Start of the time range (optional)
            end_time: End of the time range (optional)
            filters: Additional filters as {column: value}
            group_by: Additional columns to group by
            
        Returns:
            List of aggregated results
            
        Example:
            # Get hourly averages
            hourly_data = client.timeseries.aggregate(
                "sensor_data",
                interval="1 hour",
                aggregations={"temperature": "AVG", "humidity": "AVG"}
            )
            
            # Get daily totals by device
            daily_totals = client.timeseries.aggregate(
                "sensor_data",
                interval="1 day",
                aggregations={"value": "SUM"},
                group_by=["device_id"]
            )
        """
        # Build aggregation expressions
        agg_exprs = []
        for col, func in aggregations.items():
            agg_exprs.append(f"{func}({col}) AS {col}_{func.lower()}")
        
        # Build time bucket expression
        time_bucket = f"time_bucket(INTERVAL '{interval}', {time_column}) AS bucket"
        
        select_cols = [time_bucket] + agg_exprs
        
        # Add group by columns
        if group_by:
            select_cols.extend(group_by)
        
        sql = f"""
            SELECT {', '.join(select_cols)}
            FROM {table_name}
            WHERE 1=1
        """
        params = {}
        
        if start_time:
            sql += f" AND {time_column} >= :start_time"
            params["start_time"] = start_time
        
        if end_time:
            sql += f" AND {time_column} <= :end_time"
            params["end_time"] = end_time
        
        if filters:
            for key, value in filters.items():
                sql += f" AND {key} = :filter_{key}"
                params[f"filter_{key}"] = value
        
        # Group by clause
        group_cols = ["bucket"]
        if group_by:
            group_cols.extend(group_by)
        sql += f" GROUP BY {', '.join(group_cols)}"
        sql += f" ORDER BY bucket ASC"
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            rows = result.fetchall()
            
            return [dict(row._mapping) for row in rows]
    
    def create_continuous_aggregate(
        self,
        view_name: str,
        table_name: str,
        interval: str,
        aggregations: Dict[str, str],
        time_column: str = "time",
        group_by: Optional[List[str]] = None,
        refresh_interval: Optional[str] = None,
        create_materialized: bool = True,
    ) -> None:
        """
        Create a continuous aggregate for real-time analytics.
        
        Continuous aggregates automatically refresh and provide fast queries
        for aggregated time-series data.
        
        Args:
            view_name: Name of the aggregate view
            table_name: Source table name
            interval: Time bucket interval
            aggregations: Aggregation functions as {column: function}
            time_column: Name of the time column
            group_by: Additional columns to group by
            refresh_interval: How often to refresh the aggregate (optional)
            create_materialized: Create as materialized view (default: True)
            
        Example:
            client.timeseries.create_continuous_aggregate(
                "hourly_metrics",
                "sensor_data",
                interval="1 hour",
                aggregations={"temperature": "AVG", "humidity": "AVG"},
                group_by=["device_id"],
                refresh_interval="1 hour"
            )
        """
        # Build aggregation expressions
        agg_exprs = []
        for col, func in aggregations.items():
            agg_exprs.append(f"{func}({col}) AS {col}_{func.lower()}")
        
        # Build time bucket expression
        time_bucket = f"time_bucket(INTERVAL '{interval}', {time_column}) AS bucket"
        
        select_cols = [time_bucket] + agg_exprs
        if group_by:
            select_cols.extend(group_by)
        
        # Group by clause
        group_cols = ["bucket"]
        if group_by:
            group_cols.extend(group_by)
        
        sql = f"""
            CREATE MATERIALIZED VIEW IF NOT EXISTS {view_name}
            WITH (timescaledb.continuous) AS
            SELECT {', '.join(select_cols)}
            FROM {table_name}
            GROUP BY {', '.join(group_cols)}
            WITH NO DATA;
        """
        
        with self._client.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
            
            # Set refresh interval if specified
            if refresh_interval:
                refresh_sql = f"""
                    SELECT add_continuous_aggregate_policy(
                        '{view_name}',
                        start_offset => INTERVAL '{interval}',
                        end_offset => INTERVAL '1 {interval.split()[1]}',
                        schedule_interval => INTERVAL '{refresh_interval}'
                    );
                """
                try:
                    conn.execute(text(refresh_sql))
                    conn.commit()
                except Exception:
                    pass  # Policy might already exist
    
    def refresh_continuous_aggregate(
        self,
        view_name: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> None:
        """
        Manually refresh a continuous aggregate.
        
        Args:
            view_name: Name of the aggregate view
            start_time: Start time for refresh (optional)
            end_time: End time for refresh (optional)
        """
        if start_time and end_time:
            sql = f"""
                CALL refresh_continuous_aggregate(
                    '{view_name}',
                    '{start_time.isoformat()}',
                    '{end_time.isoformat()}'
                );
            """
        else:
            sql = f"CALL refresh_continuous_aggregate('{view_name}');"
        
        with self._client.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
    
    def drop_continuous_aggregate(self, view_name: str, if_exists: bool = True) -> None:
        """Drop a continuous aggregate view."""
        exists_clause = "IF EXISTS" if if_exists else ""
        sql = f"DROP MATERIALIZED VIEW {exists_clause} {view_name};"
        
        with self._client.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
    
    def set_retention_policy(
        self,
        table_name: str,
        retention_period: str,
        cascade: bool = False,
    ) -> None:
        """
        Set a data retention policy for automatic data deletion.
        
        Args:
            table_name: Name of the hypertable
            retention_period: How long to keep data (e.g., "30 days", "1 year")
            cascade: Cascade deletion to dependent tables
            
        Example:
            # Keep only last 90 days of data
            client.timeseries.set_retention_policy("sensor_data", "90 days")
        """
        cascade_clause = ", cascade => TRUE" if cascade else ""
        
        sql = f"""
            SELECT add_retention_policy(
                '{table_name}',
                INTERVAL '{retention_period}'{cascade_clause}
            );
        """
        
        with self._client.engine.connect() as conn:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception as e:
                if "already exists" in str(e).lower():
                    # Update existing policy
                    sql = f"""
                        SELECT remove_retention_policy('{table_name}');
                        SELECT add_retention_policy(
                            '{table_name}',
                            INTERVAL '{retention_period}'{cascade_clause}
                        );
                    """
                    conn.execute(text(sql))
                    conn.commit()
                else:
                    raise
    
    def remove_retention_policy(self, table_name: str) -> None:
        """Remove the retention policy from a hypertable."""
        sql = f"SELECT remove_retention_policy('{table_name}');"
        
        with self._client.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
    
    def delete_range(
        self,
        table_name: str,
        start_time: datetime,
        end_time: datetime,
        time_column: str = "time",
        filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Delete time-series data within a time range.
        
        Args:
            table_name: Name of the table
            start_time: Start of the time range
            end_time: End of the time range
            time_column: Name of the time column
            filters: Additional filters as {column: value}
            
        Returns:
            Number of records deleted
        """
        sql = f"""
            DELETE FROM {table_name}
            WHERE {time_column} >= :start_time
            AND {time_column} <= :end_time
        """
        params = {
            "start_time": start_time,
            "end_time": end_time,
        }
        
        if filters:
            for key, value in filters.items():
                sql += f" AND {key} = :filter_{key}"
                params[f"filter_{key}"] = value
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            return result.rowcount
    
    def get_chunk_info(
        self,
        table_name: str,
    ) -> List[Dict[str, Any]]:
        """
        Get information about chunks in a hypertable.
        
        Args:
            table_name: Name of the hypertable
            
        Returns:
            List of chunk information dictionaries
        """
        sql = f"""
            SELECT 
                chunk_name,
                range_start,
                range_end,
                is_compressed,
                before_compress_total_bytes,
                after_compress_total_bytes
            FROM timescaledb_information.chunks
            WHERE hypertable_name = :table_name
            ORDER BY range_start DESC;
        """
        params = {"table_name": table_name}
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            rows = result.fetchall()
            
            return [dict(row._mapping) for row in rows]
    
    def compress_chunk(
        self,
        chunk_name: str,
    ) -> None:
        """
        Compress a specific chunk.
        
        Args:
            chunk_name: Name of the chunk to compress
        """
        sql = f"SELECT compress_chunk('{chunk_name}');"
        
        with self._client.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
    
    def enable_compression(
        self,
        table_name: str,
        compress_after: str = "7 days",
        segment_by: Optional[str] = None,
        order_by: Optional[str] = None,
    ) -> None:
        """
        Enable automatic compression for a hypertable.
        
        Args:
            table_name: Name of the hypertable
            compress_after: Compress chunks older than this interval
            segment_by: Column to segment by (optional)
            order_by: Column to order by within segments (optional)
        """
        segment_clause = f", segment_by_column => ARRAY[{segment_by}]" if segment_by else ""
        order_clause = f", order_by_column => ARRAY[{order_by}]" if order_by else ""
        
        sql = f"""
            ALTER TABLE {table_name} SET (
                timescaledb.compress,
                timescaledb.compress_segmentby = '{segment_by}'{order_clause}
            );
            SELECT add_compression_policy(
                '{table_name}',
                INTERVAL '{compress_after}'{segment_clause}{order_clause}
            );
        """
        
        with self._client.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
    
    def get_time_range(
        self,
        table_name: str,
        time_column: str = "time",
        filters: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        Get the time range (min and max) of data in a table.
        
        Args:
            table_name: Name of the table
            time_column: Name of the time column
            filters: Additional filters as {column: value}
            
        Returns:
            Tuple of (min_time, max_time)
        """
        sql = f"""
            SELECT MIN({time_column}) as min_time, MAX({time_column}) as max_time
            FROM {table_name}
        """
        params = {}
        
        if filters:
            where_clauses = []
            for key, value in filters.items():
                where_clauses.append(f"{key} = :{key}")
                params[key] = value
            sql += " WHERE " + " AND ".join(where_clauses)
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            row = result.fetchone()
            
            if row:
                return (row.min_time, row.max_time)
            return (None, None)
    
    def count(
        self,
        table_name: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        time_column: str = "time",
        filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Count records in a time-series table.
        
        Args:
            table_name: Name of the table
            start_time: Start of the time range (optional)
            end_time: End of the time range (optional)
            time_column: Name of the time column
            filters: Additional filters as {column: value}
            
        Returns:
            Number of records
        """
        sql = f"SELECT COUNT(*) FROM {table_name} WHERE 1=1"
        params = {}
        
        if start_time:
            sql += f" AND {time_column} >= :start_time"
            params["start_time"] = start_time
        
        if end_time:
            sql += f" AND {time_column} <= :end_time"
            params["end_time"] = end_time
        
        if filters:
            for key, value in filters.items():
                sql += f" AND {key} = :filter_{key}"
                params[f"filter_{key}"] = value
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            return result.scalar()
    
    def is_hypertable(self, table_name: str) -> bool:
        """
        Check if a table is a hypertable.
        
        Args:
            table_name: Name of the table
            
        Returns:
            True if the table is a hypertable
        """
        sql = f"""
            SELECT EXISTS (
                SELECT 1 FROM timescaledb_information.hypertables
                WHERE hypertable_name = :table_name
            );
        """
        params = {"table_name": table_name}
        
        with self._client.session_scope() as session:
            result = session.execute(text(sql), params)
            return result.scalar()