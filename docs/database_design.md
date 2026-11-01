# 数据库设计文档

> **版本**: v1.1 ｜ **日期**: 2026-10-30 ｜ **状态**: 已按用户 2026-10-30 确认的表名清单修订并建表
> 本文件负责：**表结构、字段、主键、外键、索引、关联关系**。整体架构见 [architecture.md](architecture.md)，入库流程见 [rag_design.md](rag_design.md)。

**v1.1 变更记录（2026-10-30，用户确认）**：
1. `kb_documents` / `kb_chunks` 更名为 `knowledge_documents` / `knowledge_chunks`；
2. 新增 `query_logs`（必要的请求日志/查询记录）；
3. `faqs` 未列入用户清单，**暂不建表**（FAQ 功能后续如需，再行添加或改存 knowledge_documents）；
4. `knowledge_chunks.embedding` 向量列**暂缺**——原生 PostgreSQL 未装 pgvector 扩展（待用户选择安装方案），扩展装好后通过一次迁移追加该列 + HNSW 索引；
5. 数据库实例：原生 PostgreSQL 16.15（Windows 服务 postgresql-x64-16），库 `rag_db`，角色 `rag`。

---

## 1. 设计概览

- 数据库：原生 PostgreSQL 16 + pgvector（**待装**）+ pg_trgm（已装）。业务数据与向量同库，不引入独立向量数据库。
- 共 **8 张表**，拆分原因：**order_items**（一笔订单多件商品）；**knowledge_chunks**（向量检索粒度是分块，需溯源回文档）。
- 命名约定：表名复数小写、主键 `id BIGSERIAL`、时间戳 `TIMESTAMPTZ`、金额 `NUMERIC(12,2)`。

## 2. ER 图

```mermaid
erDiagram
    users ||--o{ orders : "user_id"
    orders ||--o{ order_items : "order_id"
    products ||--o{ order_items : "product_id"
    orders ||--o| logistics : "order_id (1:1)"
    knowledge_documents ||--o{ knowledge_chunks : "document_id"
    users ||--o{ query_logs : "user_id（可空，SET NULL）"

    users {
        bigint id PK
        varchar username UK
        varchar phone UK
        varchar password_hash "可空（正式认证阶段启用）"
        boolean is_admin
    }
    orders {
        bigint id PK
        varchar order_no UK
        bigint user_id FK
        varchar status "CHECK 约束"
        numeric total_amount
    }
    order_items {
        bigint id PK
        bigint order_id FK
        bigint product_id FK
        varchar product_name_snapshot
        integer quantity
    }
    products {
        bigint id PK
        varchar sku UK
        varchar name
        text description
        numeric price
    }
    logistics {
        bigint id PK
        bigint order_id FK_UK
        varchar tracking_no
        varchar carrier
        jsonb timeline
    }
    knowledge_documents {
        bigint id PK
        varchar title
        varchar source
        varchar category
    }
    knowledge_chunks {
        bigint id PK
        bigint document_id FK
        integer chunk_index
        text content
    }
    query_logs {
        bigint id PK
        bigint user_id FK "可空"
        varchar endpoint
        text message
        varchar answer_type
    }
```

## 3. 表定义（字段 / 主键 / 外键 / 索引 / 约束）

### 3.1 users — 用户信息

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | BIGSERIAL | **主键** | |
| username | VARCHAR(64) | **UNIQUE NOT NULL** | 合成数据统一 `demo_user_XXX` |
| phone | VARCHAR(20) | **UNIQUE** | API 出参脱敏（`138****1234`） |
| email | VARCHAR(255) | **UNIQUE** | 合成数据用 `@example.com` |
| password_hash | VARCHAR(255) | 可空 | v1 不使用；正式认证阶段启用 + bcrypt |
| is_admin | BOOLEAN | NOT NULL DEFAULT false | |
| status | SMALLINT | NOT NULL DEFAULT 1 | 1 正常 / 0 禁用 |
| created_at / updated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | |

**索引**：username / phone / email 各一个 UNIQUE 索引（由约束自动创建）。

### 3.2 orders — 订单信息

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | BIGSERIAL | **主键** | 内部主键，不对外 |
| order_no | VARCHAR(32) | **UNIQUE NOT NULL** | 对外订单号；合成数据以 `SYN` 开头 |
| user_id | BIGINT | **NOT NULL，外键 → users(id)** | 归属校验的核心列 |
| status | VARCHAR(32) | NOT NULL + **CHECK**（8 态：pending_payment/paid/shipped/delivered/completed/cancelled/refunding/refunded） | VARCHAR+CHECK 而非 enum：扩展只需一次迁移 |
| total_amount | NUMERIC(12,2) | NOT NULL | |
| receiver_name / receiver_phone / receiver_address | VARCHAR | 可空 | 出参脱敏（手机号打码、地址只留省市区） |
| remark | TEXT | 可空 | |
| created_at / updated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | |

**索引**：`(order_no)` UNIQUE；`(user_id, created_at DESC)` 复合索引（"我的订单"列表与最近 N 单）。

### 3.3 order_items — 订单商品明细

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | BIGSERIAL | **主键** | |
| order_id | BIGINT | **NOT NULL，外键 → orders(id) ON DELETE CASCADE** | |
| product_id | BIGINT | **外键 → products(id)**，可空 | 商品下架仍能答历史订单 |
| product_name_snapshot / sku_snapshot | VARCHAR | NOT NULL | **下单时快照**，不随商品表变更 |
| price_snapshot | NUMERIC(12,2) | NOT NULL | 下单时价格 |
| quantity | INT | NOT NULL DEFAULT 1 | |

