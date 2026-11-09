"""Le sort de chaque objet d'un lot, et le compte-rendu du lot entier.

Rendu SYNCHRONEMENT à l'appelant pour les modes `element` et `tableau` (décision de Gael
du 02/11/2026 : « la méthode un element et la methode array ont le meme retour synchrone
avec un array qui décris pour chaque clef fonctionnel le retour »), et rangé sur la ligne
d'ingestion pour qu'un rejeu rende le même — un compte-rendu perdu avec la réponse HTTP
n'est pas une trace.

**Un objet rejeté n'est pas un échec d'import** (même décision) : le lot continue, et
c'est le compte-rendu qui nomme ce qui n'est pas passé. L'échec du LOT n'existe que
lorsque tout a été rejeté.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

# Le sort d'un objet. Trois issues, et la distinction entre les deux premières est tout
# l'objet de la story : `inchange` dit que la base n'a pas bougé, et c'est le DELTA
# constaté qui le dit, jamais le fait que le code ait tourné.
WRITTEN = "ecrit"
UNCHANGED = "inchange"
REJECTED = "rejete"

# Motifs de rejet d'un OBJET, distincts des refus de DÉPÔT (`model.py`) : ceux-ci
# n'empêchent pas le lot, ils nomment un objet.
REJECT_KEY_MISSING = "cle_non_extractible"
REJECT_TRANSFORM = "transformation_en_echec"
REJECT_MODEL = "modele_non_respecte"
REJECT_MANUAL = "objet_d_origine_manuelle"

# Anomalie de SOURCE, et non rejet : les deux objets sont traités, le dernier valide
# gagne (décision du 02/11/2026), et le compte-rendu le signale explicitement plutôt que
# d'écrire le dernier en silence (critère 8).
ANOMALY_DUPLICATE_KEY = "cle_en_double_dans_le_lot"
# Le détail objet par objet a été PLAFONNÉ. Dit, parce qu'un compte-rendu tronqué en
# silence ferait croire à un import de cinquante mille items qu'il n'a eu que deux cents
# rejets. Les COMPTES, eux, restent exacts.
ANOMALY_DETAIL_CAPPED = "detail_plafonne"
# Le NETTOYAGE a été refusé en entier : une règle de péremption désigne une propriété que
# le modèle servi ne donne plus, ou qui n'est plus projetée. Anomalie du compte-rendu et
# non échec de l'import — l'import a bien écrit ce qu'il portait —, mais DITE, parce qu'un
# storage qui cesse de se nettoyer sans un mot est exactement ce qu'on ne veut pas.
ANOMALY_CLEANUP_REFUSED = "nettoyage_refuse"
# La SYNTHÈSE par motif a été plafonnée : au-delà, les rejets restent comptés dans le
# total mais leur motif n'entre plus dans la synthèse.
ANOMALY_REASONS_CAPPED = "motifs_plafonnes"

# Combien de motifs DISTINCTS la synthèse garde. Cinquante : un import qui en produit
# davantage n'a pas un problème de donnée, il a un problème de modèle, et la liste cesse
# alors d'être lisible. La borne existe parce que le motif porte le `detail` du
# validateur, qui peut nommer une valeur — donc le nombre de motifs distincts n'est PAS
# borné par le nombre de règles.
REASONS_CAP = 50

# État d'une ingestion, au-delà de « reçu » que la réception pose.
STATE_PROCESSED = "traite"
STATE_FAILED = "rejete"
# États propres à l'import d'un FICHIER, qui est asynchrone (story 0f14adbd) : le contrat
# publié ne lui promet qu'un acquittement de prise en charge.
STATE_QUEUED = "en_file"
STATE_RUNNING = "en_cours"
# « incomplet » : le document s'est interrompu et la transaction n'était PAS unifiée, donc
# les items valides lus avant l'incident sont écrits (critère 8). C'est l'état que le
# balayage refuse, et il se distingue de « echec », où rien n'a été écrit.
STATE_PARTIAL = "incomplet"
STATE_FAILED_IMPORT = "echec"


@dataclass(frozen=True)
class ObjectOutcome:
    """Ce qu'un objet du lot est devenu. `position` est son rang, 0 pour le premier.

    `key` est nulle quand elle n'a pas pu être extraite : c'est précisément le cas où
    l'appelant ne peut pas se repérer par la clé, et le rang est alors sa seule prise
    (critère 9).
    """

    position: int
    outcome: str
    key: str | None = None
    reason: str | None = None
    detail: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "outcome": self.outcome,
            "key": self.key,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RejectionReason:
    """Un MOTIF de rejet, son compte, et un objet par lequel aller voir.

    C'est ce qui manquait pour corriger un modèle (Gael, 08/11/2026) : un import de
    194 361 items a rendu 25 586 rejets, dont le détail s'arrêtait au deux-centième. Les
    motifs des 25 386 autres n'existaient plus nulle part — ni en base, ni dans les
    journaux, qui ne portent que des totaux. Aucun écran ne peut montrer ce qui n'a pas
    été gardé : la synthèse se tient donc PENDANT l'import, et elle est bornée par le
    nombre de motifs DISTINCTS, pas par le nombre de rejets.
    """

    reason: str
    detail: str | None
    count: int
    # La clé d'un objet rejeté sous ce motif, pour aller lire un cas réel. Le PREMIER
    # rencontré, et non le dernier : il ne change pas d'un import à l'autre si le
    # document est le même, ce qui rend deux comptes-rendus comparables.
    sample_key: str | None

    def as_json(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "detail": self.detail,
            "count": self.count,
            "sample_key": self.sample_key,
        }


@dataclass
class Report:
    """Le compte-rendu du lot : les comptes, le sort de chaque objet, les anomalies."""

    received: int
    objects: list[ObjectOutcome] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)
    # Comptes TENUS au fil de l'écriture, pour un lot dont on ne garde pas le détail objet
    # par objet — un import de fichier peut porter cinquante mille items, et son
    # compte-rendu est rangé en base. Nuls quand `objects` porte tout le lot : les comptes
    # s'en déduisent alors, et il n'y a pas deux vérités à tenir d'accord.
    tallies: dict[str, int] | None = None
    # La synthèse des motifs, TENUE au fil de l'écriture pour la même raison que les
    # comptes : au-delà du plafond de détail, l'objet rejeté est oublié mais son motif
    # doit survivre. Nulle quand `objects` porte tout le lot — la synthèse s'en déduit
    # alors, et il n'y a pas deux vérités à tenir d'accord.
    reason_tallies: dict[tuple[str, str | None], RejectionReason] | None = None

    @property
    def written(self) -> int:
        return self._count(WRITTEN)

    @property
    def unchanged(self) -> int:
        return self._count(UNCHANGED)

    @property
    def rejected(self) -> int:
        return self._count(REJECTED)

    @property
    def all_rejected(self) -> bool:
        """Tout a été rejeté, et il y avait quelque chose à traiter (critère 12).

        Un lot formellement valide mais VIDE n'est pas un échec : le ticket précédent
        l'accepte explicitement (son critère 5), et zéro objet rejeté sur zéro reçu ne
        doit pas faire tomber l'ingestion.
        """
        return self.received > 0 and self.rejected == self.received

    def counted(self, issue: ObjectOutcome, *, keep: int) -> None:
        """Compte cet item en ne gardant du détail que les REJETS, et au plus `keep`.

        Les rejets seuls, parce que ce sont les seuls que personne ne peut retrouver
        autrement : un objet écrit est dans la table de son storage, un objet inchangé y
        est déjà. Et plafonnés, parce que le compte-rendu est rangé en base — garder
        cinquante mille lignes de détail par import ferait de la colonne un journal.
        Le plafond atteint est DIT dans les anomalies, jamais tu.
        """
        if self.tallies is None:
            self.tallies = dict.fromkeys((WRITTEN, UNCHANGED, REJECTED), 0)
        self.tallies[issue.outcome] += 1
        self.received += 1
        if issue.outcome != REJECTED:
            return
        self._tally_reason(issue)
        if len(self.objects) < keep:
            self.objects.append(issue)
            return
        marque = f"{ANOMALY_DETAIL_CAPPED}:{keep}"
        if marque not in self.anomalies:
            self.anomalies.append(marque)

    @property
    def reasons(self) -> list[RejectionReason]:
        """Les motifs de rejet, du plus fréquent au moins fréquent.

        Tenus pendant l'écriture quand le détail est plafonné, DÉRIVÉS de `objects`
        sinon — exactement la règle des comptes, et pour la même raison : un lot dont on
        garde tout le détail n'a pas besoin d'une seconde vérité à tenir d'accord.
        """
        tenus = (
            list(self.reason_tallies.values())
            if self.reason_tallies is not None
            else _reasons_of(self.objects)
        )
        # Le compte d'abord, puis le motif : deux motifs à égalité gardent un ordre
        # stable d'un import à l'autre, sans quoi deux comptes-rendus du même document ne
        # se compareraient pas.
        return sorted(tenus, key=lambda motif: (-motif.count, motif.reason, motif.detail or ""))

    def as_json(self) -> dict[str, Any]:
        return {
            "received": self.received,
            "written": self.written,
            "unchanged": self.unchanged,
            "rejected": self.rejected,
            "objects": [o.as_json() for o in self.objects],
            "reasons": [motif.as_json() for motif in self.reasons],
            "anomalies": self.anomalies,
        }

    def _tally_reason(self, issue: ObjectOutcome) -> None:
        """Range ce rejet sous son motif, dans la limite de `REASONS_CAP` motifs."""
        if self.reason_tallies is None:
            self.reason_tallies = {}
        cle = (issue.reason or "", issue.detail)
        connu = self.reason_tallies.get(cle)
        if connu is not None:
            self.reason_tallies[cle] = replace(connu, count=connu.count + 1)
            return
        if len(self.reason_tallies) >= REASONS_CAP:
            marque = f"{ANOMALY_REASONS_CAPPED}:{REASONS_CAP}"
            if marque not in self.anomalies:
                self.anomalies.append(marque)
            return
        self.reason_tallies[cle] = RejectionReason(
            reason=cle[0], detail=cle[1], count=1, sample_key=issue.key
        )

    def _count(self, outcome: str) -> int:
        if self.tallies is not None:
            return self.tallies[outcome]
        return sum(1 for o in self.objects if o.outcome == outcome)


def _reasons_of(objects: list[ObjectOutcome]) -> list[RejectionReason]:
    """La synthèse déduite du détail, quand le détail est entier."""
    motifs: dict[tuple[str, str | None], RejectionReason] = {}
    for objet in objects:
        if objet.outcome != REJECTED:
            continue
        cle = (objet.reason or "", objet.detail)
        connu = motifs.get(cle)
        motifs[cle] = (
            replace(connu, count=connu.count + 1)
            if connu is not None
            else RejectionReason(reason=cle[0], detail=cle[1], count=1, sample_key=objet.key)
        )
    return list(motifs.values())


def report_of(data: Any) -> Report:
    """Le compte-rendu rangé en base, relu. Lève sur une forme inattendue.

    Lève plutôt que de rendre un compte-rendu partiel : un rejeu doit rendre CE qui a été
    décidé la première fois, et un compte-rendu amputé en silence ferait croire à un
    partenaire que son lot avait moins d'objets qu'il n'en a déposé. Si la forme a changé,
    c'est un défaut de migration, et il doit se voir.
    """
    objets = [
        ObjectOutcome(
            position=int(o["position"]),
            outcome=str(o["outcome"]),
            key=o["key"],
            reason=o["reason"],
            detail=o["detail"],
        )
        for o in data["objects"]
    ]
    return Report(
        received=int(data["received"]),
        objects=objets,
        anomalies=list(data["anomalies"]),
        # Les comptes sont RELUS et non recomptés depuis `objects` : un compte-rendu
        # d'import de fichier ne garde que ses rejets, et les recompter dirait qu'aucun
        # objet n'a été écrit.
        tallies={
            WRITTEN: int(data["written"]),
            UNCHANGED: int(data["unchanged"]),
            REJECTED: int(data["rejected"]),
        },
        # ABSENTE d'un compte-rendu écrit avant le 08/11/2026, et c'est le seul champ
        # qu'on tolère manquant : les autres lèvent, parce qu'un compte-rendu amputé
        # mentirait sur ce qu'un partenaire a déposé. Ici, la synthèse se déduit du détail
        # gardé — et l'anomalie `detail_plafonne`, déjà rangée, dit à l'écran que ce détail
        # ne couvre pas tout le lot.
        reason_tallies=_tallies_of(data.get("reasons")),
    )


def _tallies_of(data: Any) -> dict[tuple[str, str | None], RejectionReason] | None:
    if data is None:
        return None
    return {
        (str(motif["reason"]), motif["detail"]): RejectionReason(
            reason=str(motif["reason"]),
            detail=motif["detail"],
            count=int(motif["count"]),
            sample_key=motif["sample_key"],
        )
        for motif in data
    }
