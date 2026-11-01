# 应用镜像（阶段十一部署）
# 说明：
# - 基础镜像 python:3.12-slim（与架构要求的 Python 3.12 一致）；
# - pip 走清华镜像（本机网络对 PyPI 直连不稳定，实测镜像源可用）；
# - .env 不进镜像（.dockerignore 排除），密钥由 docker compose 运行时注入；
# - 数据库迁移在容器启动命令中执行（见 docker-compose.yml 的 command）。
FROM python:3.12-slim

WORKDIR /app

# 先装依赖（利用层缓存：代码变更时不需要重装）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
