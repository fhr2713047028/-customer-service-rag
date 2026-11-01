# 企业级智能客服 RAG 系统 · 系统架构文档

> **版本**: v1.2 ｜ **日期**: 2026-10-30 ｜ **状态**: 架构设计已确认，阶段二实施中
> 本文件是设计文档集的入口，负责：**系统模块、模块调用关系、技术选型、整体流程**。

## 文档索引

| 文档 | 职责 |
|---|---|
| 本文档 architecture.md | 系统模块、模块之间的调用关系、技术选型、整体流程 |
| [database_design.md](database_design.md) | 表结构、字段、主键、外键、索引、关联关系 |
| [api_design.md](api_design.md) | 接口路径、请求参数、响应格式、错误码 |
| [rag_design.md](rag_design.md) | 文档处理、分块、Embedding、混合检索、回答生成 |
| [development_plan.md](development_plan.md) | 各阶段交付物、测试方法、验收标准 |

---

## 0. 已确认决策汇总（评审结论，2026-10-30）

### 0.1 技术选型

| # | 决策 |
|---|---|
| 1 | Python 3.12+ + FastAPI（本机实测 Python 3.14.6 全栈依赖可用，待用户确认后更新版本表述） |
| 2 | PostgreSQL + pgvector（官方镜像 `pgvector/pgvector:pg16`） |
| 3 | SQLAlchemy 2.x **异步 ORM + asyncpg，全程异步数据库访问** |
| 4 | LLM：DeepSeek 常规聊天模型（**已确认初始配置**：`deepseek-chat` + `https://api.deepseek.com/v1`）；模型名/API 地址/密钥全部走环境变量，**接入时核对服务商官方文档与账号可用模型**，密钥不得提交 Git |
| 5 | Embedding：硅基流动 **BGE-M3**；维度按设计 1024，**以实际模型接口返回为准**（运行时校验，见 [rag_design.md](rag_design.md)） |
| 6 | FAQ 检索（**已确认**）：**jieba 分词 + PostgreSQL 全文检索（tsvector） + pgvector 向量检索**，RRF 融合；不引入 zhparser/pg_bigm；分词索引生成/更新/重建见 [database_design.md](database_design.md) 第 5 节 |
| 7 | 测试：pytest + HTTPX；压测：Locust；追踪：LangSmith；监控：Prometheus + Grafana |
| 8 | 部署：Docker Compose（服务规划见第 3.3 节） |
| 9 | Redis 不作为阶段一依赖，压测（实施阶段 9）后按需引入 |

### 0.2 性能口径

- 待验证目标 **QPS > 200、P99 < 500ms**，分三条路径分别测试（不得混算）：数据库精确查询 / FAQ 混合检索（不含 LLM 生成）/ 完整 RAG 问答（额外记录 TTFT、完整响应延迟、吞吐量、错误率）。
- **禁止**将 TTFT < 500ms 当作完整回答 P99 < 500ms 的证明；**禁止**预先声称达到任何性能目标。所有数字以实施阶段 9 的实测为准（方案见 [development_plan.md](development_plan.md) 第 4 节）。
- **压测预算上限 0 元（已确认）**：优先使用现有免费 API 额度；无额度时用 Mock 模型完成接口并发、数据库与检索组件性能测试；Mock 与真实 API 结果必须明确区分，**不得用 Mock 数据证明真实 RAG 链路达标**；付费测试需另行确认预算。

### 0.3 数据规模（全部合成数据，初始建议，非生产承诺）

| 表 | 初始规模（可配置默认值） |
|---|---|
| users | 100～500 条（默认 100） |
| products | 1,000 条 |
| orders | 5,000～10,000 条（默认 5,000） |
| logistics | 5,000～20,000 条（随订单状态生成，配置可调） |
| faqs | 200～500 条（默认 300） |
| kb_documents | 20～50 份（默认 30，分块后 kb_chunks 数百条） |

固定随机种子、可重复执行；数据自带合成标记（`demo_user_XXX`、`SYN` 订单号前缀、`@example.com`）。详见 [database_design.md](database_design.md) 第 6 节。

