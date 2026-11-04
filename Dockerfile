# Container for running the test suite and the symbiont command line.
# `symbiont serve` binds 127.0.0.1 only, so inside a container the service is not reachable from
# the host. The image does not change that; use it for `uv run pytest -q` and CLI commands.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --group dev --no-install-project

COPY . .
RUN uv sync --frozen --group dev

# Some tests list tracked files with `git ls-files`. The build context carries no history, so
# give them a throwaway repository of the copied files.
RUN git init -q \
    && find . -type f -not -path './.git/*' -not -path './.venv/*' -print0 | xargs -0 git update-index --add -- \
    && git -c user.name=build -c user.email=build@localhost commit -q -m "container snapshot"

CMD ["symbiont", "serve", "--port", "7377"]
