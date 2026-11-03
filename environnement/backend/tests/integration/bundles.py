"""Des bundles git fabriqués avec un VRAI git, pour les donner à la contrepartie.

Le socle n'en fabrique pas, et c'est voulu : sa doublure ne fait que SERVIR ce qu'on lui
donne. Ce qu'on éprouve ici est que ce module VÉRIFIE le commit qu'on lui ordonne avant de
poser l'arbre — et ce contrôle ne se vérifie qu'avec des bundles réels, dont l'un porte
délibérément autre chose que ce qu'on annonce.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

AUTHOR = ("-c", "user.name=Alice", "-c", "user.email=alice@annuaire.invalid")


def git(*args: str, cwd: Path | None = None) -> str:
    out = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return out.stdout


@dataclass(frozen=True)
class VersionFabriquee:
    number: int
    commit: str
    bundle: bytes
    # Les fichiers que cette version porte, pour que le test LISE l'arbre posé.
    fichiers: tuple[str, ...]


def fabrique(tmp_path: Path) -> dict[int, VersionFabriquee]:
    """Deux versions : la seconde SUPPRIME un fichier de la première.

    La suppression n'est pas un détail d'essai : un arbre posé par recopie laisserait le
    fichier retiré en place, et la stack servirait un paramétrage que personne n'a publié.
    """
    depot = tmp_path / "depot"
    git("init", "-q", "-b", "main", str(depot))
    (depot / "ecran.json").write_text('{"v": 1}\n', encoding="utf-8")
    git("add", "-A", cwd=depot)
    git(*AUTHOR, "commit", "-q", "-m", "c1", cwd=depot)
    git(*AUTHOR, "tag", "-a", "version/1", "-m", "Première", cwd=depot)
    (depot / "scenario.json").write_text('{"v": 2}\n', encoding="utf-8")
    git("rm", "-q", "ecran.json", cwd=depot)
    git("add", "-A", cwd=depot)
    git(*AUTHOR, "commit", "-q", "-m", "c2", cwd=depot)
    git(*AUTHOR, "tag", "-a", "version/2", "-m", "Réseau ferroviaire", cwd=depot)

    fabriquees: dict[int, VersionFabriquee] = {}
    for number, fichiers in ((1, ("ecran.json",)), (2, ("scenario.json",))):
        paquet = tmp_path / f"v{number}.bundle"
        git("bundle", "create", str(paquet), f"version/{number}", cwd=depot)
        commit = git("rev-parse", f"version/{number}^{{commit}}", cwd=depot).strip()
        fabriquees[number] = VersionFabriquee(number, commit, paquet.read_bytes(), fichiers)
    return fabriquees


def bundle_substitue(tmp_path: Path, number: int, sur_commit: str) -> bytes:
    """Un bundle dont `version/<number>` EXISTE mais pointe sur `sur_commit`.

    C'est la SUBSTITUTION RÉELLE, et elle ne se confond pas avec un bundle qui ne porte
    pas la bonne étiquette : celui-là échoue dès la récupération, sur « couldn't find
    remote ref », et n'atteint jamais la comparaison de commit. Mesuré le 01/11/2026 — un
    premier essai de ce test construisait le cas faible et validait donc le mauvais refus.

    Ce qu'un intermédiaire ferait, lui, c'est servir un contenu qui a l'air du bon : la
    bonne étiquette, un autre arbre. Seul le commit, qui voyage dans l'ordre SIGNÉ, permet
    de le refuser.

    Travaille sur le dépôt que `fabrique` a laissé dans `tmp_path` : les deux vont
    ensemble, et appeler celui-ci sans celle-là n'a pas de sens.
    """
    depot = tmp_path / "depot"
    git("tag", "-d", f"version/{number}", cwd=depot)
    git(*AUTHOR, "tag", "-a", f"version/{number}", sur_commit, "-m", "Substituée", cwd=depot)
    paquet = tmp_path / f"substitue-{number}.bundle"
    git("bundle", "create", str(paquet), f"version/{number}", cwd=depot)
    return paquet.read_bytes()


# --- Un paramétrage RÉEL, pour éprouver la matérialisation des tables -----------------

ACCOUNTS_MODELE = """$schema: https://json-schema.org/draft/2020-12/schema
$id: miles:/domains/pudo/accounts
title: Accounts
type: object
properties:
  AccountId: {type: string}
  Postes: {type: integer}
  Contact: {$ref: '#/$defs/Contact'}
$defs:
  Contact:
    type: object
    properties:
      Phone: {type: string}
      Email: {type: string}
"""
SITE_MODELE = """$schema: https://json-schema.org/draft/2020-12/schema
$id: miles:/domains/pudo/site
title: Site
type: object
properties:
  Id: {type: string}
  Zipcode: {type: string}