### 0.4 前端与用户体系

- v1 只做后端 API，用 **Swagger UI（`/docs`）、HTTPX 或 Postman** 验证接口；无前端、无 CORS 中间件。
- 保留 users/orders/products/logistics 模型及用户关联关系；**v1 不开发注册登录**。
- 身份机制：受控测试身份 —— 服务端脚本 `issue_token.py` 用 `JWT_SECRET` 签发 JWT。**禁止将客户端任意提交的 user_id 当作可信身份**（见 [api_design.md](api_design.md) 第 2 节）。
- 单轮问答，接口预留 `conversation_id`，不实现会话存储/历史管理/上下文记忆。

### 0.5 压测负载假设（仅用于初始压测，不代表真实电商流量）

**60%** 订单/物流/商品精确查询；**25%** FAQ 政策检索；**10%** 完整 RAG 问答；**5%** 组合问题与异常场景。四类任务独立定义、每任务恰好一次 HTTP 请求、不重复计数；±10% 敏感性测试。详见 [development_plan.md](development_plan.md) 第 4 节。

### 0.6 安全与稳定性要求（落地位置见第 4 节及各专题文档）

1. 所有数据库查询使用参数化 SQL 或受控 ORM 查询；
2. 订单查询校验认证身份与订单归属（[api_design.md](api_design.md) 第 5 节）；
3. **大模型不得获得任意 SQL 执行权限**（无 text-to-SQL、无数据库 function calling，第 4.1 节）；
4. 外部模型请求设置超时、有限重试、安全降级（第 3.2 节、[rag_design.md](rag_design.md) 第 6 节）；
5. 日志与追踪不泄露 API Key、密码及不必要的用户敏感信息（第 4.2 节）；
6. 检索不到可靠依据的政策问题 → 明确拒答或转人工（[rag_design.md](rag_design.md) 第 6 节）；
7. 订单不存在 / 无权访问 / 数据库异常分别设计错误处理（[api_design.md](api_design.md) 第 3 节）；
8. **监控端点不得默认向不可信网络公开**（第 3.3、4.2 节）。

### 0.7 贯穿全局的设计原则

| # | 原则 |
|---|---|
| 1 | 简单、可验证优先：不引入 LangChain/LlamaIndex，LLM 用 `openai` SDK（DeepSeek/硅基流动均兼容），检索直接写 SQL |
| 2 | 结构化数据优先 + 模板回答：订单/物流/商品问题不经过 LLM（防幻觉 + 性能的最大杠杆） |
| 3 | 权限在数据层强制：SQL 带 `user_id = :current_user`，服务层二次断言 |
| 4 | 密钥只走环境变量（`.env`，进 `.gitignore`；仓库只有 `.env.example`） |
| 5 | 不虚构数据/指标：合成数据明确标注；性能数字只来自实测 |
| 6 | 分阶段交付：每阶段含运行方法、测试方法、预期结果、常见错误排查 |

---

## 1. 系统模块与调用关系

### 1.1 整体架构

