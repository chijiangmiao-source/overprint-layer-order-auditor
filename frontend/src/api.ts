import type { ProblemPayload, SolutionResponse, ValidationErrorItem } from "./types";

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
