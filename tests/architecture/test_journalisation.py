from __future__ import annotations

from pathlib import Path

from architecture.journalisation import RACINES, resolve_appels_fautifs

DEPOT = Path(__file__).resolve().parents[2]


def test_aucun_appel_de_journalisation_ne_passe_la_clef_reservee() -> None:
    fautifs = resolve_appels_fautifs(DEPOT)
    assert not fautifs, "clef `event` passée à un logger (TypeError à l'exécution) :\n" + "\n".join(
        str(a) for a in fautifs
    )


def test_la_faute_du_15_11_est_detectee(tmp_path: Path) -> None:
    # La faute pour de vrai, telle qu'elle était écrite : sans ce cas, une garde qui ne
    # lirait aucun fichier serait verte pour toujours.
    source = tmp_path / "portail" / "backend" / "src" / "miles" / "service.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        'log.info("type_d_event_declare", workspace=w, event=declared.name)\n',
        encoding="utf-8",
    )

    assert [(a.fichier, a.ligne) for a in resolve_appels_fautifs(tmp_path)] == [
        ("portail/backend/src/miles/service.py", 1)
    ]


def test_les_racines_lues_existent() -> None:
    # Un chemin renommé ferait lire zéro fichier, et la garde ne mesurerait plus rien.
    assert all((DEPOT / r).is_dir() for r in RACINES)
