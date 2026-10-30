# 单阶段镜像：前端构建产物随仓库提交（src/quantum_organizer/web/static），
# 因此镜像构建不需要 Node，也不需要联网下载前端依赖。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QORG_STATE_DIR=/state

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg libimage-exiftool-perl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

# 可选：用外部 locator 服务代替内置解析
# ENV QORG_GEOCODER_URL=http://quantum-locator:8899

EXPOSE 8080
VOLUME ["/data", "/state"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8080/healthz')"

ENTRYPOINT ["qorg"]
CMD ["serve", "--data", "/data", "--port", "8080"]
