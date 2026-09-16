"""FastAPI application: whole-request validation and exact subset DP solve."""

from __future__ import annotations

import os
from typing import Any, List, Tuple

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from .models import (
    ObservationResult,
    PlacementProfileIn,
    PlacementProfileOut,
    ProblemError,
    ProblemIn,
    ProfileDepth,
    SolutionOut,
    ValidationErrorItem,
    Witness,
    collect_semantic_errors,
)
from .solver import evaluate_order, placement_profile, solve

app = FastAPI(title="Woodblock Layer Audit", version="1.0.0")

_default_origins = "http://localhost:5173,http://localhost:8080,http://127.0.0.1:5173"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", _default_origins).split(",") if o.strip()],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def _loc_to_pointer(loc: tuple[Any, ...]) -> str:
    parts: List[str] = []
    for piece in loc:
        text = str(piece)
        parts.append(text.replace("~", "~0").replace("/", "~1"))
    return "/" + "/".join(parts) if parts else ""


async def _read_json(request: Request) -> Tuple[Any, JSONResponse | None]:
    """Parse the request body, mirroring /api/solve's bad-JSON 422 shape."""
    try:
        return await request.json(), None
    except Exception:
        return None, JSONResponse(
            status_code=422,
            content=ProblemError(
                errors=[ValidationErrorItem(pointer="", message="request body must be valid JSON")]
            ).model_dump(),
        )


def _validate(data: Any, model_cls: type[BaseModel]) -> Tuple[BaseModel | None, JSONResponse | None]:
    """Run Pydantic and cross-field validation exactly as /api/solve does.

    Returns ``(model, None)`` on success or ``(None, 422_response)``; all
    problems are reported in one pointer-sorted response.
    """
    errors: List[ValidationErrorItem] = []

    model: BaseModel | None = None
    try:
        model = model_cls.model_validate(data)
    except ValidationError as exc:
        for err in exc.errors():
            errors.append(
                ValidationErrorItem(pointer=_loc_to_pointer(tuple(err["loc"])), message=err["msg"])
            )

    # Cross-field semantic validation (duplicates, dangling refs, ...) runs
    # on the raw body independently of type validation. Placement-profile
    # requests additionally get an unknown-target error at /target, so it is
    # still merged in (and pointer-sorted) when some other field is invalid.
    errors.extend(collect_semantic_errors(data, check_target=(model_cls is PlacementProfileIn)))

    if errors:
        # Stable sort by JSON Pointer; the first occurrence keeps its order.
        ordered = sorted(enumerate(errors), key=lambda pair: (pair[1].pointer, pair[0]))
        payload = ProblemError(errors=[item for _, item in ordered])
        return None, JSONResponse(status_code=422, content=payload.model_dump())

    return model, None


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/solve", response_model=SolutionOut)
async def solve_problem(request: Request) -> Any:
    data, bad_json = await _read_json(request)
    if bad_json is not None:
        return bad_json

    problem, error_response = _validate(data, ProblemIn)
    if error_response is not None:
        return error_response
    assert isinstance(problem, ProblemIn)

    # Canonicalize nothing for the solver math, but emit rows in ASCII order
    # so reordering layers/observations in the request cannot change the
    # reported witness.
    layers = sorted(problem.layers)
    triples = sorted(((obs.lower, obs.upper, obs.weight) for obs in problem.observations),
                     key=lambda t: (t[0], t[1]))

    result = solve(layers, triples)

    rows = evaluate_order(layers, triples, result["order"])
    witness = Witness(order=result["order"], cost=sum(r["cost"] for r in rows), observations=[
        ObservationResult(**row) for row in rows
    ])

    second_witness = None
    if result["second_order"] is not None:
        second_rows = evaluate_order(layers, triples, result["second_order"])
        second_witness = Witness(
            order=result["second_order"],
            cost=sum(r["cost"] for r in second_rows),
            observations=[ObservationResult(**row) for row in second_rows],
        )

    return SolutionOut(
        status=result["status"],
        cost=result["cost"],
        order=result["order"],
        witness=witness,
        second_cost=result["second_cost"],
        second_order=result["second_order"],
        second_witness=second_witness,
        layers=layers,
    )


@app.post("/api/placement-profile", response_model=PlacementProfileOut)
async def placement_profile_problem(request: Request) -> Any:
    data, bad_json = await _read_json(request)
    if bad_json is not None:
        return bad_json

    problem, error_response = _validate(data, PlacementProfileIn)
    if error_response is not None:
        return error_response
    assert isinstance(problem, PlacementProfileIn)

    layers = sorted(problem.layers)
    triples = sorted(((obs.lower, obs.upper, obs.weight) for obs in problem.observations),
                     key=lambda t: (t[0], t[1]))

    profile = placement_profile(layers, triples, problem.target)
    return PlacementProfileOut(
        target=profile["target"],
        optimal_cost=profile["optimal_cost"],
        depths=[ProfileDepth(**row) for row in profile["depths"]],
    )
