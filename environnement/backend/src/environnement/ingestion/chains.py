"""La chaîne qu'une entrée de source nomme, lue dans l'arbre servi et compilée.

L'entrée déclare un SLUG de chaîne ; la chaîne vit dans `transformations/<slug>/` avec son
enchaînement et un template par étape. Rien n'est en base : c'est du paramétrage versionné,
et c'est `git revert` qui en fait le retour arrière (invariant du dépôt).

**Le profil d'écriture est confronté ICI AUSSI**, et non seulement du côté qui édite :
`compile_chain` le fait. Un template vient d'un fichier de git, que personne ne garantit
avoir été écrit par un écran — une branche se modifie aussi à la main, depuis la forge. Le
refuser à l'exécution est le même fail closed qu'à la saisie.
"""

from __future__ import annotations

from miles_socle.parametrage.chains import chain_path, read_chain, template_path
from miles_socle.parametrage.refs import ReadFile
from miles_socle.transform.chain import Chain, ChainInvalidError, StepSpec, compile_chain


class ChainUnreadable(Exception):
    """La chaîne nommée par l'entrée manque, est illisible, ou sort du profil.

    Un seul type pour les trois : du point de vue du dépôt, aucune ne se corrige en
    réessayant, et toutes se corrigent dans le module de paramétrage. `detail` dit
    laquelle, pour le compte-rendu.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


async def file_load_chain(read: ReadFile, slug: str) -> Chain:
    """Lit et compile la chaîne de ce slug. Une chaîne SANS étape est licite.

    Licite, et c'est voulu : elle rend le message inchangé, ce qui est exactement ce
    qu'on veut d'une source dont le modèle d'entrée est déjà le modèle du storage. Un
    refus forcerait à écrire un template identité pour ne rien faire.
    """
    doc = read_chain(await read(chain_path(slug)))
    if doc is None:
        raise ChainUnreadable(chain_path(slug))
    specs: list[StepSpec] = []
    for step in doc.steps:
        source = await read(template_path(slug, step))
        if source is None:
            raise ChainUnreadable(template_path(slug, step))
        specs.append(StepSpec(source, step.target))
    try:
        return compile_chain(specs)
    except ChainInvalidError as refus:
        # Le rang de l'étape fautive et son code : sans eux, « chaîne illisible » sur une
        # chaîne de douze étapes n'envoie nulle part.
        premier = refus.problems[0]
        raise ChainUnreadable(f"{slug}#{premier.step}:{premier.code}") from None
