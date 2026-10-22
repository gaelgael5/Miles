from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from miles.transform.engine import (
    EvaluationError,
    OutsideProfileError,
    TemplateSyntaxError,
    compile_template,
    evaluate,
)

# Réservé à l'administrateur tant que les rôles n'existent pas. Vérifier n'écrit rien :
# l'enregistrement d'un template appartient à ce qui le porte (mapping, import…).
router = APIRouter(prefix="/api/templates")
MAX_TEMPLATE_LENGTH = 256 * 1024


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: str = Field(max_length=MAX_TEMPLATE_LENGTH)
    # Échantillon d'entrée ; absent, seule la forme du template est vérifiée.
    sample: Any = None


class PositionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str
    line: int | None
    column: int | None


class ViolationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    construction: str
    detail: str | None
    line: int | None
    column: int | None


class EvaluationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str | None
    path: str | None
    expected: str | None


class CheckOut(BaseModel):
    """Verdict sur un template : même entrée, même verdict, quel que soit l'appelant."""

    model_config = ConfigDict(extra="forbid")
    valid: bool
    syntax: PositionOut | None = None
    violations: list[ViolationOut] = []
    # Faux sans échantillon : la conformité du résultat ne peut pas être affirmée.
    evaluated: bool = False
    result: Any = None
    evaluation: EvaluationOut | None = None


@router.post("/check", response_model=CheckOut)
async def check_template(body: CheckIn, request: Request) -> CheckOut:
    try:
        template = compile_template(body.template)
    except TemplateSyntaxError as exc:
        return CheckOut(
            valid=False, syntax=PositionOut(message=exc.message, line=exc.line, column=exc.column)
        )
    except OutsideProfileError as exc:
        violations = [
            ViolationOut(construction=v.construct, detail=v.detail, line=v.line, column=v.column)
            for v in exc.violations
        ]
        return CheckOut(valid=False, violations=violations)
    if body.sample is None:
        return CheckOut(valid=True)
    budget: int = request.app.state.transform_budget
    try:
        result = evaluate(template, body.sample, budget)
    except EvaluationError as exc:
        failure = EvaluationOut(
            code=exc.code, message=exc.message, path=exc.path, expected=exc.expected
        )
        return CheckOut(valid=True, evaluated=True, evaluation=failure)
    return CheckOut(valid=True, evaluated=True, result=result)
