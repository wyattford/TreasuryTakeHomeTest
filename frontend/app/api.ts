import type { Decision, DecisionOut, ExtractedApplicationFields, ExtractionOut, ReviewResult } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// Longest the backend will hold a status request open waiting for an
// extraction to finish (see GET /extractions/{id}?wait=).
const EXTRACTION_POLL_WAIT_SECONDS = 25;

export interface ReviewFormValues {
  frontExtractionId: string;
  backExtractionId: string | null;
  beverageClass: string;
  imported: boolean;
  brandName: string;
  fancifulName: string;
  classType: string;
  abv: string;
  netContents: string;
  nameAddress: string;
  countryOfOrigin: string;
  appellation: string;
  sulfiteDeclaration: string;
}

async function throwIfNotOk(res: Response, fallbackMessage: string): Promise<void> {
  if (res.ok) return;
  const body = await res.json().catch(() => null);
  throw new Error(typeof body?.detail === "string" ? body.detail : fallbackMessage);
}

function appendIfSet(form: FormData, key: string, value: string) {
  if (value.trim()) form.append(key, value.trim());
}

function toFormData(values: ReviewFormValues): FormData {
  const form = new FormData();
  form.append("front_extraction_id", values.frontExtractionId);
  if (values.backExtractionId) form.append("back_extraction_id", values.backExtractionId);
  form.append("beverage_class", values.beverageClass);
  form.append("imported", String(values.imported));
  // Every declared field is optional — blank ones are checked against the
  // label's own requirements instead of against the application.
  appendIfSet(form, "brand_name", values.brandName);
  appendIfSet(form, "fanciful_name", values.fancifulName);
  appendIfSet(form, "class_type", values.classType);
  appendIfSet(form, "abv", values.abv);
  appendIfSet(form, "net_contents", values.netContents);
  appendIfSet(form, "name_address", values.nameAddress);
  appendIfSet(form, "country_of_origin", values.countryOfOrigin);
  appendIfSet(form, "appellation", values.appellation);
  appendIfSet(form, "sulfite_declaration", values.sulfiteDeclaration);
  return form;
}

export function labelImageUrl(extractionId: string): string {
  return `${API_BASE}/extractions/${extractionId}/image`;
}

/** Uploads a label image; the backend starts reading it immediately. */
export async function startExtraction(image: File): Promise<ExtractionOut> {
  const form = new FormData();
  form.append("image", image);
  const res = await fetch(`${API_BASE}/extractions`, { method: "POST", body: form });
  await throwIfNotOk(res, `Upload failed (${res.status}).`);
  return (await res.json()) as ExtractionOut;
}

/** Long-polls until the extraction is no longer pending, or `isStale()`
 * says the caller stopped caring (e.g. the user picked a different photo). */
export async function waitForExtraction(id: string, isStale: () => boolean): Promise<ExtractionOut | null> {
  while (!isStale()) {
    const res = await fetch(`${API_BASE}/extractions/${id}?wait=${EXTRACTION_POLL_WAIT_SECONDS}`);
    await throwIfNotOk(res, `Checking the upload failed (${res.status}).`);
    const extraction = (await res.json()) as ExtractionOut;
    if (extraction.status !== "pending") return extraction;
  }
  return null;
}

/** Fire-and-forget: frees the model from a photo the user replaced. */
export function cancelExtraction(id: string): void {
  fetch(`${API_BASE}/extractions/${id}`, { method: "DELETE" }).catch(() => {});
}

export async function submitReview(values: ReviewFormValues): Promise<ReviewResult> {
  const res = await fetch(`${API_BASE}/reviews`, {
    method: "POST",
    body: toFormData(values),
  });

  await throwIfNotOk(res, `Review request failed (${res.status}).`);

  return (await res.json()) as ReviewResult;
}

export async function saveDecision(applicationId: string, decision: Decision, note: string): Promise<DecisionOut> {
  const res = await fetch(`${API_BASE}/reviews/${applicationId}/decision`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, note }),
  });
  await throwIfNotOk(res, `Saving the decision failed (${res.status}).`);
  return (await res.json()) as DecisionOut;
}

export async function extractApplicationPdf(file: File): Promise<ExtractedApplicationFields> {
  const form = new FormData();
  form.append("file", file);

  const res = await fetch(`${API_BASE}/applications/extract-pdf`, {
    method: "POST",
    body: form,
  });

  await throwIfNotOk(res, `PDF extraction failed (${res.status}).`);

  return (await res.json()) as ExtractedApplicationFields;
}
