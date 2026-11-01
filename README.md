# 企业级智能客服 RAG 系统

电商场景智能客服后端：**结构化业务查询**（订单/物流/商品）+ **知识库问答**（退货/退款/物流/售后政策）+ **智能路由**（规则路由 + 组合查询），全链路可观测、可部署、可评估。

> 本项目为**简历/学习项目**，全部业务数据为合成测试数据（SYN/demo 标记），政策文档为模拟规则，不接入任何真实业务。

## 1. 项目背景

真实企业客服后端的要求是"**查得到、查得对、查得安全**"：
- 订单状态、物流轨迹这类**数字信息必须来自数据库**，不能交给大模型编；
- 政策类问题（"买完不想要了能退吗"）字面与知识库不同，需要**语义检索**；
- 同一个问题可能同时涉及业务数据与政策（"我的订单符合退货条件吗"），需要**多数据源编排**；
- 越权查询、模型幻觉、上游故障降级、监控定位，每一个都是面试高频点。

本项目按 13 个阶段从零实现，每一层都有测试与评估数据背书。

## 2. 核心功能

| 模块 | 说明 |
|---|---|
| 商品查询 API | 详情 / 关键词（pg_trgm 相似度排序）/ 分类过滤 / 分页，公开接口 |
| 订单与物流 API | 列表 / 详情 / 物流时间线；JWT 认证 + **双层归属校验** + 出参脱敏 |
| 知识库 | Markdown 文档 → 解析/清洗/分块/元数据 → 批量导入 + 质检脚本 |
| 检索 | jieba 中文分词 + tsvector 全文检索、pgvector HNSW 向量检索、**RRF 混合融合** |
| 智能问答 | 统一入口 `/api/v1/chat`：规则路由（业务查询/知识检索/组合查询/模糊澄清）+ 拒答 + 降级 |
| 监控追踪 | Prometheus 八族指标、Grafana 仪表盘、LangSmith 链路树（隐私边界） |
| 前端演示页 | `/` 单页聊天界面（纯 HTML/JS，零依赖） |

## 3. 技术栈

Python 3.12 · FastAPI · SQLAlchemy 2.x async + asyncpg · PostgreSQL 16 + pgvector + pg_trgm ·
jieba + tsvector 中文全文检索 · RRF 混合检索 · DeepSeek（生成）· 硅基流动 BGE-M3（Embedding）·
pytest + HTTPX（124 用例）· Locust（压测）· Prometheus + Grafana · LangSmith · Docker Compose · Alembic

## 4. 系统架构图

```mermaid
flowchart LR
    subgraph Client["客户端"]
        Web["聊天页 / Swagger / Postman"]
    end
    subgraph App["FastAPI（异步）"]
        MW["中间件：JWT / request_id / 日志 / 指标"]
        Routes["api/ 路由层（参数校验）"]
        SVC["services/ 服务层（业务规则 / 编排 / 脱敏）"]
        RET["retrieval/ 检索层（structured / keyword / vector / hybrid）"]
        TPL["模板回答引擎（订单/物流/商品，不经过 LLM）"]
        KB["kb_answer（拒答判断 → 提示词 → 生成/降级）"]
    end
    subgraph Data["PostgreSQL 16（同一实例）"]
        PG[("业务表 users/orders/logistics…")]
        VEC[("pgvector：知识分块向量 HNSW")]
        FTS["tsvector GIN：jieba 预分词全文索引"]
    end
    subgraph Ext["外部服务"]
        DS["DeepSeek（生成）"]
        EM["硅基流动 BGE-M3（Embedding）"]
        LS["LangSmith（追踪）"]
    end
    subgraph Ops["可观测性"]
        PM["Prometheus → Grafana"]
    end
    Web --> MW --> Routes --> SVC
    SVC --> RET --> PG & VEC & FTS
    SVC --> TPL
    SVC --> KB --> DS & LS
    SVC --> EM
    App --> PM
```

## 5. 核心数据流（一次 `/chat` 问答）

```
用户问题
  → JWT 认证（身份只来自令牌）
  → 规则意图路由（v3：结构化意图必须带用户上下文）
      ├─ 订单/物流/商品 → SQL 精确查询（WHERE 含 user_id 归属校验）→ 模板回答（P99<30ms，不经过 LLM）
      ├─ 政策类问题 → 混合检索（FTS∥向量 → RRF）→ 拒答判断（阈值 0.63）
      │        ├─ 无依据 → 明确拒答（不编造）
      │        └─ 有依据 → 提示词（引用/拒答/注入防护约束）→ DeepSeek 生成 + 真实来源引用
      └─ 组合问题（订单上下文 + 政策词）→ 查库 + RAG 双源（订单信息分区注入提示词）
  → 每次问答写入 query_logs（请求日志表）
```

## 6. 环境准备

