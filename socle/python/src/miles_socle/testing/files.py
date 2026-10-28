"""Fichiers et valeurs d'essai que les trois produits préparent de la même façon.

Le `.env` monté fichier par fichier, le compte d'amorçage qu'il porte, la clé des secrets :
ce sont des formes imposées par le socle, pas des choix de produit. Les recopier dans
chaque suite les fait dériver de ce que le socle lit réellement — et c'est arrivé.
"""

from __future__ import annotations

import base64
from pathlib import Path

from miles_socle.auth.passwords import hash_password

# Entrées que le produit ne doit PAS écraser en écrivant le compte d'amorçage : le `.env`
# de l'hôte porte aussi le mot de passe de la base et le port publié. Aucune de ces valeurs
# n'a de portée hors des tests ; ce sont des témoins.
BASE_ENV = "MILES_DB_PASSWORD=ne-pas-toucher\nMILES_HTTP_PORT=8180\n"
ADMIN_PASSWORD = "correct horse battery"
ADMIN_USERNAME = "admin"
DSN = "postgresql://miles:x@db:5432/miles"
# Clé de 32 octets en base64url, comme celle que `dev-deploy.sh` engendre.
#
# ENGENDRÉE depuis des octets, et non écrite à la main. La valeur en dur qui tenait cette
# place dans deux produits faisait 43 caractères, sans rembourrage : `parse_secrets_key` la
# REFUSAIT, ce qui n'apparaissait nulle part parce qu'aucun test ne montait l'application
# entière — la configuration transporte cette clé, elle ne la lit pas. Mesuré le 28/10/2026
# sur machine de test. Ne pas revenir à un littéral.
SECRETS_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")


def write_migrations(directory: Path, files: dict[str, str]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, sql in files.items():
        (directory / name).write_text(sql, encoding="utf-8")
    return directory


def write_env(tmp_path: Path, content: str = BASE_ENV) -> tuple[Path, Path]:
    """`.env` et `.env.bak` tels que `dev-deploy.sh` les prépare : les deux existent.

    Les deux, et pas seulement le premier : le backend restaure `.env` depuis `.env.bak`
    si son écriture est interrompue, et un fichier absent le ferait échouer autrement que
    pour la raison qu'on éprouve. Les droits 600 sont ceux de la machine.
    """
    env, backup = tmp_path / ".env", tmp_path / ".env.bak"
    env.write_text(content, encoding="utf-8")
    env.chmod(0o600)
    backup.write_text("", encoding="utf-8")
    backup.chmod(0o600)
    return env, backup


def admin_env(email: str, *, username: str = ADMIN_USERNAME, base: str = BASE_ENV) -> str:
    """Le `.env` d'une installation où un administrateur EXISTE déjà.

    Les trois entrées d'un seul coup : le socle refuse de démarrer sur un compte partiel,
    et c'est voulu — il ne doit pas deviner si un administrateur existe. L'empreinte est
    calculée, jamais écrite en dur, pour que les tests éprouvent le vrai hachage.
    """
    return (
        base
        + f"MILES_ADMIN_EMAIL='{email}'\nMILES_ADMIN_USERNAME='{username}'\n"
        + f"MILES_ADMIN_PASSWORD_HASH='{hash_password(ADMIN_PASSWORD)}'\n"
    )
