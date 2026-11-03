"""Le montage des routeurs du portail : quarante-cinq routeurs, cent dix-sept chemins.

Sorti de `app.py` le 3 novembre 2026 (enabler `82ec7d76`), qui dépassait la limite de 300
lignes du dépôt — pour moitié en imports de routeurs. Le découpage suit ce qui CHANGE pour
des raisons différentes : ici la liste de ce qui est servi, qui s'allonge à chaque écran ;
dans `app.py` la construction, la durée de vie et les DÉCLARATIONS DE SÉCURITÉ.

**Ce qui n'est PAS ici, et ne doit pas y venir** : le portillon (`auth_gate`), les deux
listes de passage (`signed_api_paths`, `system_api_paths`) et le routeur de pair dont la
première est DÉRIVÉE. Les séparer de leur dérivation rouvrirait précisément la panne que
cette dérivation rend inexprimable — un chemin ouvert loin de la vérification qui le garde.
"""

from __future__ import annotations

import urban_json_editor
from fastapi import FastAPI
from miles_socle.auth.api_auth import router as auth_router
from miles_socle.auth.api_preferences import router as preferences_router
from miles_socle.cultures.api_cultures import public_router as login_cultures_router
from miles_socle.cultures.api_cultures import router as cultures_router
from miles_socle.events.api_events import router as events_router
from miles_socle.health.api_health import router as health_router
from miles_socle.journal.api_journal import router as journal_router
from miles_socle.oidc.api_connectors import router as oidc_connectors_router
from miles_socle.oidc.api_login import router as oidc_login_router
from miles_socle.pairing.api_admin import router as pairing_router
from miles_socle.secrets.api_secrets import router as secrets_router
from miles_socle.secrets.api_secrets import types_router as secret_types_router

from miles.accounts.api_accounts import router as accounts_router
from miles.apikeys.api_apikeys import router as api_keys_router
from miles.chains.api_chains import router as chains_api_router
from miles.contracts.api_contracts import router as contracts_router
from miles.contracts.api_models import router as contract_models_router
from miles.datamodels.api_datamodels import router as data_models_router
from miles.gitaccess.api_gitaccess import connections_router
from miles.identities.api_identities import router as identities_router
from miles.oauth.api_authorize import router as oauth_authorize_router
from miles.oauth.api_clients import router as oauth_clients_router
from miles.oauth.api_public import router as oauth_public_router
from miles.obo.api_identity import router as identity_router
from miles.reference.api_countries import router as countries_router
from miles.reference.api_timezones import router as timezones_router
from miles.security.api_security import router as security_router
from miles.sources.api_sources import router as sources_router
from miles.storages.api_storages import router as storages_router
from miles.transform.api_catalog import router as catalog_router
from miles.transform.api_editor import JSLT_EDITOR_PATH
from miles.transform.api_editor import router as jslt_editor_router
from miles.transform.api_transform import chains_router
from miles.transform.api_transform import router as transform_router
from miles.workshop.api_branches import router as branches_router
from miles.workshop.api_branches import views_router as branch_views_router
from miles.workshop.api_domains import router as domains_router
from miles.workshop.api_holds import me_router as my_shelves_router
from miles.workshop.api_holds import router as holds_router
from miles.workshop.api_trads import router as trads_router
from miles.workshop.api_trads_keys import router as trads_keys_router
from miles.workshop.api_workshop import router as workshop_router
from miles.workspaces.api_workspace_cultures import router as workspace_cultures_router
from miles.workspaces.api_workspaces import router as workspaces_router


def include_api_routers(app: FastAPI) -> None:
    """Monte tout ce que le portail sert, hors routes signées et surface MCP."""
    app.include_router(health_router)
    # L'entretien des journaux partitionnés, appelé par un déclencheur d'HÔTE (décision du
    # 03/11/2026) : ni cookie ni personne derrière. Il vit dans /api et le portillon le
    # laisse passer par `system_api_paths` — déclaré ci-dessous DEPUIS le routeur qui le
    # porte, pour que le chemin et sa vérification ne puissent pas se séparer.
    app.include_router(journal_router)
    # La consultation du journal d'events (story 50bfcba0). DANS /api et hors de toute
    # liste de passage : le portillon exige donc une session, ce qui est le but — le
    # journal dit qui a fait quoi.
    app.include_router(events_router)
    app.include_router(auth_router)
    app.include_router(secrets_router)
    app.include_router(secret_types_router)
    app.include_router(cultures_router)
    app.include_router(login_cultures_router)
    app.include_router(oidc_connectors_router)
    app.include_router(oidc_login_router)
    app.include_router(security_router)
    app.include_router(workspaces_router)
    app.include_router(workspace_cultures_router)
    app.include_router(trads_router)
    app.include_router(trads_keys_router)
    app.include_router(connections_router)
    app.include_router(countries_router)
    app.include_router(timezones_router)
    app.include_router(data_models_router)
    app.include_router(domains_router)
    app.include_router(workshop_router)
    app.include_router(contracts_router)
    app.include_router(contract_models_router)
    app.include_router(branches_router)
    app.include_router(branch_views_router)
    app.include_router(holds_router)
    app.include_router(my_shelves_router)
    app.include_router(preferences_router)
    app.include_router(identities_router)
    app.include_router(transform_router)
    app.include_router(chains_router)
    app.include_router(catalog_router)
    app.include_router(chains_api_router)
    app.include_router(sources_router)
    app.include_router(storages_router)
    app.include_router(accounts_router)
    app.include_router(api_keys_router)
    app.include_router(identity_router)
    # L'appariement au module d'enrôlement, servi par le socle sous `/api/identity`.
    app.include_router(pairing_router)
    app.include_router(oauth_clients_router)
    app.include_router(oauth_authorize_router)
    app.include_router(oauth_public_router)
    app.include_router(jslt_editor_router)
    # Éditeur JSLT (urban-json-editor, 24/10/2026) : le Web Component et sa feuille de
    # style, servis par Miles lui-même — jamais depuis un CDN, comme Monaco. Monté SOUS
    # /api parce que c'est le seul préfixe que le nginx du front relaie déjà : ailleurs,
    # les assets tomberaient sur l'index de l'IHM.
    urban_json_editor.mount(app, JSLT_EDITOR_PATH)
