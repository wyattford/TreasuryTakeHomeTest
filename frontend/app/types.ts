// Mirrors backend/app/schemas.py — keep these in sync by hand for now; a
// generated client (e.g. from the OpenAPI schema FastAPI already exposes)
// would be the next step if this grows past a prototype.

export type BeverageClass = "distilled_spirits" | "wine" | "malt_beverage";

export interface ApplicationOut {
  id: string;
  beverage_class: BeverageClass;
  imported: boolean;
  brand_name: string | null;
  fanciful_name: string | null;
  class_type: string | null;
  abv: number | null;
  net_contents: string | null;
  name_address: string | null;
  country_of_origin: string | null;
  appellation: string | null;
  sulfite_declaration: string | null;
  submitted_at: string;
}

export interface ExtractedApplicationFields {
  beverage_class: BeverageClass | null;
  imported: boolean | null;
  brand_name: string | null;
  fanciful_name: string | null;
  name_address: string | null;
  appellation: string | null;
}

export interface ExtractedLabelFields {
  brand_name: string | null;
  fanciful_name: string | null;
  class_type: string | null;
  abv_percent: number | null;
  proof: number | null;
  net_contents: string | null;
  name_address: string | null;
  country_of_origin: string | null;
  appellation: string | null;
  sulfite_declaration: string | null;
  government_warning_text: string | null;
  other_disclosures: string[];
  illegible_fields: string[];
}

export type ExtractionStatus = "pending" | "done" | "error" | "cancelled";

export interface ExtractionOut {
  id: string;
  status: ExtractionStatus;
  error_message: string | null;
  latency_ms: number | null;
  extracted_fields: ExtractedLabelFields | null;
}

export type Decision = "accept" | "reject" | "follow_up";

export interface DecisionOut {
  decision: Decision;
  note: string | null;
  decided_at: string;
}

export type FieldStatus = "match" | "mismatch" | "flagged" | "missing";

export interface FieldComparisonOut {
  field_name: string;
  application_value: string | null;
  extracted_value: string | null;
  match_type: string;
  status: FieldStatus;
  detail: string | null;
}

export interface ReviewResult {
  application: ApplicationOut;
  front_extraction_id: string;
  back_extraction_id: string | null;
  extracted_fields: ExtractedLabelFields;
  field_sources: Record<string, "front" | "back">;
  comparisons: FieldComparisonOut[];
  model_used: string;
  latency_ms: number; // time the user waited after submitting
  extraction_ms: number; // time the model spent reading the label
  overall_status: "clear" | "flagged";
  decision: DecisionOut | null;
}

export interface ApiError {
  error: string;
}
