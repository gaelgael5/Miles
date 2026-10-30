from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict

from miles.reference.activation import EmptyChangeError, UnknownSlugsError
from miles.reference.model import Country, validate_culture
from miles.reference.service import CountriesService

# Le référentiel des pays, section Global du portail. Le préfixe est `/api/countries` et
# non `/api/referentials` : le mot « référentiel » désigne déjà trois autres choses dans ce
# produit — les référentiels d'objets ingérés, les référentiels de mapping de git, les
# storages — et une route qui le reprendrait se confondrait avec eux.
#
# Réservées à l'administrateur tant que les rôles n'existent pas : la passerelle refuse
# toute autre session, et aucune de ces routes n'est publique.
router = APIRouter(prefix="/api/countries")


def countries_service(request: Request) -> CountriesService:
    service: CountriesService = request.app.state.countries
    return service


Service = Annotated[CountriesService, Depends(countries_service)]


class CountryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    alpha2: str
    # Dérivé de CLDR à la lecture, dans la culture demandée. Jamais stocké, donc jamais
    # périmé : activer une culture de plus change ce champ sans aucune migration.
    label: str
    active: bool


class ActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slugs: list[str]
    active: bool


class ActivationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changed: list[str]


def _out(country: Country) -> CountryOut:
    return CountryOut(
        slug=country.slug, alpha2=country.alpha2, label=country.label, active=country.active
    )


@router.get("", response_model=list[CountryOut])
async def list_countries(
    service: Service,
    culture: Annotated[str | None, Query(max_length=40)] = None,
    only_active: bool = False,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> list[CountryOut]:
    """Les pays, avec leur libellé dans la culture demandée.

    `only_active` existe pour les écrans qui PROPOSENT un pays : ils n'en proposeront pas
    249. `q` filtre sur le code et sur le libellé dérivé — filtrer sur le seul code
    obligerait à connaître « DEU » pour trouver l'Allemagne.

    La culture est validée avant d'aller lire CLDR avec elle. Une forme inattendue est lue
    comme « pas de culture » : l'écran affiche alors les libellés de repli, ce qui vaut
    mieux qu'une liste vide pour un paramètre mal formé.
    """
    pays = await service.resolve_list(
        culture=validate_culture(culture), only_active=only_active, search=q
    )
    return [_out(p) for p in pays]


@router.post("/activation", response_model=ActivationResult)
async def set_activation(
    body: ActivationRequest, request: Request, service: Service
) -> ActivationResult | JSONResponse:
    """Active ou désactive exactement la sélection reçue. Rend ce qui a réellement changé.

    Un seul geste pour les deux sens, comme pour les cultures : l'écran envoie une
    sélection et un sens, et la moitié appliquée serait un état que personne n'a demandé.
    """
    try:
        changed = await service.resolve_set_active(request_author(request), body.slugs, body.active)
    except UnknownSlugsError as exc:
        # Les slugs fautifs sont NOMMÉS : ils viennent d'une saisie d'écran, et lui cacher
        # lesquels l'obligerait à tout retenter.
        return _error({"field": "slugs", "unknown": list(exc.slugs)})
    except EmptyChangeError:
        return _error({"field": "slugs"})
    return ActivationResult(changed=changed)


def _error(detail: object) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": detail}
    )
