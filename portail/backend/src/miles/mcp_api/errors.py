from __future__ import annotations

import json
from typing import Any


def refusal(code: str, **detail: Any) -> str:
    """Erreur exploitable par l'agent : un code stable, et ce qui permet de se corriger seul.

    Rendue en texte JSON dans le résultat d'erreur de l'outil (`isError`), pour que l'agent
    la lise sans autre documentation : quoi, où, et ce qui existe à la place.
    """
    return json.dumps({"code": code, **detail}, ensure_ascii=False)


def refusal_code(message: str) -> str:
    try:
        return str(json.loads(message).get("code", "refus"))
    except (ValueError, AttributeError):
        return "refus"
