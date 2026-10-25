"""Le document OpenAPI qu'une source de données promet (Gael, 25/10/2026).

Une source déclare par quels moyens la donnée arrive ; ces moyens sont une API, et cette
API se LIT. Le document est DÉRIVÉ de la déclaration, jamais tenu à la main : une spec
écrite à côté dériverait de ce que la source fait vraiment, et personne ne le verrait.

Il décrit ce que la source promet, pas ce qui est hébergé : l'ingestion n'existe pas
encore. C'est délibéré — on veut relire le contrat avant de le construire.
"""

from __future__ import annotations

from typing import Any

from miles.datamodels.layout import MODEL_RE
from miles.sources.layout import MAX_BATCH, Entry, SourceDoc

OPENAPI_VERSION = "3.1.0"
# Préfixe des points d'entrée d'ingestion. Un seul endroit le définit : le jour où ils
# sont hébergés, c'est ici qu'on lira où ils doivent l'être.
INGEST_ROOT = "/ingest"


def document(doc: SourceDoc, schemas: dict[str, Any], storage_model: str | None) -> dict[str, Any]:
    """L'OpenAPI de cette source. `schemas` : le schéma inliné de chaque modèle source."""
    paths: dict[str, Any] = {}
    for rank, entry in enumerate(doc.entries):
        paths.update(_entry_paths(doc, rank, entry, schemas))
    described = {
        _schema_name(e.source_model): schemas[e.source_model]
        for e in doc.entries
        if e.source_model in schemas
    }
    return {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": doc.label or doc.name,
            "version": "1",
            "description": _description(doc, storage_model),
        },
        "paths": paths,
        "components": {"schemas": described},
    }


def _description(doc: SourceDoc, storage_model: str | None) -> str:
    cible = f" vers « {storage_model} »" if storage_model is not None else ""
    return (
        f"Entrées de données de la source « {doc.name} », qui alimente le storage "
        f"« {doc.storage} »{cible}. Chaque objet reçu traverse la chaîne de "
        "transformation déclarée avant d'être écrit. Document dérivé de la déclaration : "
        "il dit ce que la source promet, et se régénère avec elle."
    )


def _base(doc: SourceDoc, entry: Entry, rank: int) -> str:
    """Le chemin de cette entrée, qualifié par son modèle source.

    Qualifié TOUJOURS, même quand la source n'a qu'une entrée : sans cela, ajouter une
    seconde entrée changerait le chemin de la première, et un appelant déjà branché
    dessus casserait. Le rang ne sert qu'à départager deux entrées du même modèle.
    """
    match = MODEL_RE.match(entry.source_model)
    name = match["name"] if match is not None else f"entree-{rank + 1}"
    same = [e for e in doc.entries if e.source_model == entry.source_model]
    if len(same) > 1:
        name = f"{name}-{rank + 1}"
    return f"{INGEST_ROOT}/{doc.name}/{name}"


def _entry_paths(
    doc: SourceDoc, rank: int, entry: Entry, schemas: dict[str, Any]
) -> dict[str, Any]:
    base = _base(doc, entry, rank)
    ref = {"$ref": f"#/components/schemas/{_schema_name(entry.source_model)}"}
    known = entry.source_model in schemas
    paths: dict[str, Any] = {}
    if entry.modes.element:
        paths[base] = {
            "post": _operation(
                f"{doc.name}-{rank}-element",
                "Déposer un objet",
                f"Un seul objet du modèle « {entry.source_model} ».",
                {"application/json": {"schema": ref if known else {}}},
            )
        }
    if entry.modes.batch:
        items = ref if known else {}
        paths[f"{base}/batch"] = {
            "post": _operation(
                f"{doc.name}-{rank}-batch",
                "Déposer un lot",
                f"Un tableau d'objets du modèle « {entry.source_model} », {MAX_BATCH} au plus.",
                {
                    "application/json": {
                        "schema": {"type": "array", "items": items, "maxItems": MAX_BATCH}
                    }
                },
            )
        }
    if entry.modes.file:
        paths[f"{base}/file"] = {
            "post": _operation(
                f"{doc.name}-{rank}-file",
                "Déposer un fichier",
                "Le fichier est rangé en répertoire temporaire, puis lu en flux selon le "
                f"découpage « {entry.split} ». {_writing(entry.write_batch)}"
                + (", en une seule transaction." if entry.unified_transaction else "."),
                {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "properties": {"file": {"type": "string", "format": "binary"}},
                            "required": ["file"],
                        }
                    }
                },
            )
        }
    return paths


def _operation(
    operation_id: str, summary: str, description: str, content: dict[str, Any]
) -> dict[str, Any]:
    return {
        "operationId": operation_id,
        "summary": summary,
        "description": description,
        "requestBody": {"required": True, "content": content},
        "responses": {
            "202": {"description": "Lot pris en charge ; un identifiant d'ingestion est rendu."},
            "400": {"description": "Corps illisible ou hors du modèle source."},
            "403": {"description": "Appelant sans droit d'écriture sur cette source."},
        },
    }


def _writing(batch: int) -> str:
    """« tous les 1 objets lus » ne se lit pas : à l'unité, on le dit autrement."""
    if batch == 1:
        return "Écriture à chaque objet lu"
    return f"Écriture tous les {batch} objets lus"


def _schema_name(model: str) -> str:
    """« pudo/import-crm » → « pudo.import-crm » : un « / » couperait la référence."""
    return model.replace("/", ".")