"""


def _storage(nom: str, modele: str, cle: str, index: list[tuple[str, list[str]]]) -> str:
    lignes = [
        f'nom: "{nom}"',
        f'libelle: "{nom.title()}"',
        f'modele: "{modele}"',
        "cle:",
        f'  - "{cle}"',
    ]
    if index:
        lignes.append("index:")
        for titre, colonnes in index:
            lignes.append(f'  - nom: "{titre}"')
            lignes.append("    colonnes:")
            lignes += [f'      - "{c}"' for c in colonnes]
    else:
        lignes.append("index: []")
    return "\n".join(lignes) + "\n"


def _pose_chaine(depot: Path, slug: str, etapes: list[tuple[str, str]]) -> None:
    """Écrit `transformations/<slug>/` : son enchaînement, et un template par étape.

    La forme est celle que le module de paramétrage produit, lue par le socle. Elle est
    recopiée ici plutôt que produite par son écrivain : les tests du module
    d'environnement n'ont pas accès au module de paramétrage, et c'est la frontière.
    """
    repertoire = depot / "transformations" / slug
    repertoire.mkdir(parents=True, exist_ok=True)
    pas = [{"name": nom, "template": f"{nom}.jslt", "target": None} for nom, _ in etapes]
    (repertoire / "chain.json").write_text(
        json.dumps(
            {"format_version": 1, "slug": slug, "label": slug, "steps": pas},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    for nom, template in etapes:
        (repertoire / f"{nom}.jslt").write_text(template, encoding="utf-8")


def _source(nom: str, storage: str, modele: str, modes: tuple[bool, bool, bool]) -> str:
    """Une source et son unique entrée web. Les trois modes dans l'ordre déclaré."""
    element, tableau, fichier = modes
    return (
        f'nom: "{nom}"\n'
        f'libelle: "{nom.title()}"\n'
        f'storage: "{storage}"\n'
        "entrees:\n"
        '  - type: "web"\n'
        f'    modele_source: "{modele}"\n'
        f'    chaine: "vers-{storage}"\n'
        "    modes:\n"
        f"      element: {str(element).lower()}\n"
        f"      tableau: {str(tableau).lower()}\n"
        f"      fichier: {str(fichier).lower()}\n"
    )


def fabrique_parametrage(tmp_path: Path) -> dict[int, VersionFabriquee]:
    """Trois versions d'un paramétrage, pour éprouver l'écart entre deux poses.

    1. `accounts` indexé sur le téléphone et sur le nombre de postes — une chaîne et un
       ENTIER, parce que c'est le type qui décide de l'ordre d'une comparaison — et
       `sites` sans index ;
    2. `accounts` gagne un index sur l'e-mail, `sites` en gagne un sur le code postal ;
    3. `accounts` PERD son index sur le téléphone, et `sites` disparaît de la déclaration.

    Chaque version porte aussi ses SOURCES — `comptes-pudo` et `sites-pudo` —, et la
    disparition de `sites` en v3 emporte la sienne : c'est le cas où un octroi de clé
    d'API ne désigne plus rien, et il ne s'éprouve qu'avec une version qui retire.

    Les trois ensemble, et dans cet ordre, parce que c'est l'ENCHAÎNEMENT qui est à
    éprouver : une pose seule ne dirait rien de ce qu'une version suivante retire.
    """
    depot = tmp_path / "param"
    git("init", "-q", "-b", "main", str(depot))
    (depot / "domains" / "pudo" / "messages").mkdir(parents=True)
    (depot / "storages").mkdir()
    (depot / "sources").mkdir()
    (depot / "domains/pudo/messages/accounts.yaml").write_text(ACCOUNTS_MODELE, encoding="utf-8")
    (depot / "domains/pudo/messages/site.yaml").write_text(SITE_MODELE, encoding="utf-8")
    # Les chaînes que les sources nomment. SANS ÉTAPE, et c'est le cas réel de ces deux
    # sources : leur modèle d'entrée EST celui de leur storage, donc il n'y a rien à
    # transformer. Exiger un template identité pour ne rien faire serait du bruit — et
    # l'absence du répertoire ferait désormais refuser le dépôt, puisque la chaîne
    # déclarée doit exister dans la version servie. La transformation réelle s'éprouve
    # avec `fabrique_import`, qui porte un vrai template.
    for storage in ("accounts", "sites"):
        _pose_chaine(depot, f"vers-{storage}", [])

    etapes = [
        {
            "storages/accounts.yaml": _storage(
                "accounts",
                "pudo/accounts",
                "$.AccountId",
                [("tel", ["$.Contact.Phone"]), ("taille", ["$.Postes"])],
            ),
            "storages/sites.yaml": _storage("sites", "pudo/site", "$.Id", []),
            "sources/comptes-pudo.yaml": _source(
                "comptes-pudo", "accounts", "pudo/accounts", (True, True, False)
            ),
            "sources/sites-pudo.yaml": _source(
                "sites-pudo", "sites", "pudo/site", (True, False, False)
            ),
        },
        {
            "storages/accounts.yaml": _storage(
                "accounts",
                "pudo/accounts",
                "$.AccountId",
                [
                    ("tel", ["$.Contact.Phone"]),
                    ("taille", ["$.Postes"]),
                    ("mail", ["$.Contact.Email"]),
                ],
            ),
            "storages/sites.yaml": _storage(
                "sites", "pudo/site", "$.Id", [("code", ["$.Zipcode"])]
            ),
            "sources/comptes-pudo.yaml": _source(
                "comptes-pudo", "accounts", "pudo/accounts", (True, True, True)
            ),
            "sources/sites-pudo.yaml": _source(
                "sites-pudo", "sites", "pudo/site", (True, False, False)
            ),
        },
        {
            "storages/accounts.yaml": _storage(
                "accounts",
                "pudo/accounts",
                "$.AccountId",
                [("mail", ["$.Contact.Email"]), ("taille", ["$.Postes"])],
            ),
            "sources/comptes-pudo.yaml": _source(
                "comptes-pudo", "accounts", "pudo/accounts", (True, True, True)
            ),
        },
    ]
    fabriquees: dict[int, VersionFabriquee] = {}
    for number, fichiers in enumerate(etapes, start=1):
        for chemin in (
            "storages/accounts.yaml",
            "storages/sites.yaml",
            "sources/comptes-pudo.yaml",
            "sources/sites-pudo.yaml",
        ):
            cible = depot / chemin
            if chemin in fichiers:
                cible.write_text(fichiers[chemin], encoding="utf-8")
            elif cible.exists():
                git("rm", "-q", chemin, cwd=depot)
        git("add", "-A", cwd=depot)
        git(*AUTHOR, "commit", "-q", "-m", f"param v{number}", cwd=depot)
        git(*AUTHOR, "tag", "-a", f"version/{number}", "-m", f"v{number}", cwd=depot)
        paquet = tmp_path / f"param-v{number}.bundle"
        git("bundle", "create", str(paquet), f"version/{number}", cwd=depot)
        commit = git("rev-parse", f"version/{number}^{{commit}}", cwd=depot).strip()
        fabriquees[number] = VersionFabriquee(number, commit, paquet.read_bytes(), tuple(fichiers))
    return fabriquees


