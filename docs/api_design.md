# API 接口设计文档

> **版本**: v1.0 ｜ **日期**: 2026-10-30 ｜ **状态**: 已确认（源自架构文档 v1.1 第 4/6 节，独立成文）
> 本文件负责：**接口路径、请求参数、响应格式、错误码**。整体架构见 [architecture.md](architecture.md)。

---

## 1. 统一约定

- 前缀 `/api/v1`，JSON 传输；认证走请求头 `Authorization: Bearer <JWT>`。
- v1 验证方式：Swagger UI（`/docs`）、HTTPX、Postman。
- 成功响应外壳（HTTP 200）：

```json
{ "code": 0, "message": "ok", "data": { }, "request_id": "a1b2c3" }
```

- 失败响应外壳（HTTP 状态码如实反映错误，`code` 用于细分业务错误）：

```json
{ "code": 20001, "message": "订单不存在或无权访问", "data": null, "request_id": "a1b2c3" }
```

- Pydantic 校验失败（422）保留 FastAPI 默认结构，由全局处理器附加 `request_id`，不吞掉校验详情。

## 2. 认证与鉴权（v1 受控测试身份）

- v1 **不提供注册/登录接口**。受控测试身份由服务端脚本签发：

```
python scripts/issue_token.py --user-id 1 [--admin] [--expire-hours 24]
→ 输出 JWT，调用方放入 Authorization: Bearer <JWT> 即可。
```

- JWT：HS256，payload 含 `sub`（用户 id）、`is_admin`、`exp`；有效期 `JWT_EXPIRE_MINUTES`（默认 1440）从环境变量读取；`JWT_SECRET` 必须为随机强密钥。
- **禁止将客户端任意提交的 user_id 当作可信身份**：任何请求体/查询参数中的 user_id 一律不读取；身份只来自 JWT 解析结果。
- 所有需认证的路由通过 `get_current_user` 依赖注入；`/admin/*` 叠加 `require_admin`。该依赖与未来正式认证完全共用，接入注册登录时只新增签发入口（bcrypt），业务代码零改动。
- 限流：每用户每分钟 60 次起点（内存版，配置可调；Redis 引入后换分布式版）。

## 3. 错误码

| HTTP | code | 含义 | 触发场景 |
|---|---|---|---|
| 401 | 10001 | 未提供令牌或已过期 | 无 Authorization 头 / JWT 过期 |
| 401 | 10002 | 令牌无效 | 签名错误、被篡改 |
| 403 | 10003 | 无权限 | 普通用户访问 `/admin/*` |
| 404 | 20001 | 订单不存在或不属于当前用户 | **不区分"不存在"与"无权限"，防订单号枚举** |
| 404 | 20002 | 商品不存在 | 商品 id 无效 |
| 429 | 40001 | 触发限流 | 超过每分钟配额 |
| 502 | 50001 | 上游模型服务失败 | LLM 重试 2 次后仍失败（已降级） |
| 503 | 50002 | 依赖服务不可用 | 数据库连接失败（与 20001/50001 严格区分，日志与告警各自独立） |
| 500 | 50003 | 内部错误 | 未预期异常（详情只进日志，不出参） |

## 4. 接口清单

### 4.1 系统端点（无需认证）

```
GET /healthz    # 存活探针，恒 200（已实现）
GET /readyz     # 就绪探针：检查 DB 连通（SELECT 1），失败 503（已实现）
GET /docs       # Swagger UI（开发期验证用）
GET /metrics    # Prometheus 抓取（阶段 8 实现；访问控制见 architecture.md 4.2）
```

### 4.2 对话（核心入口，单轮）

```
POST /api/v1/chat            # 需 JWT（订单类问题必须知道"你是谁"）
请求: {
  "message": "我的订单 SYN202610280001 发货了吗？",
  "conversation_id": null,   # v1 单轮对话，字段预留；多轮在后期阶段
  "stream": false            # v1 只做非流式 JSON；阶段 9 测量完整链路时评估流式
}
响应 data: {
  "answer": "您的订单 SYN202610280001 已于 10 月 29 日发货，物流单号 ...，当前状态：运输中。",
  "answer_type": "template",     # template | generated | fallback | degraded | clarify
  "route": "order_query",        # 阶段八新增：处理路径
                                 # order_query | logistics_query | product_query
                                 # | kb_retrieval | combined | clarify
  "intents": ["order_status"],
  "sources": [                   # 答案依据，前端可渲染为可点击引用
    { "type": "order", "order_no": "...", "status": "shipped" }
  ],
  "confidence": "high"           # high | low；low 时提示转人工
}
说明: 知识库全部未命中不是错误 → HTTP 200 + answer_type=fallback + 拒答/转人工话术
组合查询（如"我的订单符合退货条件吗"）→ route=combined，sources 同时含
订单与知识库分块，订单信息以【订单信息】分区注入提示词。
```

### 4.3 订单与物流（结构化查询 API，与 chat 共用同一服务层）

```
GET /api/v1/orders?page=1&page_size=10         # 仅当前用户的订单，分页
GET /api/v1/orders/{order_no}                  # 他人订单号 → 404 (20001)
GET /api/v1/orders/{order_no}/logistics        # 物流时间线，同上权限校验
响应 data 示例: {
  "order_no": "SYN202610280001", "status": "shipped", "total_amount": "299.00",
  "receiver_phone": "138****1234",             # 出参已脱敏
  "items": [ { "product_name_snapshot": "保温杯", "quantity": 1 } ],
  "created_at": "2026-10-28T10:00:00Z"
}
```

### 4.4 商品

```
GET /api/v1/products/{id}
GET /api/v1/products?keyword=保温杯&category=&page=1&page_size=10   # 关键词走 pg_trgm
```

### 4.5 物流（按物流单号查询，2026-10-30 新增）

```
GET /api/v1/logistics/{tracking_no}    # 需认证；单号必须属于当前用户的订单，否则 404 (20001)
响应 data: { "tracking_no", "carrier", "status", "timeline",
             "updated_at", "order_no", "order_status" }   # 附带订单上下文
```

### 4.5 知识库管理（仅管理员）

```
POST   /api/v1/admin/faqs            # { question, answer, category, tags? } → 入库时自动分词 + 向量化
PUT    /api/v1/admin/faqs/{id}       # 内容变更 → 重新分词 + 重新向量化
DELETE /api/v1/admin/faqs/{id}       # 软删除（status=0），204
POST   /api/v1/admin/documents       # multipart 上传（md/txt/pdf）→ 分块 + 向量化，返回 document_id
POST   /api/v1/admin/rebuild-embeddings   # 202：后台任务全量重建向量（Embedding 模型变更时用）
```

## 5. 数据权限（订单归属校验）

- **第一层（数据层）**：所有订单查询 SQL 强制带 `user_id = :current_user_id`，该值只来自 JWT 解析结果，**永远不接收客户端传入的 user_id 参数**。
- **第二层（服务层）**：返回前断言 `order.user_id == current_user.id`，失败抛 404(20001)。
- 对外资源定位一律用 `order_no`（业务单号）而非内部 `id`，减少枚举面。
- 对"不存在"与"无权限"返回同一错误码与文案，防订单号枚举。
- **强制测试项**（实施阶段 4 验收）：集成测试构造"用户 B 请求用户 A 的 order_no"，断言 404 且响应体不含任何订单信息。
- 出参脱敏：`receiver_phone` → `138****1234`；地址只保留省市区；`password_hash` 永不返回。
