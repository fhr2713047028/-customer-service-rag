"""集中读取环境变量配置。

所有敏感信息（密钥、连接串）只从环境变量 / .env 文件读取，
不要把任何 Key 写死在代码里（架构文档第 0.7 节原则 4）。
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # pydantic-settings 会自动读取项目根目录的 .env 文件；
    # 优先级：环境变量 > .env 文件 > 默认值
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env 中暂未用到的键（如后续阶段的 LLM Key）不会报错
    )

    app_name: str = "customer-service-rag"

    # 数据库连接：asyncpg 驱动（全程异步，架构文档第 0.1 节决策 3）
    # 默认值与 docker-compose.yml 中 postgres 服务保持一致
    database_url: str = "postgresql+asyncpg://rag:rag_password@localhost:5432/rag_db"

    # 连接池（架构文档 7.1 的起点值，阶段 9 压测后调优）
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_echo: bool = False  # 置 True 可在控制台看到每条 SQL，调试用

    # JWT（测试身份骨架，api_design.md 第 2 节）
    # 生产/演示前必须把 JWT_SECRET 换成随机强密钥（.env 中已生成随机值，勿改）
    jwt_secret: str = "dev-only-insecure-secret"
    jwt_expire_minutes: int = 1440
    jwt_algorithm: str = "HS256"

    # Embedding（阶段五）：provider 可配置 —— mock（离线确定性向量，默认）
    # 或 openai（硅基流动 BGE-M3 等 OpenAI 兼容接口）
    embedding_provider: str = "mock"
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_api_key: str = ""  # 只走环境变量；为空时只能使用 mock
    embedding_model: str = "BAAI/bge-m3"
    # 维度设计值 = BGE-M3 的 1024；真实接口运行时校验实际返回维度，
    # 不一致立即报错（防止换模型后新旧向量混用）
    embedding_dim: int = 1024
    embedding_timeout_seconds: int = 10

    # LLM（阶段七）：provider 可配置 —— mock（离线确定性生成，默认）或 openai（DeepSeek）
    # 模型名/base_url 以接入时服务商官方文档为准（已确认初始配置）
    llm_provider: str = "mock"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""  # 只走环境变量；为空时只能使用 mock
    llm_model: str = "deepseek-chat"
    llm_timeout_seconds: int = 30

    # LangSmith 链路追踪（阶段十）：默认关闭（Key 为空时所有追踪装饰器为透传）。
    # 启用后仅追踪问题/检索/耗时/回答，不带用户身份与订单号（core/tracing.py）
    langsmith_api_key: str = ""
    langsmith_project: str = "cs-rag"

    # 拒答阈值（阶段七）：向量 top-1 相似度低于此值 → 判定"无依据"并拒答。
    # 校准记录（真实 BGE-M3，2026-10-31，28 分块语料）：无依据题 top-1 区间
    # 0.458~0.671（均值 0.551），有依据题 0.582~0.818（均值 0.713）——
    # 区间中点 0.63。相较 mock 词袋向量（无法分离），真实语义模型下
    # 两类分布已基本拉开，但仍存在少量重叠，实际拒答/误拒率以评估报告为准。
    # 该阈值只用于拒答边界，不用于"高分即正确"的判定（rag_design 5.4 约定）。
    kb_refusal_min_score: float = 0.63


# 模块级单例：整个应用共用一份配置。
# 测试中如需覆盖，优先通过环境变量实现，而不是改代码。
settings = Settings()
