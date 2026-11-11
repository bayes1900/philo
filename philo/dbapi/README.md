# Generic Database API

一套通用的 PostgreSQL 数据库 API，支持 pgvector 和 TimescaleDB 扩展，无需预定义 schema。

## 特性

- **Schema 无关**: 动态创建表结构，无需预定义模型
- **pgvector 支持**: 向量相似度搜索，支持 HNSW 和 IVFFlat 索引
- **TimescaleDB 支持**: 时序数据自动分区、连续聚合、数据保留策略
- **JSONB 文档存储**: 灵活的文档存储和查询
- **事务管理**: 简单的事务控制接口

## 快速开始

### 安装依赖

```bash
pip install sqlalchemy psycopg2-binary python-dotenv
```

### 初始化客户端

```python
from searanch.database import DatabaseClient

# 使用环境变量 DATABASE_URL
client = DatabaseClient()

# 或直接指定连接字符串
client = DatabaseClient(
    database_url="postgresql://user:pass@localhost:5432/mydb"
)

# 初始化扩展（pgvector, timescaledb）
client.initialize()
```

## API 概览

### 1. Vector API (pgvector)

向量相似度搜索操作。

```python
# 创建向量表
client.vectors.create_table(
    "document_embeddings",
    dimension=1536,  # OpenAI embedding 维度
    metadata_columns={
        "title": "TEXT",
        "source": "TEXT",
        "created_at": "TIMESTAMPTZ DEFAULT NOW()"
    }
)

# 插入向量
doc_id = client.vectors.insert("document_embeddings", {
    "embedding": [0.1, 0.2, 0.3, ...],  # 1536 维向量
    "title": "Document Title",
    "source": "web"
})

# 批量插入
client.vectors.insert_many("document_embeddings", [
    {"embedding": [0.1, ...], "title": "Doc 1"},
    {"embedding": [0.2, ...], "title": "Doc 2"},
])

# 相似度搜索
results = client.vectors.search(
    "document_embeddings",
    query_vector=[0.1, 0.2, ...],
    limit=10,
    distance_threshold=0.3,  # 可选：最大距离阈值
    distance_metric="cosine",  # cosine, l2, inner_product
    filters={"source": "web"}  # 可选：额外过滤条件
)

for r in results:
    print(f"ID: {r['id']}, Title: {r['title']}, Distance: {r['distance']}")

# 创建索引（提高搜索性能）
client.vectors.create_index(
    "document_embeddings",
    index_type="hnsw",  # 或 "ivfflat"
    distance_metric="cosine"
)

# 通过 ID 查找相似文档
similar = client.vectors.search_by_id("document_embeddings", doc_id, limit=5)

# 更新向量
client.vectors.update("document_embeddings", doc_id, {
    "embedding": [0.2, 0.3, ...],
    "title": "Updated Title"
})

# 删除
client.vectors.delete("document_embeddings", doc_id)
```

### 2. TimeSeries API (TimescaleDB)

时序数据操作。

```python
from datetime import datetime, timedelta

# 创建时序表（自动转换为 hypertable）
client.timeseries.create_table(
    "sensor_data",
    time_column="timestamp",
    additional_columns={
        "device_id": "TEXT NOT NULL",
        "temperature": "FLOAT",
        "humidity": "FLOAT"
    },
    partition_interval="1 day",  # 分区间隔
    space_partition_column="device_id"  # 可选：空间分区
)

# 或将现有表转换为 hypertable
client.timeseries.create_hypertable(
    "existing_table",
    time_column="created_at",
    partition_interval="1 week"
)

# 插入数据
client.timeseries.insert("sensor_data", {
    "timestamp": datetime.now(),
    "device_id": "sensor_001",
    "temperature": 25.5,
    "humidity": 60.0
})

# 批量插入
client.timeseries.insert_many("sensor_data", [
    {"timestamp": datetime.now(), "device_id": "s1", "temperature": 25.0},
    {"timestamp": datetime.now() + timedelta(minutes=1), "device_id": "s1", "temperature": 26.0},
])

# 查询时间范围
data = client.timeseries.query_range(
    "sensor_data",
    start_time=datetime.now() - timedelta(hours=1),
    end_time=datetime.now(),
    filters={"device_id": "sensor_001"},
    order_by="desc"
)

# 获取最新记录
latest = client.timeseries.query_latest("sensor_data", filters={"device_id": "sensor_001"})

# 时间聚合
hourly_avg = client.timeseries.aggregate(
    "sensor_data",
    interval="1 hour",
    aggregations={
        "temperature": "AVG",
        "humidity": "AVG",
        "device_id": "COUNT"
    },
    group_by=["device_id"]
)

# 创建连续聚合（自动刷新的物化视图）
client.timeseries.create_continuous_aggregate(
    "hourly_sensor_stats",
    "sensor_data",
    interval="1 hour",
    aggregations={"temperature": "AVG", "humidity": "AVG"},
    group_by=["device_id"],
    refresh_interval="1 hour"
)

# 设置数据保留策略（自动删除旧数据）
client.timeseries.set_retention_policy("sensor_data", "90 days")

# 启用压缩
client.timeseries.enable_compression("sensor_data", compress_after="7 days")

# 获取时间范围
min_time, max_time = client.timeseries.get_time_range("sensor_data")

# 删除时间范围内的数据
deleted = client.timeseries.delete_range(
    "sensor_data",
    start_time=datetime.now() - timedelta(days=30),
    end_time=datetime.now()
)
```

