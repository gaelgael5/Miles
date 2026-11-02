"""Faire servir une version de paramétrage à la stack, comme l'enrôlement le fait.

Écrit ici parce que TROIS suites en ont besoin — les tables de storage, la recherche, et
les clés d'API — et que les deux premières en portaient chacune leur copie. Une troisième
aurait figé la divergence : le jour où l'ordre d'hébergement gagne un champ, une copie
oubliée ferait rougir une suite sur une signature, loin de ce qu'elle éprouve.
"""

from __future__ import annotations

import httpx
from miles_socle.signing.calls import ORIGIN_HEADER, SIGNATURE_HEADER, sign_call
from miles_socle.signing.hosting import HOSTED_VERSION_PATH, HostedVersionIn
from miles_socle.signing.keys import load_private_key
from miles_socle.testing.enrolment_double import EXPECTED_CODE, PEER_ORIGIN, EnrolmentDouble

from tests.integration.bundles import VersionFabriquee
from tests.integration.environnement_stack import EnvironnementStack

WORKSPACE = "reseau-ferroviaire"


async def apparie(stack: EnvironnementStack) -> None:
    """Apparie la stack à la contrepartie : sans quoi aucun ordre n'est accepté."""
    ouverte = await stack.client.post(
        "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": "Recette nord"}
    )
    assert ouverte.status_code == 202, ouverte.text
    conclu = await stack.client.post("/api/identity/pairing/confirm", json={"code": EXPECTED_CODE})
    assert conclu.status_code == 200, conclu.text


async def ordonne(
    stack: EnvironnementStack, double: EnrolmentDouble, version: VersionFabriquee
) -> httpx.Response:
    """Envoie l'ordre d'héberger `version`, signé comme l'enrôlement le signe.

    Rejouable : c'est ainsi qu'on éprouve qu'un ordre resservi ne refait rien.
    """
    double.bundles[version.commit] = version.bundle
    corps = (
        HostedVersionIn(workspace_id=WORKSPACE, number=version.number, commit=version.commit)
        .model_dump_json()
        .encode("utf-8")
    )
    entetes = {
        ORIGIN_HEADER: PEER_ORIGIN,
        "Content-Type": "application/json",
        SIGNATURE_HEADER: sign_call(
            load_private_key(double.keypair.private_pem),
            origin=PEER_ORIGIN,
            method="POST",
            target=HOSTED_VERSION_PATH,
            body=corps,
        ),
    }
    recu = await stack.anonymous().post(HOSTED_VERSION_PATH, content=corps, headers=entetes)
    assert recu.status_code == 200, recu.text
    return recu


async def sert(
    stack: EnvironnementStack, double: EnrolmentDouble, version: VersionFabriquee
) -> None:
    """Apparie puis fait servir : le point de départ de tout test qui lit un paramétrage."""
    await apparie(stack)
    await ordonne(stack, double, version)