```mermaid
flowchart TB
    subgraph Client["调用方（v1: Swagger UI / HTTPX / Postman / Locust）"]
        API3["HTTP 调用方（Bearer JWT）"]
    end

    subgraph App["FastAPI 应用（app/）"]
        MW["中间件层<br/>鉴权(JWT) / 限流 / 日志(request_id) / Prometheus"]
        R["路由层 api/<br/>Pydantic 参数校验"]
        SVC["服务编排层 services/<br/>chat_service：意图 → 检索 → 回答"]
        INT["意图识别与路由<br/>阶段5: 规则版 / 阶段7: LLM 版"]
        RET["检索层 retrieval/<br/>structured / keyword(FTS) / vector / hybrid(RRF)"]
        SEG["app/core/text.py<br/>归一化 + jieba 分词（纯函数）"]
        TPL["模板回答引擎 structured_answer"]
        LLMG["LLM 网关 llm/client<br/>超时 / 重试 / 降级 / @traceable"]
        EMB["Embedding 客户端 embeddings/<br/>硅基流动 BGE-M3"]
    end

    subgraph Data["数据层（Docker 内部网络）"]
        PG[("PostgreSQL 16 + pgvector<br/>users / orders / order_items / products / logistics")]
        FTS[("faqs.search_text<br/>tsvector GIN 索引（全文检索）")]
        VEC[("faqs + kb_chunks 的 embedding<br/>VECTOR(1024) HNSW 索引")]
        TRI["products.name<br/>pg_trgm GIN（商品关键词）"]
    end

    subgraph Ext["外部服务（需 API Key）"]
        DS["DeepSeek API<br/>deepseek-chat（以官方文档为准）"]
        EAPI["硅基流动 API<br/>BAAI/bge-m3"]
        LS["LangSmith（SaaS）<br/>追踪与评估，脱敏配置"]
    end

    subgraph Ops["可观测性 / 压测（Docker 内部网络）"]
        PRO["Prometheus（仅内网抓取 /metrics）"]
        GRA["Grafana"]
        LOC["Locust（宿主机运行，独立于 compose）"]
    end

    API3 --> MW --> R --> SVC
    SVC --> INT --> RET
    SEG -.->|"分词/tsquery 生成"| RET
    RET -->|"参数化 SQL（含归属校验）"| PG
    RET -->|"to_tsvector @@ to_tsquery"| FTS
    RET -->|"embedding <=> 余弦"| VEC
    RET -->|"ILIKE + similarity"| TRI
    RET -->|"查询向量化"| EMB --> EAPI
    SVC -->|"结构化问题"| TPL
    SVC -->|"生成类问题"| LLMG --> DS
    LLMG -.->|"trace（脱敏后）"| LS
    App -.->|"/metrics（内网）"| PRO --> GRA
    LOC -->|"HTTP 压测（四类任务 60/25/10/5）"| App
```

### 1.2 一次问答的整体流程

```mermaid
sequenceDiagram
    participant C as 调用方
    participant A as FastAPI
    participant I as 意图路由
    participant R as 检索层
    participant DB as PostgreSQL (+pgvector)
    participant E as 硅基流动 Embedding
    participant L as DeepSeek
    participant T as 模板引擎

    C->>A: POST /api/v1/chat（JWT + message）
    A->>A: 鉴权 → 限流 → request_id
    A->>I: 意图识别（规则/LLM，可多意图）
    alt 结构化问题（订单/物流/商品）
        I->>R: 结构化查询（携带 current_user.id）
        R->>DB: SELECT ... WHERE order_no=:no AND user_id=:uid
        DB-->>R: 业务数据
        R-->>T: 模板渲染
        T-->>C: answer_type=template（压测路径 P1）
    else 知识类问题（政策/FAQ/文档）
        I->>R: 混合检索（FTS + 向量并行）
        R->>E: embed(question)
        E-->>R: 查询向量
        R->>DB: tsvector 查询 + HNSW 向量查询
        DB-->>R: 两路候选
        R->>R: RRF 融合 → 阈值过滤
        alt 命中 FAQ 且单数据源
            R-->>C: 返回 faq.answer + 来源，不调 LLM（压测路径 P2）
        else 命中知识文档 / 多数据源
            R-->>L: 分区上下文 + 约束提示词
            L-->>C: 生成回答 + 引用（压测路径 P3，记录 TTFT/完整延迟）
        else 全部低于阈值
            R-->>C: answer_type=fallback 拒答/转人工
        end
    end
```

### 1.3 模块职责与分层规则

| 层 | 目录 | 职责 | 禁止 |
|---|---|---|---|
| 路由层 | `app/api/` | HTTP 协议：参数校验、状态码、鉴权依赖 | 不写业务逻辑、不写 SQL |
| 服务层 | `app/services/` | 编排：意图 → 检索 → 模板/生成 → 响应组装 | 不直接处理 HTTP 细节 |
| 检索层 | `app/retrieval/` | 只负责"取数"（SQL/向量查询） | 不做业务判断 |
| 数据层 | `app/models/` `app/db/` | ORM 模型、引擎、会话 | 不引用上层 |
| 基础设施 | `app/core/` `app/llm/` `app/embeddings/` `app/middleware/` | 通用工具、外部网关、中间件 | 不写业务规则 |

