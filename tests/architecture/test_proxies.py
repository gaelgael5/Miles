from __future__ import annotations

from pathlib import Path

from architecture.proxies import (
    NGINX_CONF,
    PRODUITS,
    file_compression,
    resolve_facades_sans_compression,
)

DEPOT = Path(__file__).resolve().parents[2]


def test_les_trois_facades_compressent_ce_qu_elles_servent() -> None:
    manques = resolve_facades_sans_compression(DEPOT)
    assert not manques, "façades sans compression :\n" + "\n".join(str(m) for m in manques)


def test_une_directive_seulement_commentee_ne_compte_pas(tmp_path: Path) -> None:
    # Un fichier qui PARLE de compression ne compresse pas : sans cette distinction, il
    # suffirait d'en parler pour satisfaire la garde.
    conf = tmp_path / "nginx.conf"
    conf.write_text("server {\n    # gzip on;\n}\n", encoding="utf-8")

    assert file_compression(conf) == ()


def test_gzip_on_sans_types_ne_compte_pas(tmp_path: Path) -> None:
    # `gzip on` seul ne couvre que text/html : le bundle, qui est tout le poids, partirait
    # non compressé — une compression déclarée mais sans effet là où elle sert.
    conf = tmp_path / "nginx.conf"
    conf.write_text("server {\n    gzip on;\n}\n", encoding="utf-8")

    assert file_compression(conf) == ()


def test_la_directive_retiree_d_une_seule_facade_nomme_ce_fichier_la(tmp_path: Path) -> None:
    # La faute pour de vrai, éprouvée sur les fichiers réels : la garde doit nommer le
    # produit fautif et aucun autre, sinon elle n'aide pas à réparer.
    for produit in PRODUITS:
        copie = tmp_path / produit / "frontend"
        copie.mkdir(parents=True)
        texte = (DEPOT / produit / NGINX_CONF).read_text(encoding="utf-8")
        if produit == "enrolement":
            texte = texte.replace("gzip on;", "")
        (copie / "nginx.conf").write_text(texte, encoding="utf-8")

    manques = resolve_facades_sans_compression(tmp_path)

    assert [m.fichier for m in manques] == [f"enrolement/{NGINX_CONF}"]


def test_un_type_oublie_est_nomme(tmp_path: Path) -> None:
    for produit in PRODUITS:
        copie = tmp_path / produit / "frontend"
        copie.mkdir(parents=True)
        texte = (DEPOT / produit / NGINX_CONF).read_text(encoding="utf-8")
        if produit == "environnement":
            texte = texte.replace("text/css", "")
        (copie / "nginx.conf").write_text(texte, encoding="utf-8")

    manques = resolve_facades_sans_compression(tmp_path)

    assert [(m.fichier, "text/css" in m.raison) for m in manques] == [
        (f"environnement/{NGINX_CONF}", True)
    ]
