"""业务错误码与 AppError 异常体系（对应 api_design.md 第 3 节错误码表）。"""


class AppError(Exception):
    """所有业务异常的基类。

    全局异常处理器（core/exceptions.py）会把它转成统一响应外壳：
    {"code": ..., "message": ..., "data": null, "request_id": ...}
    """

    def __init__(self, message: str, *, code: int, http_status: int):
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status


class ProductNotFoundError(AppError):
    """商品不存在：404 / 20002。"""

    def __init__(self) -> None:
        super().__init__("商品不存在", code=20002, http_status=404)


class OrderNotFoundError(AppError):
    """订单不存在或不属于当前用户：404 / 20001。

    故意不区分"不存在"与"无权限"（api_design.md 第 3 节），防止订单号枚举。
    """

    def __init__(self) -> None:
        super().__init__("订单不存在或无权访问", code=20001, http_status=404)


class LogisticsNotFoundError(AppError):
    """物流记录不存在或不属于当前用户：404 / 20001（与订单同策略，防单号枚举）。"""

    def __init__(self) -> None:
        super().__init__("物流记录不存在或无权访问", code=20001, http_status=404)


class EmbeddingError(AppError):
    """Embedding 上游服务失败：502 / 50001（与 LLM 同码，见 api_design.md 错误码表）。"""

    def __init__(self, detail: str = "向量化服务失败") -> None:
        super().__init__(detail, code=50001, http_status=502)


class LLMError(AppError):
    """LLM 上游服务失败：502 / 50001。"""

    def __init__(self, detail: str = "上游模型服务失败") -> None:
        super().__init__(detail, code=50001, http_status=502)


class RerankError(AppError):
    """Rerank 上游服务失败：502 / 50001。"""

    def __init__(self, detail: str = "重排序服务失败") -> None:
        super().__init__(detail, code=50001, http_status=502)


class DatabaseUnavailableError(AppError):
    """数据库不可用：503 / 50002（api_design.md 错误码表：依赖服务不可用）。

    与订单不存在（20001）、LLM 失败（50001）严格区分（架构 6.4）。
    """

    def __init__(self) -> None:
        super().__init__("依赖服务不可用", code=50002, http_status=503)


class AuthMissingOrExpiredError(AppError):
    """未提供令牌或已过期：401 / 10001。"""

    def __init__(self) -> None:
        super().__init__("未提供令牌或已过期", code=10001, http_status=401)


class AuthInvalidTokenError(AppError):
    """令牌无效：401 / 10002。"""

    def __init__(self) -> None:
        super().__init__("令牌无效", code=10002, http_status=401)
