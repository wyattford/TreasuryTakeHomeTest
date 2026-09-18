import type { ReviewResult } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface ReviewFormValues {
  front: File;
  back: File | null;
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

function toFormData(values: ReviewFormValues): FormData {
  const form = new FormData();
  form.append("front", values.front);
  if (values.back) form.append("back", values.back);
  form.append("beverage_class", values.beverageClass);
  form.append("imported", String(values.imported));
  form.append("brand_name", values.brandName);
  if (values.fancifulName) form.append("fanciful_name", values.fancifulName);
  form.append("class_type", values.classType);
  if (values.abv) form.append("abv", values.abv);
  form.append("net_contents", values.netContents);
  form.append("name_address", values.nameAddress);
  if (values.countryOfOrigin) form.append("country_of_origin", values.countryOfOrigin);
  if (values.appellation) form.append("appellation", values.appellation);
  if (values.sulfiteDeclaration) form.append("sulfite_declaration", values.sulfiteDeclaration);
  return form;
}

export async function submitReview(values: ReviewFormValues): Promise<ReviewResult> {
  const res = await fetch(`${API_BASE}/reviews`, {
    method: "POST",
    body: toFormData(values),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Review request failed (${res.status}).`);
  }

  return (await res.json()) as ReviewResult;
}
