import type {
  PlacementProfileResponse,
  ProblemPayload,
  SolutionResponse,
  ValidationErrorItem,
} from "./types";

export class SolveError extends Error {
  readonly errors: ValidationErrorItem[];

  constructor(errors: ValidationErrorItem[]) {
    super(errors.map((e) => `${e.pointer || "(body)"}: ${e.message}`).join("\n"));
    this.name = "SolveError";
    this.errors = errors;
  }
}

export async function solveProblem(payload: ProblemPayload): Promise<SolutionResponse> {
  const response = await fetch("/api/solve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (response.status === 422) {
    const data = (await response.json()) as { errors: ValidationErrorItem[] };
    throw new SolveError(data.errors ?? []);
  }
  if (!response.ok) {
    throw new SolveError([{ pointer: "", message: `server error ${response.status}` }]);
  }
  return (await response.json()) as SolutionResponse;
}

/**
 * Sensitivity profile for one layer: the same ProblemIn payload, plus the
 * clicked target. 422s use the identical {errors:[{pointer,message}]} shape
 * as /api/solve (an unknown target arrives with pointer "/target").
 */
export async function fetchPlacementProfile(
  payload: ProblemPayload,
  target: string,
): Promise<PlacementProfileResponse> {
  const response = await fetch("/api/placement-profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, target }),
  });

  if (response.status === 422) {
    const data = (await response.json()) as { errors: ValidationErrorItem[] };
    throw new SolveError(data.errors ?? []);
  }
  if (!response.ok) {
    throw new SolveError([{ pointer: "", message: `server error ${response.status}` }]);
  }
  return (await response.json()) as PlacementProfileResponse;
}
