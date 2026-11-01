# 企业级智能客服 RAG 系统

电商场景智能客服后端：订单/物流/商品精确查询 + 退货/退款政策知识库检索 + 大模型问答。
技术栈：Python 3.12 / FastAPI / PostgreSQL 16 + pgvector / SQLAlchemy 2.x async /
jieba + tsvector 中文全文检索 / RRF 混合检索 / DeepSeek / 硅基流动 BGE-M3 /
Prometheus + Grafana / LangSmith。

> 本项目为简历项目，全部业务数据为合成测试数据（SYN/demo 标记），不接入真实业务。
> 设计文档见 [docs/](docs/)（architecture / database_design / api_design / rag_design / development_plan）。

## 快速开始（Docker 部署）

### 前置

- Docker Desktop（Windows）；
- 宿主机端口要求：**8000 / 5433 / 9090 空闲**（5432 被原生 PostgreSQL 占用，部署版映射 5433）；
- `.env` 已就位（数据库配置 + DeepSeek/硅基流动/LangSmith 密钥，绝不进 Git 与镜像）。

### 启动

```bash
# 1. 校验配置
docker compose config

# 2. 构建并启动（首次构建约 2~5 分钟；自动执行 alembic 迁移）
docker compose up -d --build

# 3. 查看状态（三个服务都应 healthy/Up）
docker compose ps

# 4. 查看日志
docker compose logs --tail=100 app

# 5. 验证服务
curl http://127.0.0.1:8000/healthz     # 存活
curl http://127.0.0.1:8000/readyz      # 就绪（数据库连通）
# Swagger UI: http://127.0.0.1:8000/docs
```

### 初始化数据（首次部署后执行一次）

```bash
# 业务测试数据（20 用户 / 40 商品 / 100 订单 / 物流 300 条记录）
docker compose exec app python -m scripts.seed_data

# 知识库（5 份模拟政策文档 → 28 分块 + 真实 BGE-M3 向量）
docker compose exec app python -m scripts.ingest_documents

# 质检
docker compose exec app python -m scripts.check_knowledge_quality

# 签发测试令牌（v1 无注册登录）
docker compose exec app python -m scripts.issue_token --user-id 1
```

### 停止 / 重启

```bash
docker compose stop      # 停止容器（数据保留在卷里）
docker compose start     # 再次启动（数据仍在）
docker compose down      # 删除容器（数据仍在卷里）
# ⚠️ docker compose down -v 会删除数据卷！执行前确认：会清空数据库全部数据。
```

### 监控与追踪

| 组件 | 地址 | 说明 |
|---|---|---|
| Prometheus | http://127.0.0.1:9090 | 抓取 app:8000/metrics（八族指标） |
| Grafana | http://127.0.0.1:3000 | 原生安装；数据源已指向 localhost:9090；仪表盘「智能客服 RAG - 运行时指标」 |
| LangSmith | https://smith.langchain.com | 项目 cs-rag；LLM/RAG 链路树（kb_answer→hybrid_search→llm.generate） |

### 常见问题排查

| 症状 | 原因与解决 |
|---|---|
| `docker compose up` 报端口占用 | 8000 被宿主机 uvicorn 占用（先停）；5433/9090 被其他程序占用（改 compose 映射） |
| 拉取镜像卡住 | 本机网络对 Docker Hub 直连不稳：`docker pull docker.m.daocloud.io/<镜像>` 后 `docker tag` 回原名 |
| app 日志 `Can't locate revision` | 数据卷挂到了旧库（历史迁移记录）——更换卷名（本仓库已用独立卷 `deploy_pgdata`） |
| 容器 Up 但接口 503 | `docker compose ps` 看 app 是否 healthy；`docker compose logs app` 看迁移是否成功 |
| chat 返回 fallback（无法确认） | 知识库未导入：执行 `docker compose exec app python -m scripts.ingest_documents` |
| ModuleNotFoundError | 依赖没写进 requirements.txt（本地临时安装不会进镜像），补清单后 `--build` |

## 开发模式（宿主机直接跑）

```bash
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
PYTHONIOENCODING=utf-8 .venv\Scripts\python -m pytest -q          # 124 个测试
PYTHONIOENCODING=utf-8 .venv\Scripts\python -m scripts.smoke_api  # API 冒烟
```
开发模式数据库使用原生 PostgreSQL 16（localhost:5432，账号 rag/rag_password）。