- Windows / macOS / Linux + **Docker Desktop**；
- 端口要求：8000 / 5433 / 9090 空闲；
- `.env`：数据库配置 + DeepSeek / 硅基流动 / LangSmith 密钥（模板见 `.env.example`；`.env` 绝不进 Git 与镜像）。

## 7. 配置说明

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | 容器内自动覆盖为 `@postgres:5432`（compose 处理，无需手改） |
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` | 生成模型：`openai`（DeepSeek）或 `mock`（离线） |
| `EMBEDDING_PROVIDER` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` / `EMBEDDING_DIM` | BGE-M3；维度运行时校验 |
| `KB_REFUSAL_MIN_SCORE` | 拒答阈值（0.63，真实 BGE-M3 校准记录见 config.py） |
| `LANGSMITH_*` | 追踪开关（无 Key 零开销透传） |

## 8. 启动方式

```bash
docker compose config                       # 校验
docker compose up -d --build                # 构建启动（自动执行 alembic 迁移）
docker compose exec app python -m scripts.seed_data --orders 5000   # 业务数据
docker compose exec app python -m scripts.ingest_documents          # 知识库
docker compose exec app python -m scripts.issue_token --user-id 1   # 测试令牌
# 浏览器打开 http://127.0.0.1:8000/（聊天页）或 /docs（Swagger）
docker compose stop / start                 # 停止/重启（数据在卷中保留）
```

## 9. API 示例

```bash
TOKEN=...   # issue_token 输出
# 商品（公开）
curl "http://127.0.0.1:8000/api/v1/products?keyword=耳机"
# 订单（认证 + 归属校验；他人订单一律 404 防枚举）
curl -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/v1/orders"
# 智能问答
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"我的订单符合退货条件吗？"}' "http://127.0.0.1:8000/api/v1/chat"
# → {answer, answer_type, route(combined|order_query|kb_retrieval|clarify), sources[], confidence}
```

## 10. 自动化测试

```bash
PYTHONIOENCODING=utf-8 .venv\Scripts\python -m pytest -q    # 124 个用例
```
覆盖：认证与越权、归属校验与脱敏、意图路由（8 场景）、检索（RRF/分词/向量）、
RAG（引用/拒答/诱导/降级）、故障注入（超时/429/5xx/4xx，MockTransport 零生产调用）、
并发、指标低基数红线。详见 [docs/test_report.md](docs/test_report.md)。

## 11. 性能测试

```bash
# 数据准备（容器库）与运行
DATABASE_URL=postgresql+asyncpg://rag:rag_password@localhost:5433/rag_db \
  .venv\Scripts\python -m scripts.prepare_perf_data
.venv\Scripts\python -m locust -f loadtests/locustfile.py --headless --users 20 \
  --run-time 2m --host http://127.0.0.1:8000 --csv results/business --csv-full-history
```
三类结果（[docs/performance_report.md](docs/performance_report.md)）：
业务 API **P99≤28ms / 0 失败 / 59 RPS**（5000 订单规模）；
检索链路 **P99=490ms**（瓶颈=Embedding 294ms，本地检索仅 12ms）；
完整 RAG **P99=2.7s**（瓶颈=LLM 生成 1.24s，如实呈现不满足 500ms 目标）。

## 12. 已知问题和后续优化方向

**已知问题（如实声明）**
- v1 无注册登录（受控测试令牌），bcrypt 认证未接入；
- 完整 RAG 为非流式，首字延迟即完整延迟（TTFT 指标不适用）；
- 拒答阈值依赖真实 BGE-M3 校准，更换 Embedding 模型需重校准；
- 用户权重 ≠ 请求占比（压测分布偏差原因见性能报告 2.4）；
- 组合查询的 trace 含合成订单号（生产需 LangSmith 掩码策略，TODO 已记录）。

**后续优化方向（均附依据，见性能报告第 4 节）**：LLM 流式输出（SSE）、
热门问题缓存（Redis）、Embedding 批量化/本地化、水平扩容、admin 知识库管理接口、
Function Calling 版工具选择（工具注册表已预留）。

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 系统模块、调用关系、技术选型 |
| [docs/database_design.md](docs/database_design.md) | 表结构、主外键、索引、关联 |
| [docs/api_design.md](docs/api_design.md) | 接口、参数、响应、错误码 |
| [docs/rag_design.md](docs/rag_design.md) | 分块、Embedding、混合检索、回答生成 |
| [docs/test_report.md](docs/test_report.md) | 测试全景与覆盖说明 |
| [docs/performance_report.md](docs/performance_report.md) | 三类压测与瓶颈分析 |
| [docs/retrieval_eval_report.md](docs/retrieval_eval_report.md) | 检索三方案对比评估 |
| [docs/rag_eval_report.md](docs/rag_eval_report.md) | 76 题 RAG 评估 |
| [docs/interview_qa.md](docs/interview_qa.md) | 面试问题清单 |
