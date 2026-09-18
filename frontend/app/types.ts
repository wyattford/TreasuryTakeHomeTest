// Mirrors backend/app/schemas.py — keep these in sync by hand for now; a
// generated client (e.g. from the OpenAPI schema FastAPI already exposes)
// would be the next step if this grows past a prototype.

export type BeverageClass = "distilled_spirits" | "wine" | "malt_beverage";

export interface ApplicationOut {
  id: string;
  beverage_class: BeverageClass;
  imported: boolean;
  brand_name: string;
  fanciful_name: string | null;
  class_type: string;
  abv: number | null;
  net_contents: string;
  name_address: string;
  country_of_origin: string | null;
  appellation: string | null;
  sulfite_declaration: string | null;
  submitted_at: string;
}

export interface ExtractedLabelFields {
  brand_name: string | null;
  fanciful_name: string | null;
  class_type: string | null;
  abv_percent: number | null;
  net_contents: string | null;
  name_address: string | null;
  country_of_origin: string | null;
  appellation: string | null;
  sulfite_declaration: string | null;
  government_warning_text: string | null;
  other_disclosures: string[];
  illegible_fields: string[];
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
  extracted_fields: ExtractedLabelFields;
  comparisons: FieldComparisonOut[];
  model_used: string;
  latency_ms: number;
  overall_status: "clear" | "flagged";
}

export interface ApiError {
  error: string;
}