调用方向只能自上而下 `api → services → retrieval/models`，禁止反向导入。这条规则让每一层都可以被单独测试。

---

## 2. 项目目录结构

```
customer-service-rag/
├── app/                            # 应用代码（唯一入口）
│   ├── main.py                     # FastAPI 实例：路由/中间件/启动事件；/healthz /readyz（已实现）
│   ├── config.py                   # pydantic-settings 读 .env（全部密钥/配置集中于此，已实现）
│   ├── api/
│   │   ├── deps.py                 # get_db / get_current_user / require_admin
│   │   └── routes/
│   │       ├── chat.py             # POST /api/v1/chat（核心 RAG 入口）
│   │       ├── orders.py           # GET /api/v1/orders、/orders/{order_no}、/logistics
│   │       ├── products.py         # GET /api/v1/products
│   │       └── admin.py            # 知识库管理（FAQ 增删改、文档上传、重建索引）
│   ├── core/
│   │   ├── errors.py               # 错误码常量 + AppError
│   │   ├── exceptions.py           # 全局异常处理器
│   │   ├── logging.py              # 结构化日志 + request_id + 脱敏过滤器
│   │   ├── security.py             # JWT 签发/校验、手机号/地址脱敏（bcrypt 后期加入）
│   │   └── text.py                 # 文本归一化 + jieba 分词 + tsquery 构造（纯函数，重点单测）
│   ├── db/
│   │   ├── base.py                 # DeclarativeBase（已实现）
│   │   ├── session.py              # async engine + 连接池配置（已实现）
│   │   └── init_db.py              # CREATE EXTENSION + 建表（开发用；生产走 alembic）
│   ├── models/                     # ORM 模型（对应 database_design.md 的 8 张表）
│   │   ├── user.py / order.py / order_item.py / product.py
│   │   └── logistics.py / faq.py / kb_document.py / kb_chunk.py
│   ├── schemas/                    # Pydantic 请求/响应模型
│   │   ├── common.py / chat.py / order.py / product.py / faq.py / kb.py
│   ├── services/
│   │   ├── chat_service.py         # 编排：意图 → 检索 → 模板/生成 → 响应
│   │   ├── intent.py               # 意图路由（规则版 → LLM 版）
│   │   ├── structured_answer.py    # 模板回答引擎
│   │   └── kb_answer.py            # 知识库回答（上下文组装、阈值、兜底）
│   ├── retrieval/
│   │   ├── structured.py           # 结构化精确查询（内含归属校验）
│   │   ├── keyword.py              # FTS 全文检索（jieba 分词由 core/text 提供）
│   │   ├── vector.py               # pgvector 向量检索（HNSW 余弦）
│   │   └── hybrid.py               # RRF 融合 + 去重 + 阈值过滤
│   ├── llm/
│   │   └── client.py               # DeepSeek 网关：AsyncOpenAI、超时/重试/降级、@traceable
│   ├── embeddings/
│   │   └── client.py               # BGE-M3 封装：维度运行时校验、批量接口
│   └── middleware/
│       ├── metrics.py              # Prometheus 指标（清单见第 3.4 节）
│       └── ratelimit.py            # 限流（内存版，后期换 Redis）
├── alembic/                        # 数据库迁移（实施阶段 2 引入）
│   ├── env.py
│   └── versions/
├── data/                           # 合成数据文件（标注 synthetic，不进 git 的大文件）
│   ├── faq/                        # FAQ 语料源文件（csv/jsonl，synthetic）
│   └── seed/                       # 种子数据源与生成清单（synthetic/demo）
├── scripts/
│   ├── seed_data.py                # 合成数据初始化：固定随机种子、幂等、规模可配
│   ├── issue_token.py              # 受控测试身份：签发 JWT（v1 认证入口）
│   ├── ingest_faq.py               # FAQ 导入：jieba 分词 → search_text + BGE-M3 → embedding
│   ├── ingest_documents.py         # 文档分块 + 向量化入库
│   └── rebuild_search_text.py      # 分词策略/词典变更时全量重建 search_text
├── test/                           # pytest 测试
│   ├── conftest.py                 # 夹具：测试库、HTTPX 客户端、签发测试 token
│   ├── unit/                       # 纯函数单测：RRF、分词/tsquery、脱敏、意图规则
│   └── integration/                # API 集成测试：真实 HTTP + 测试库
├── loadtests/
│   └── locustfile.py               # 四类任务 60/25/10/5，每任务恰好一次 HTTP 请求
├── monitoring/
│   ├── prometheus.yml              # 仅内网抓取 app /metrics
│   └── grafana/
│       └── dashboards/             # 面板 JSON
├── docs/                           # 设计文档集
│   ├── architecture.md             # 本文档：模块/调用关系/技术选型/整体流程
│   ├── database_design.md          # 表结构/字段/主外键/索引/关联
│   ├── api_design.md               # 接口路径/请求参数/响应格式/错误码
│   ├── rag_design.md               # 文档处理/分块/Embedding/混合检索/回答生成
│   ├── development_plan.md         # 阶段交付物/测试方法/验收标准
│   └── phase-XX-*.md               # 各实施阶段文档（运行/测试/预期/排查，随阶段产出）
├── .env.example                    # 环境变量模板
├── requirements.txt                # 依赖清单（已安装验证）
├── pytest.ini                      # pytest 配置（asyncio_mode/pythonpath）
├── Dockerfile                      # 应用镜像（阶段 10 完善）
├── docker-compose.yml              # 服务规划见 3.3（postgres 已落地）
├── .gitignore
└── README.md
```

