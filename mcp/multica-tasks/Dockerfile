# Бинарь CLI берём из образа backend того же тега, что выкачен на сервере (один бинарь на CLI и на платформу).
# При обновлении платформы тег поднимают здесь же: расхождение версий CLI и сервера ломает вызовы.
ARG MULTICA_BACKEND_IMAGE=ghcr.io/inoisy/multica-backend:852d1a2238bf147b6bb5f7c0c929ece86580c920
FROM ${MULTICA_BACKEND_IMAGE} AS multica-cli

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STATE_DIRECTORY=/state

RUN groupadd --gid 10001 mcp \
    && useradd --uid 10001 --gid mcp --no-create-home --shell /usr/sbin/nologin mcp \
    && install -d -o mcp -g mcp -m 0700 /state \
    && install -d -m 1777 /run/multica-cli
COPY --from=multica-cli /app/multica /usr/local/bin/multica
WORKDIR /app
COPY bin/ bin/
COPY multica_tasks/ multica_tasks/
COPY deploy/probe.py deploy/probe.py
USER 10001:10001
EXPOSE 8101
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python3", "-I", "/app/deploy/probe.py"]
ENTRYPOINT ["python3", "-I", "/app/bin/multica-tasks-mcp"]