### 3. Document API (JSONB)

JSON 文档存储和查询。

```python
# 创建文档表
client.documents.create_table(
    "articles",
    additional_columns={
        "title": "TEXT",
        "author": "TEXT",
        "created_at": "TIMESTAMPTZ DEFAULT NOW()"
    }
)

# 插入文档
doc_id = client.documents.insert(
    "articles",
    document={  # 存储在 data 列（JSONB）
        "category": "tech",
        "tags": ["ai", "machine-learning"],
        "views": 100,
        "metadata": {"source": "web", "verified": True}
    },
    additional_data={"title": "AI Article", "author": "John"}
)

# 查找文档
docs = client.documents.find("articles", {
    "data->>'category'": "tech"  # JSONB 路径查询
})

# 查找单个文档
doc = client.documents.find_one("articles", {"author": "John"})

# 通过 ID 查找
doc = client.documents.find_by_id("articles", doc_id)

# 更新文档（合并模式）
client.documents.update("articles", doc_id, {
    "data": {"views": 200, "new_field": "value"}  # 与现有 data 合并
})

# 更新文档（替换模式）
client.documents.update("articles", doc_id, {
    "data": {"views": 200}  # 完全替换 data
}, merge_document=False)

# 全文搜索
results = client.documents.search(
    "articles",
    query="machine learning",
    columns=["title", "data->>'content'"],
    limit=10
)

# 创建搜索索引
client.documents.create_search_index("articles", ["title", "data->>'content'"])

# 创建 JSONB 索引
client.documents.create_jsonb_index("articles", "data->'tags'")

# 高级 JSONB 查询
docs = client.documents.query_jsonb(
    "articles",
    jsonb_path="tags",
    query_type="contains",
    value=["ai"]
)

# 聚合
stats = client.documents.aggregate(
    "articles",
    aggregations={
        "count": "COUNT(*)",
        "avg_views": "AVG((data->>'views')::float)"
    },
    group_by=["data->>'category'"]
)

# 删除
client.documents.delete("articles", doc_id)
client.documents.delete_many("articles", {"author": "John"})
```

### 4. Query API (原始 SQL)

低级数据库操作。

```python
# 执行原始 SQL
results = client.query.execute(
    "SELECT * FROM users WHERE age > :age",
    {"age": 18}
)

# 执行并返回单个结果
user = client.query.execute_one(
    "SELECT * FROM users WHERE id = :id",
    {"id": 1}
)

# 执行并返回标量值
count = client.query.execute_scalar("SELECT COUNT(*) FROM users")

# 事务
with client.query.transaction() as tx:
    tx.execute("INSERT INTO users (name) VALUES (:name)", {"name": "John"})
    tx.execute("UPDATE stats SET count = count + 1")
    # 自动提交或回滚

# 创建表
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

# 创建索引
client.query.create_index("users", "email", unique=True)
client.query.create_index("users", ["name", "created_at"])

# 表信息
columns = client.query.get_table_columns("users")
indexes = client.query.get_table_indexes("users")
size = client.query.get_table_size("users")
exists = client.query.table_exists("users")

# 数据库信息
tables = client.query.list_tables()
db_size = client.query.get_database_size()

# 维护操作
client.query.vacuum("users")
client.query.analyze("users")

# 查询计划
plan = client.query.explain("SELECT * FROM users WHERE email = :email", {"email": "test@test.com"})

# CSV 导入导出
client.query.copy_from_csv("users", "/path/to/users.csv")
client.query.copy_to_csv("SELECT * FROM users", "/path/to/output.csv")
```

