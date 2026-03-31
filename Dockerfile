FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e . \
    && chmod +x ./scripts/docker_start_web.sh ./scripts/docker_start_mcp.sh

EXPOSE 5080

CMD ["./scripts/docker_start_web.sh"]
