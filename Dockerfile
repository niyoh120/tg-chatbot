# syntax=docker/dockerfile:1

FROM python:3.9-slim-bullseye as base

ENV PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random \
    PYTHONUNBUFFERED=1 \
    BING_COOKIE_FILE=/data/cookie.json \
    TELEGRAM_BOT_DATA_PATH=/data/__data

WORKDIR /app

FROM base as builder

ENV PIP_DEFAULT_TIMEOUT=100 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.4.1

# Tiktoken requires Rust toolchain, so build it in a separate stage
RUN apt-get update && apt-get install -y gcc curl
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y && apt-get install --reinstall libc6-dev -y
ENV PATH="/root/.cargo/bin:${PATH}"

RUN pip install --upgrade pip && pip install "poetry==$POETRY_VERSION"

COPY pyproject.toml poetry.lock README.md ./

RUN poetry config virtualenvs.in-project true && \ 
    poetry run pip install --upgrade pip && \
    poetry install --only main --no-root --no-interaction --no-ansi

FROM base as final

COPY --from=builder /app/.venv ./.venv
COPY src ./src
COPY docker-entrypoint.sh .

CMD ["./docker-entrypoint.sh"]