# Un paramétrage dédié à l'écriture différentielle (story d680e811) : un modèle, un
# storage, une source, et une chaîne qui TRANSFORME vraiment. Séparé de
# `fabrique_parametrage`, dont les deux sources ont le même modèle en entrée et en sortie
# — elles ne pouvaient donc rien dire de ce qu'une transformation rend insensible.
MAGASIN_MODELE = """$schema: https://json-schema.org/draft/2020-12/schema
$id: miles:/domains/pudo/magasin
title: Magasin
type: object
required: [Code, Libelle]
properties:
  Code: {type: string}
  Libelle: {type: string}
  Ville: {type: [string, "null"]}
  Postes: {type: [integer, "null"]}
"""
# Le template NE LIT PAS tout ce que la source envoie : c'est ce qui rend l'empreinte
# insensible à un champ d'émission qui change à chaque envoi (critère 4), et on ne peut
# pas l'éprouver avec un template identité.
MAGASIN_TEMPLATE = (
    '{ "Code": $.code, "Libelle": $.nom, "Ville": $.ville, "Postes": $.postes#integer }'
)


def fabrique_import(tmp_path: Path) -> dict[int, VersionFabriquee]:
    """UNE version : le storage `magasins`, sa source, et la chaîne qui y mène."""
    depot = tmp_path / "import"
    git("init", "-q", "-b", "main", str(depot))
    (depot / "domains" / "pudo" / "messages").mkdir(parents=True)
    (depot / "storages").mkdir()
    (depot / "sources").mkdir()
    (depot / "domains/pudo/messages/magasin.yaml").write_text(MAGASIN_MODELE, encoding="utf-8")
    (depot / "storages/magasins.yaml").write_text(
        _storage("magasins", "pudo/magasin", "$.Code", [("ville", ["$.Ville"])]), encoding="utf-8"
    )
    (depot / "sources/magasins-import.yaml").write_text(
        _source("magasins-import", "magasins", "pudo/magasin", (True, True, False)),
        encoding="utf-8",
    )
    _pose_chaine(depot, "vers-magasins", [("convertir", MAGASIN_TEMPLATE)])
    git("add", "-A", cwd=depot)
    git(*AUTHOR, "commit", "-q", "-m", "import v1", cwd=depot)
    git(*AUTHOR, "tag", "-a", "version/1", "-m", "v1", cwd=depot)
    paquet = tmp_path / "import-v1.bundle"
    git("bundle", "create", str(paquet), "version/1", cwd=depot)
    commit = git("rev-parse", "version/1^{commit}", cwd=depot).strip()
    return {1: VersionFabriquee(1, commit, paquet.read_bytes(), ("storages/magasins.yaml",))}
