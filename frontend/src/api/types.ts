// Friendly aliases over the types generated from the FastAPI OpenAPI schema.
// Regenerate schema.ts with `npm run gen:types` after changing backend schemas.
import type { components } from "./schema";

type S = components["schemas"];

export type Meta = S["Meta"];
export type Enrollment = S["EnrollmentOut"];
export type Need = S["NeedOut"];
export type Task = S["TaskOut"];
export type Patient = S["PatientOut"];
export type PatientList = S["PatientList"];
export type PatientDetail = S["PatientDetail"];
export type WorklistItem = S["WorklistItem"];
export type TaskList = S["TaskList"];

export type Role = "scheduler" | "clinical";
export type View = "worklist" | "patients";

export interface Filters {
  specialty: string;
  task_type: string;
  program: string;
  tier: string;
  search: string;
}

export const EMPTY_FILTERS: Filters = { specialty: "", task_type: "", program: "", tier: "", search: "" };
