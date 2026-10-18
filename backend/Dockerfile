# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
# --frozen : l'image se construit sur le verrou du dépôt, jamais sur une résolution
# du jour qui ferait tourner en test autre chose que ce qui a été validé.
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY migrations ./migrations
# --no-editable : l'image finale ne copie que le venv, sans /app/src ; un
# paquet installé en mode éditable y pointerait vers un chemin absent.
RUN uv sync --frozen --no-dev --no-editable

# Cible des tests : lancée par scripts/run-integration-tests.sh sur machine de test.
FROM base AS test
COPY tests ./tests
RUN uv sync --frozen
ENTRYPOINT ["uv", "run", "--frozen", "pytest"]

FROM python:3.12-slim AS runtime
RUN useradd --system --uid 10001 miles
COPY --from=base /opt/venv /opt/venv
COPY --from=base /app/migrations /app/migrations
ENV PATH=/opt/venv/bin:$PATH MILES_MIGRATIONS_DIR=/app/migrations PYTHONUNBUFFERED=1
USER miles
EXPOSE 8000
CMD ["uvicorn", "miles.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
