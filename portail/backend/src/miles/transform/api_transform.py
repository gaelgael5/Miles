from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from miles.transform.chain import (
    ChainFailedError,
    ChainInvalidError,
    StepProblem,
    StepSpec,
    compile_chain,
    run_chain,
)
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
# Chaîne de transformations (story 66ae5c10) : même vérification, étape par étape.
chains_router = APIRouter(prefix="/api/transformations")
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


class StepIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: str = Field(max_length=MAX_TEMPLATE_LENGTH)
    # Vide : le résultat devient le message ; sinon le chemin où le poser.
    target: str | None = Field(default=None, max_length=1024)


class ChainCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[StepIn] = Field(max_length=200)
    # Message d'entrée ; absent, la source vaut {}.
    sample: Any = None


class StepProblemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step: int
    code: str
    detail: str | None
    line: int | None
    column: int | None
    violations: list[ViolationOut]


class ChainFailureOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step: int
    evaluation: EvaluationOut


class ChainCheckOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valid: bool
    problems: list[StepProblemOut] = []
    # Message produit après chaque étape : on voit où une transformation dévie.
    trace: list[Any] = []
    failure: ChainFailureOut | None = None


@chains_router.post("/check", response_model=ChainCheckOut)
async def check_chain(body: ChainCheckIn, request: Request) -> ChainCheckOut:
    budget: int = request.app.state.transform_budget
    return run_check(body.steps, body.sample, budget)


def run_check(steps: list[StepIn], sample: Any, budget: int) -> ChainCheckOut:
    """L'essai d'une chaîne sur un échantillon, sans rien écrire.

    Partagé par l'écran et la surface MCP : un même essai doit rendre le même verdict
    par les deux chemins, sinon l'agent et la personne ne parleraient pas de la même chose.
    """
    specs = [StepSpec(s.template, s.target) for s in steps]
    try:
        chain = compile_chain(specs)
    except ChainInvalidError as exc:
        return ChainCheckOut(valid=False, problems=[step_problem_out(p) for p in exc.problems])
    try:
        trace = run_chain(chain, sample, budget)
    except ChainFailedError as exc:
        cause = exc.cause
        evaluation = EvaluationOut(
            code=cause.code, message=cause.message, path=cause.path, expected=cause.expected
        )
        return ChainCheckOut(
            valid=True, failure=ChainFailureOut(step=exc.step, evaluation=evaluation)
        )
    return ChainCheckOut(valid=True, trace=trace)


def step_problem_out(problem: StepProblem) -> StepProblemOut:
    return StepProblemOut(
        step=problem.step,
        code=problem.code,
        detail=problem.detail,
        line=problem.line,
        column=problem.column,
        violations=[
            ViolationOut(construction=v.construct, detail=v.detail, line=v.line, column=v.column)
            for v in problem.violations
        ],
    )
