"""Le vocabulaire de l'illisible : pourquoi un document déposé ne se lit pas.

Volontairement SANS dépendance et sans mécanique : ces codes sont rangés en `failure_code`
dans l'historique des ingestions et lus par les tests d'intégration. Les séparer de la
lecture elle-même est ce qui permet de changer le lecteur — ce qui a été fait le
07/11/2026, d'un parcours jeton par jeton vers une fenêtre glissante — sans toucher à un
seul code de refus, donc sans faire évoluer un contrat pour une raison interne.

**Ne pas ajouter de code ici sans y être obligé.** Un code neuf est une évolution visible
du contrat d'ingestion : une valeur démesurée, une chaîne non terminée, un conteneur non
fermé se rangent tous sous `document_json_invalide`, parce que le déposant les corrige de
la même façon — en déposant un document bien formé.
"""

from __future__ import annotations

# Imbrication maximale admise dans un document déposé, et dans un item. Bornée, et le
# dépassement est RENDU comme un refus : un débordement de pile tomberait le service au
# lieu de faire refuser un dépôt fautif. L'analyseur du stdlib ne borne rien de lui-même —
# mesuré le 07/11/2026, il a construit deux mille niveaux sans broncher —, donc la garde
# est explicite et vit dans `jsonwindow`.
MAX_DEPTH = 100

# Pourquoi un document est illisible. Chacun dit à qui a déposé ce qu'il doit corriger.
DOCUMENT_INVALID = "document_json_invalide"
ITEMS_PATH_ABSENT = "decoupage_absent_du_document"
ITEMS_PATH_NOT_ARRAY = "decoupage_ne_designe_pas_un_tableau"
DOCUMENT_TOO_DEEP = "document_trop_imbrique"
METADATA_TOO_LARGE = "metadonnees_demesurees"

# Les refus STRUCTURELS : le document ne porte pas ce que la déclaration suppose, ou il
# dépasse une borne. Distingués d'une INTERRUPTION de lecture, et la distinction décide de
# l'issue d'un import : un document structurellement inimportable se termine en ÉCHEC sans
# rien écrire (critère 4), là où un document tronqué au milieu laisse écrits les items lus
# avant l'incident si la transaction n'est pas unifiée (critère 8). Les confondre ferait
# marquer « incomplet » un import dont aucun item n'a jamais pu être lu — et le balayage
# attendrait la suite d'un document qui n'en avait pas.
STRUCTURAL = frozenset(
    {ITEMS_PATH_ABSENT, ITEMS_PATH_NOT_ARRAY, DOCUMENT_TOO_DEEP, METADATA_TOO_LARGE}
)


class DocumentUnreadable(Exception):
    """Le document déposé ne se lit pas. `code` est stable, `detail` aide à corriger.

    Levée pendant une passe, donc éventuellement après que des items ont déjà été émis :
    c'est l'appelant qui sait combien, et lui qui décide — tout ou rien si la transaction
    est unifiée, import incomplet sinon (critères 7 et 8).
    """

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code if detail is None else f"{code}:{detail}")
        self.code, self.detail = code, detail


def show(keys: tuple[str | int, ...]) -> str:
    """Le découpage tel que l'auteur l'a écrit, pour que le refus le nomme (critère 4)."""
    rendu = "$"
    for key in keys:
        rendu += f"[{key}]" if isinstance(key, int) else f".{key}"
    return f"{rendu}[*]"