## 完整示例

### RAG 应用示例

```python
from searanch.database import DatabaseClient
import openai

# 初始化
client = DatabaseClient()
client.initialize()

# 创建向量表
client.vectors.create_table(
    "knowledge_base",
    dimension=1536,
    metadata_columns={
        "content": "TEXT",
        "source": "TEXT",
        "page": "INTEGER"
    }
)

# 创建索引
client.vectors.create_index("knowledge_base", index_type="hnsw")

# 插入文档
def index_document(content, source, page):
    embedding = openai.Embedding.create(
        input=content,
        model="text-embedding-ada-002"
    )["data"][0]["embedding"]
    
    return client.vectors.insert("knowledge_base", {
        "embedding": embedding,
        "content": content,
        "source": source,
        "page": page
    })

# 搜索相关文档
def search_knowledge(query, limit=5):
    embedding = openai.Embedding.create(
        input=query,
        model="text-embedding-ada-002"
    )["data"][0]["embedding"]
    
    return client.vectors.search(
        "knowledge_base",
        query_vector=embedding,
        limit=limit,
        distance_threshold=0.3
    )
```

### IoT 数据采集示例

```python
from searanch.database import DatabaseClient
from datetime import datetime, timedelta
import random

# 初始化
client = DatabaseClient()
client.initialize(extensions=['timescaledb'])

# 创建时序表
client.timeseries.create_table(
    "iot_metrics",
    time_column="timestamp",
    additional_columns={
        "device_id": "TEXT NOT NULL",
        "metric_type": "TEXT NOT NULL",
        "value": "FLOAT",
        "unit": "TEXT"
    },
    partition_interval="1 day",
    space_partition_column="device_id"
)

# 设置保留策略（保留 1 年数据）
client.timeseries.set_retention_policy("iot_metrics", "1 year")

# 创建连续聚合
client.timeseries.create_continuous_aggregate(
    "hourly_metrics",
    "iot_metrics",
    interval="1 hour",
    aggregations={"value": "AVG"},
    group_by=["device_id", "metric_type"]
)

# 插入数据
def record_metric(device_id, metric_type, value, unit):
    client.timeseries.insert("iot_metrics", {
        "timestamp": datetime.now(),
        "device_id": device_id,
        "metric_type": metric_type,
        "value": value,
        "unit": unit
    })

# 查询最近一小时的数据
def get_recent_metrics(device_id):
    return client.timeseries.query_range(
        "iot_metrics",
        start_time=datetime.now() - timedelta(hours=1),
        end_time=datetime.now(),
        filters={"device_id": device_id}
    )

# 获取每小时平均值
def get_hourly_averages(device_id):
    return client.query.execute("""
        SELECT * FROM hourly_metrics 
        WHERE device_id = :device_id
        ORDER BY bucket DESC
        LIMIT 24
    """, {"device_id": device_id})
```

## 配置

### 环境变量

```bash
# 数据库连接
DATABASE_URL=postgresql://user:password@localhost:5432/database

# SQL 调试
SQL_ECHO=true
```

### 连接参数

```python
client = DatabaseClient(
    database_url="postgresql://...",
    pool_size=10,          # 连接池大小
    max_overflow=20,       # 最大溢出连接
    pool_pre_ping=True,    # 连接健康检查
    echo=False             # SQL 日志
)
```

## 迁移指南

### 从旧 API 迁移

```python
# 旧 API
from searanch.database import DatabaseManager

db = DatabaseManager()
news = db.create_news_article(title="...", content="...")

# 新 API（推荐）
from searanch.database import DatabaseClient

client = DatabaseClient()
client.initialize()

# 使用 Document API 存储新闻
client.documents.create_table("news", additional_columns={
    "title": "TEXT",
    "content": "TEXT",
    "source": "TEXT",
    "published_at": "TIMESTAMPTZ"
})

client.documents.insert("news", {
    "data": {"sentiment": 0.5, "tags": ["finance"]},
    "title": "...",
    "content": "...",
    "source": "..."
})
```

## 注意事项

1. **pgvector 索引**: 数据量较大时（>1000条），建议创建 HNSW 索引以提高搜索性能
2. **TimescaleDB**: 确保数据库已安装 TimescaleDB 扩展
3. **连接池**: 高并发场景下适当增加 `pool_size`
4. **事务**: 使用 `session_scope()` 或 `transaction()` 确保数据一致性