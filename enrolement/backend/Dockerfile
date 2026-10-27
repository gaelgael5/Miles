# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
# L'image reproduit la disposition du dépôt — <racine>/enrolement/backend et <racine>/socle
# — au lieu de bâtir dans /app. Raison : `miles-socle` est déclaré dans pyproject.toml au
# chemin relatif `../../socle/python`, et uv REFUSE de normaliser un chemin qui remonte
# au-dessus de son répertoire de base. Depuis /app, `../..` sortirait de la racine et la
# construction échouerait ; depuis /src/enrolement/backend, elle reste dans l'arborescence.
# Mesuré sur machine de test le 27/10/2026 — ne pas « simplifier » en revenant à /app.
WORKDIR /src/enrolement/backend
# Le socle arrive par un contexte de build additionnel, et non en élargissant le contexte
# à la racine du dépôt : l'image embarquerait sinon les autres produits.
COPY --from=socle . /src/socle/python
COPY pyproject.toml uv.lock ./
# --frozen : l'image se construit sur le verrou du dépôt, jamais sur une résolution
# du jour qui ferait tourner en test autre chose que ce qui a été validé.
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY migrations ./migrations
# --no-editable : l'image finale ne copie que le venv, sans les sources ; un paquet
# installé en mode éditable — le socle comme le produit — y pointerait vers un chemin absent.
RUN uv sync --frozen --no-dev --no-editable

# Cible des tests : lancée par scripts/run-integration-tests.sh sur machine de test.
FROM base AS test
COPY tests ./tests
RUN uv sync --frozen
ENTRYPOINT ["uv", "run", "--frozen", "pytest"]

FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --system --uid 10001 miles
COPY --from=base /opt/venv /opt/venv
COPY --from=base /src/enrolement/backend/migrations /app/migrations
ENV PATH=/opt/venv/bin:$PATH MILES_MIGRATIONS_DIR=/app/migrations PYTHONUNBUFFERED=1
USER miles
EXPOSE 8000
CMD ["uvicorn", "enrolement.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