**依赖清单**：运行时 `fastapi` `uvicorn[standard]` `sqlalchemy[asyncio]` `asyncpg` `pydantic` `pydantic-settings` `alembic` `pgvector` `openai` `httpx` `pyjwt` `jieba` `prometheus-client` `python-multipart`；测试 `pytest` `pytest-asyncio` `httpx` `faker`；压测 `locust`；实施阶段 7 追加 `langsmith`；生产化阶段追加 `bcrypt`、`pypdf`。

---

## 3. 基础设施设计

### 3.1 异步数据库连接池

- SQLAlchemy async engine + asyncpg：`pool_size=10`、`max_overflow=10`（**起点值**，按 200 QPS 短查询初估；阶段 9 实测调优，不预设结论）、`pool_pre_ping=True`、`pool_recycle=1800`、asyncpg 连接/命令超时 5s。
- 会话生命周期：**每请求一个 session**（`get_db` 异步生成器依赖），请求结束即归还连接；禁止跨请求共享、禁止后台任务复用已关闭会话。
- **禁止懒加载**：关联统一 `selectinload()` 预加载，避免 async 下隐式 IO 报错。
- 慢查询：阶段 8 开启 `log_min_duration_statement` 观察，压测时配合 `EXPLAIN` 验证索引生效。

### 3.2 外部模型调用

- 统一走 `AsyncOpenAI`（httpx 异步连接池）；DeepSeek 与硅基流动各持一个客户端实例（base_url/api_key/model 全部来自环境变量）。
- **超时**：LLM 30s、Embedding 10s（配置可调）。**有限重试**：仅对超时/5xx/429（尊重 Retry-After）重试，指数退避最多 2 次；4xx 不重试。**并发保护**：检索两路 `asyncio.gather` 并行；上游信号量上限 20。
- **降级**：见 [rag_design.md](rag_design.md) 第 6 节。
- 环境变量清单（`.env.example`，DeepSeek 模型名/base_url 以接入时官方文档为准）：

