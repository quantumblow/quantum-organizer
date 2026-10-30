# 单阶段镜像：前端构建产物随仓库提交（src/quantum_organizer/web/static），
# 因此镜像构建不需要 Node，也不需要联网下载前端依赖。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QORG_STATE_DIR=/state

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg libimage-exiftool-perl \
    && rm -rf /var/lib/apt/lists/*

# quantum-locator 需要先发布到 PyPI，或先 `python -m build` 出 wheel 放到 docker/wheels/
ARG LOCATOR_SPEC="quantum-locator>=0.1,<1"

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY docker/wheels/ /tmp/wheels/
RUN pip install --no-cache-dir --upgrade pip \
    && (pip install --no-cache-dir /tmp/wheels/*.whl || pip install --no-cache-dir "$LOCATOR_SPEC") \
    && pip install --no-cache-dir .

# 可选：用外部 locator 服务代替内置解析
# ENV QORG_GEOCODER_URL=http://quantum-locator:8899

# 非 root 运行：容器写进素材目录的文件才不会变成 root 所有（宿主机 uid 通常是 1000）
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd -g ${APP_GID} qorg \
    && useradd -u ${APP_UID} -g ${APP_GID} -m -s /usr/sbin/nologin qorg \
    && mkdir -p /data /state \
    && chown -R ${APP_UID}:${APP_GID} /data /state /app
USER qorg

EXPOSE 8080
VOLUME ["/data", "/state"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8080/healthz')"

ENTRYPOINT ["qorg"]
CMD ["serve"]