**索引**：`(order_id)`。

### 3.4 products — 商品信息

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | BIGSERIAL | **主键** | |
| sku | VARCHAR(64) | **UNIQUE NOT NULL** | |
| name | VARCHAR(255) | NOT NULL | |
| category | VARCHAR(64) | 可空 | |
| description | TEXT | 可空 | |
| price | NUMERIC(12,2) | NOT NULL | |
| stock | INT | NOT NULL DEFAULT 0 | |
| status | VARCHAR(16) | NOT NULL + **CHECK**：on_sale/off_sale | |
| created_at / updated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | |

**索引**：`(sku)` UNIQUE；`name` 上 **pg_trgm GIN**（关键词搜索；迁移与 init_db.py 中以原始 SQL 创建）。

### 3.5 logistics — 物流记录

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | BIGSERIAL | **主键** | |
| order_id | BIGINT | **UNIQUE NOT NULL，外键 → orders(id)** | v1 一单一物流 |
| tracking_no | VARCHAR(64) | NOT NULL | |
| carrier | VARCHAR(32) | 可空 | |
| status | VARCHAR(32) | NOT NULL + **CHECK**（created/picked_up/in_transit/out_for_delivery/delivered/exception） | |
| timeline | JSONB | NOT NULL DEFAULT '[]' | 轨迹数组 `[{"time","location","description"}]` |
| updated_at | TIMESTAMPTZ | NOT NULL | 每次同步物流时由代码更新 |

**索引**：`(tracking_no)`。

### 3.6 knowledge_documents — 知识文档元数据

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | BIGSERIAL | **主键** | |
| title | VARCHAR(255) | NOT NULL | |
| source | VARCHAR(512) | 可空 | 来源文件名/URL |
| doc_type | VARCHAR(16) | NOT NULL + **CHECK**：md/txt/pdf | |
| category | VARCHAR(32) | NOT NULL | |
| status | SMALLINT | NOT NULL DEFAULT 1 | 1 生效 / 0 停用 |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | |

### 3.7 knowledge_chunks — 文档分块及向量

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | BIGSERIAL | **主键** | |
| document_id | BIGINT | **NOT NULL，外键 → knowledge_documents(id) ON DELETE CASCADE** | 溯源回文档 |
| chunk_index | INT | NOT NULL | **UNIQUE(document_id, chunk_index)** |
| content | TEXT | NOT NULL | 分块正文 |
| metadata | JSONB | NOT NULL DEFAULT '{}'（迁移 #2，2026-10-31） | 分块元数据：{doc_title, section, source_line, char_count} |
| embedding | VECTOR(1024) | 可空（早期分块先入库后补向量）；迁移 #3（2026-10-31）+ HNSW 索引已建 | BGE-M3 维度，运行时校验实际返回 |

### 3.8 query_logs — 必要的请求日志/查询记录

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | BIGSERIAL | **主键** | |
| user_id | BIGINT | **外键 → users(id) ON DELETE SET NULL**，可空 | 匿名请求可记录；用户删除后日志保留 |
| endpoint | VARCHAR(255) | NOT NULL | 请求路径 |
| message | TEXT | 可空 | 用户输入（写入前脱敏） |
| intents | VARCHAR(32)[] | 默认 '{}' | 识别出的意图列表 |
| answer_type | VARCHAR(32) | 可空 | template / faq / generated / fallback |
| latency_ms | INT | 可空 | 请求耗时 |
| http_status | SMALLINT | 可空 | 响应状态码 |
| error_code | VARCHAR(16) | 可空 | 业务错误码 |
| request_id | VARCHAR(64) | 可空 | 与结构化日志关联 |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | |

**索引**：`(user_id, created_at)`、`(request_id)`。数据保留/清理策略在可观测性阶段（实施阶段 8）定义。

## 4. 数据库基础设施与关键 DDL

- 实例：原生 PostgreSQL 16.15（Windows 服务 `postgresql-x64-16`，超级用户 `postgres`）；应用账号 `rag`（密码 `rag_password`），库 `rag_db`。
- 已装扩展：`pg_trgm`（随安装包）。**待装**：`pgvector`（用户待选方案：A 社区预编译 DLL / B 官方源码编译 / C Docker）。
- 建表权威路径：`alembic upgrade head`（迁移 `79330a6f94ab`）；开发快捷路径 `python -m app.db.init_db` 与之保持一致。
- knowledge_documents 关键 DDL（其余表以 alembic 迁移为准）：

```sql
CREATE TABLE knowledge_documents (
    id         BIGSERIAL PRIMARY KEY,
    title      VARCHAR(255) NOT NULL,
    source     VARCHAR(512),
    doc_type   VARCHAR(16) NOT NULL CHECK (doc_type IN ('md', 'txt', 'pdf')),
    category   VARCHAR(32) NOT NULL,
    status     SMALLINT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 5. 数据规模与合成数据约定（种子脚本阶段执行）

| 表 | 初始规模（可配置默认值） | 合成标记 |
|---|---|---|
| users | 100～500（默认 100） | `demo_user_XXX`、`@example.com` |
| products | 1,000 | 合成内容 |
| orders | 5,000～10,000（默认 5,000） | 订单号 `SYN` 前缀 |
| logistics | 5,000～20,000（随订单状态生成） | 单号 `SYN` 前缀 |
| knowledge_documents | 20～50（默认 30） | 文档头标注 synthetic |

- 全部由脚本生成、固定随机种子、可重复执行、幂等；文件与数据双重标注 synthetic/demo。
- **这些规模是初始建议，不是生产规模承诺。**
