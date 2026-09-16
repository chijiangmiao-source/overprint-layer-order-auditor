"""Pydantic schemas and whole-request validation for the audit API."""

from __future__ import annotations

import re
from typing import Annotated, Any, List, Literal

from pydantic import BaseModel, ConfigDict, Field

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
MIN_LAYERS = 2
MAX_LAYERS = 20
MIN_WEIGHT = 1
MAX_WEIGHT = 1_000_000

Weight = Annotated[int, Field(strict=True, ge=MIN_WEIGHT, le=MAX_WEIGHT)]


class ObservationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lower: str
    upper: str
    weight: Weight


class ProblemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layers: List[str]
    observations: List[ObservationIn]


class ValidationErrorItem(BaseModel):
    # RFC 6901 JSON Pointer, e.g. "/observations/3/upper".
    pointer: str
    message: str


class ProblemError(BaseModel):
    errors: List[ValidationErrorItem]


class ObservationResult(BaseModel):
    lower: str
    upper: str
    weight: int
    lower_position: int
    upper_position: int
    violated: bool
    cost: int


class Witness(BaseModel):
    """A concrete order with a line-by-line, re-summable cost breakdown."""

    order: List[str]
    cost: int
    observations: List[ObservationResult]


class SolutionOut(BaseModel):
    status: Literal["unique", "ambiguous"]
    cost: int
    order: List[str]
    witness: Witness
    second_cost: int | None = None
    second_order: List[str] | None = None
    second_witness: Witness | None = None
    layers: List[str]


def _pointer(parts: List[Any]) -> str:
    if not parts:
        return ""
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def collect_semantic_errors(data: Any) -> List[ValidationErrorItem]:
    """Cross-field validation over the raw JSON body.

    Runs independently of Pydantic type/shape validation so that type
    errors and semantic errors are reported together in one response.
    Every invalid construct gets its own JSON Pointer.
    """
    errors: List[ValidationErrorItem] = []

    if not isinstance(data, dict):
        errors.append(ValidationErrorItem(pointer="", message="request body must be a JSON object"))
        return errors

    raw_layers = data.get("layers")
    raw_observations = data.get("observations")

    # ---- layers -----------------------------------------------------------
    if not isinstance(raw_layers, list):
        # Missing / wrong-typed `layers` is already reported by Pydantic;
        # nothing semantic can be derived without it.
        return errors

    if not (MIN_LAYERS <= len(raw_layers) <= MAX_LAYERS):
        errors.append(
            ValidationErrorItem(
                pointer=_pointer(["layers"]),
                message=f"number of layers must be between {MIN_LAYERS} and {MAX_LAYERS}",
            )
        )
    seen: dict[str, int] = {}
    for i, raw_id in enumerate(raw_layers):
        if not isinstance(raw_id, str):
            continue  # type error reported by Pydantic
        if not ID_PATTERN.match(raw_id):
            errors.append(
                ValidationErrorItem(
                    pointer=_pointer(["layers", i]),
                    message="layer id must match [A-Za-z0-9_-]{1,24}",
                )
            )
            continue
        if raw_id in seen:
            errors.append(
                ValidationErrorItem(
                    pointer=_pointer(["layers", i]),
                    message=f"duplicate layer id {raw_id!r}; first seen at index {seen[raw_id]}",
                )
            )
        else:
            seen[raw_id] = i

    # ---- observations -----------------------------------------------------
    raw_observations = data.get("observations")

    # Without a well-formed layer list, dangling/self/duplicate checks
    # would only add noise on top of the already-reported `layers` errors.
    if not isinstance(raw_layers, list):
        return errors

    if not isinstance(raw_observations, list):
        return errors  # type error reported by Pydantic

    if len(raw_observations) == 0:
        errors.append(
            ValidationErrorItem(
                pointer=_pointer(["observations"]),
                message="at least one directed observation is required",
            )
        )

    pairs: List[tuple[str, str]] = []
    for i, raw_obs in enumerate(raw_observations):
        if not isinstance(raw_obs, dict):
            continue  # type error reported by Pydantic
        lower = raw_obs.get("lower")
        upper = raw_obs.get("upper")
        if not isinstance(lower, str) or not isinstance(upper, str):
            continue
        lower_ok = lower in seen
        upper_ok = upper in seen
        if not lower_ok:
            errors.append(
                ValidationErrorItem(
                    pointer=_pointer(["observations", i, "lower"]),
                    message=f"dangling reference to unknown layer {lower!r}",
                )
            )
        if not upper_ok:
            errors.append(
                ValidationErrorItem(
                    pointer=_pointer(["observations", i, "upper"]),
                    message=f"dangling reference to unknown layer {upper!r}",
                )
            )
        if lower_ok and upper_ok:
            if lower == upper:
                errors.append(
                    ValidationErrorItem(
                        pointer=_pointer(["observations", i]),
                        message=f"self loop on layer {lower!r} is not allowed",
                    )
                )
            else:
                pair = (lower, upper)
                if pair in pairs:
                    errors.append(
                        ValidationErrorItem(
                            pointer=_pointer(["observations", i]),
                            message=(
                                f"duplicate directed pair {lower!r} -> {upper!r}; "
                                f"first seen at index {pairs.index(pair)}"
                            ),
                        )
                    )
                else:
                    pairs.append(pair)

    return errors
