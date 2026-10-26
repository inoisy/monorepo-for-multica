FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STATE_DIRECTORY=/state

RUN groupadd --gid 10001 mcp \
    && useradd --uid 10001 --gid mcp --no-create-home --shell /usr/sbin/nologin mcp \
    && install -d -o mcp -g mcp -m 0700 /state
WORKDIR /app
COPY bin/ bin/
COPY multica_tasks/ multica_tasks/
COPY deploy/probe.py deploy/probe.py
USER 10001:10001
EXPOSE 8101
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python3", "-I", "/app/deploy/probe.py"]
ENTRYPOINT ["python3", "-I", "/app/bin/multica-tasks-mcp"]