```
DATABASE_URL=postgresql+asyncpg://rag:rag_password@localhost:5432/rag_db
JWT_SECRET=<必须改为随机强密钥>
JWT_EXPIRE_MINUTES=1440
LLM_BASE_URL=https://api.deepseek.com/v1        # 以官方文档为准
LLM_API_KEY=sk-...
LLM_MODEL=deepseek-chat                          # 以官方文档为准
LLM_TIMEOUT_SECONDS=30
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_API_KEY=sk-...
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIM=1024                               # 以实际 API 返回维度为准，运行时不匹配即报错
RATE_LIMIT_PER_MINUTE=60
LANGSMITH_API_KEY=        # 阶段 7 起需要
LANGSMITH_PROJECT=cs-rag
```

### 3.3 Docker Compose 服务规划

| 服务 | 镜像 | 端口暴露 | 说明 |
|---|---|---|---|
| postgres | `pgvector/pgvector:pg16` | **仅内部网络**（开发期可临时映射 5432，生产不映射） | 数据卷 `pgdata`；healthcheck `pg_isready`；初始化 SQL 建扩展（**已落地**） |
| app | 项目 Dockerfile | 8000（开发期对宿主机） | `env_file: .env`；`depends_on: postgres(healthy)`；含 /healthz /readyz /docs /metrics（阶段 10 完善） |
| prometheus | `prom/prometheus` | **仅内部网络** | 抓取 `app:8000/metrics`（阶段 8 落地） |
| grafana | `grafana/grafana` | 3000（开发期，管理员密码走环境变量） | 面板 JSON；数据源指向 prometheus（阶段 8 落地） |
| locust | —（**非 compose 服务**） | — | 宿主机运行，避免压测机占用容器资源 |

- 对外只暴露业务端口 8000（开发期）与 Grafana 3000（开发期）；**/metrics 在生产由反代拦截或防火墙限制**（落实 0.6 第 8 条）。
- LangSmith 为 SaaS，无 compose 服务；Key 只走环境变量。

### 3.4 Prometheus 指标清单（阶段 8 落地）

`http_request_duration_seconds`（method/path/status 分桶）、`rag_answer_type_total{type}`、`rag_retrieval_duration_seconds{source}`、`rag_llm_duration_seconds`、`rag_llm_ttft_seconds`、`rag_upstream_call_duration_seconds{provider}`、`rag_errors_total{code}`、`db_pool_active_connections`；压测期间加慢查询日志 + `EXPLAIN` 抽查 + 资源曲线。

---

## 4. 全局安全约束

### 4.1 输入安全与 LLM 权限边界

- **SQL 注入**：全部参数绑定（`text()` + `:param` 或 ORM）；pgvector 参数用 `pgvector.sqlalchemy.Vector`；`ILIKE` 关键词作为绑定参数并转义 `%_\`。阶段 2 代码评审逐条检查"是否存在 f-string 拼 SQL"。
- **LLM 无 SQL 执行权限（硬性）**：LLM 只输出意图分类/实体提取/自然语言回答三类结果；**不做 text-to-SQL，不给模型任何数据库 function calling 工具**；所有数据库访问路径都是固定代码。
- **提示注入**：见 [rag_design.md](rag_design.md) 第 5.4 节分隔符方案。
- **越权**：管理员接口 `require_admin` + `/admin/*` 路由隔离。

### 4.2 日志、追踪脱敏与监控端点隔离

- 结构化 JSON 日志 + `request_id` 贯穿；脱敏过滤器：手机号、完整地址、密码字段、JWT 全文、API Key **一律不进日志**。
- LangSmith 追踪：默认只记录元数据（耗时、模型名、token 数、检索条数），**关闭输入输出文本记录或配置掩码**（阶段 7 落地）。
- **监控端点不默认向不可信网络公开**：compose 内 Prometheus 经内部网络抓取 `/metrics`，Postgres/Prometheus 不发布宿主机端口；生产部署由反代/防火墙仅放行业务端口。

---

## 5. 状态与下一步

- 阶段一（架构设计）已确认，全部决策记录于本文件第 0 节；待定事项（6 项）见 [development_plan.md](development_plan.md) 第 5 节。
- 阶段二实施中：模块 1「FastAPI 应用 + 配置 + 数据库连接」已完成并交付验证（/healthz /readyz 三态测试通过）。进度跟踪见 [development_plan.md](development_plan.md) 第 6 节。
