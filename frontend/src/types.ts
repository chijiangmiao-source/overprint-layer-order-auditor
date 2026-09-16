export interface ObservationInput {
  lower: string;
  upper: string;
  weight: number;
}

export interface ProblemPayload {
  layers: string[];
  observations: ObservationInput[];
}

export interface ValidationErrorItem {
  pointer: string;
  message: string;
}

export interface ObservationResult {
  lower: string;
  upper: string;
  weight: number;
  lower_position: number;
  upper_position: number;
  violated: boolean;
  cost: number;
}

export interface Witness {
  order: string[];
  cost: number;
  observations: ObservationResult[];
}

export interface SolutionResponse {
  status: "unique" | "ambiguous";
  cost: number;
  order: string[];
  witness: Witness;
  second_cost: number | null;
  second_order: string[] | null;
  second_witness: Witness | null;
  layers: string[];
}
