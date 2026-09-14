# 使用与本地开发一致的 Python 3.12，并选择 slim 版本控制镜像体积。
FROM python:3.12-slim

# Python 日志直接输出到 Docker 日志；不生成容器内无用的 .pyc 缓存。
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先复制依赖清单，使业务代码变化时仍可复用依赖安装缓存层。
COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

# 生产进程不应使用 root 权限。该用户只需要读取应用代码并访问外部服务。
RUN groupadd --system app \
    && useradd --system --gid app --create-home app

COPY --chown=app:app src ./src

USER app

EXPOSE 8000

# 默认角色为 HTTP API。调度器容器复用同一镜像，并把启动命令覆盖为：
# python -m src.main scheduler
CMD ["python", "-m", "uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
