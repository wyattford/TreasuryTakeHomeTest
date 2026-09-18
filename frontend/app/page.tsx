"use client";

import { FormEvent, useState } from "react";
import { submitReview } from "./api";
import { StatusBadge } from "./StatusBadge";
import type { ReviewResult } from "./types";

const FIELD_LABELS: Record<string, string> = {
  brand_name: "Brand name",
  class_type: "Class / type designation",
  abv: "Alcohol content",
  net_contents: "Net contents",
  name_address: "Name and address",
  government_warning: "Government warning statement",
  country_of_origin: "Country of origin",
  appellation: "Appellation of origin",
  sulfite_declaration: "Sulfite declaration",
  other_disclosure: "Other disclosure",
};

function fieldLabel(fieldName: string): string {
  if (fieldName.startsWith("illegible:")) {
    const inner = fieldName.slice("illegible:".length);
    return `${FIELD_LABELS[inner] ?? inner} (illegible on label)`;
  }
  return FIELD_LABELS[fieldName] ?? fieldName;
}

const EMPTY_FORM = {
  beverageClass: "distilled_spirits",
  imported: false,
  brandName: "",
  fancifulName: "",
  classType: "",
  abv: "",
  netContents: "",
  nameAddress: "",
  countryOfOrigin: "",
  appellation: "",
  sulfiteDeclaration: "",
};

export default function Home() {
  const [form, setForm] = useState(EMPTY_FORM);
  const [front, setFront] = useState<File | null>(null);
  const [back, setBack] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ReviewResult | null>(null);

  const isWine = form.beverageClass === "wine";

  function set<K extends keyof typeof EMPTY_FORM>(key: K, value: (typeof EMPTY_FORM)[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!front) {
      setError("Please choose a front label image.");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const review = await submitReview({
        front,
        back,
        beverageClass: form.beverageClass,
        imported: form.imported,
        brandName: form.brandName,
        fancifulName: form.fancifulName,
        classType: form.classType,
        abv: form.abv,
        netContents: form.netContents,
        nameAddress: form.nameAddress,
        countryOfOrigin: form.countryOfOrigin,
        appellation: form.appellation,
        sulfiteDeclaration: form.sulfiteDeclaration,
      });
      setResult(review);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="text-2xl font-semibold text-gray-900">TTB Label Review</h1>
      <p className="mt-1 text-gray-600">
        Upload a label image and the application details declared on TTB F 5100.31 — this
        checks that what&apos;s on the label matches what was submitted.
      </p>

      <form onSubmit={onSubmit} className="mt-8 space-y-6 rounded-lg border border-gray-200 p-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Front label image" required>
            <input
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp"
              onChange={(e) => setFront(e.target.files?.[0] ?? null)}
              className="block w-full text-sm"
              required
            />
          </Field>
          <Field label="Back label image (optional)">
            <input
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp"
              onChange={(e) => setBack(e.target.files?.[0] ?? null)}
              className="block w-full text-sm"
            />
          </Field>

          <Field label="Beverage class" required>
            <select
              value={form.beverageClass}
              onChange={(e) => set("beverageClass", e.target.value)}
              className="input"
            >
              <option value="distilled_spirits">Distilled spirits</option>
              <option value="wine">Wine</option>
              <option value="malt_beverage">Malt beverage</option>
            </select>
          </Field>

          <div className="flex items-end gap-2 pb-2">
            <input
              id="imported"
              type="checkbox"
              checked={form.imported}
              onChange={(e) => set("imported", e.target.checked)}
            />
            <label htmlFor="imported" className="text-sm text-gray-800">
              Imported product
            </label>
          </div>
        </div>

        <h2 className="pt-2 text-sm font-semibold tracking-wide text-gray-500 uppercase">
          Application data (TTB F 5100.31)
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Brand name" required>
            <input value={form.brandName} onChange={(e) => set("brandName", e.target.value)} className="input" required />
          </Field>
          <Field label="Fanciful name">
            <input value={form.fancifulName} onChange={(e) => set("fancifulName", e.target.value)} className="input" />
          </Field>
          <Field label="Class / type designation" required>
            <input value={form.classType} onChange={(e) => set("classType", e.target.value)} className="input" required />
          </Field>
          <Field label="Alcohol content (%)">
            <input
              type="number"
              step="0.1"
              value={form.abv}
              onChange={(e) => set("abv", e.target.value)}
              className="input"
            />
          </Field>
          <Field label="Net contents" required>
            <input
              value={form.netContents}
              onChange={(e) => set("netContents", e.target.value)}
              placeholder="e.g. 750 mL"
              className="input"
              required
            />
          </Field>
          <Field label="Name and address" required>
            <input value={form.nameAddress} onChange={(e) => set("nameAddress", e.target.value)} className="input" required />
          </Field>
          <Field label={`Country of origin${form.imported ? " (required for imports)" : ""}`}>
            <input value={form.countryOfOrigin} onChange={(e) => set("countryOfOrigin", e.target.value)} className="input" />
          </Field>
          {isWine && (
            <>
              <Field label="Appellation of origin">
                <input value={form.appellation} onChange={(e) => set("appellation", e.target.value)} className="input" />
              </Field>
              <Field label="Sulfite declaration">
                <input
                  value={form.sulfiteDeclaration}
                  onChange={(e) => set("sulfiteDeclaration", e.target.value)}
                  className="input"
                />
              </Field>
            </>
          )}
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-md bg-gray-900 px-4 py-3 text-base font-medium text-white hover:bg-gray-800 disabled:opacity-50"
        >
          {loading ? "Reviewing…" : "Review label"}
        </button>
      </form>

      {error && (
        <div className="mt-6 rounded-md border border-red-300 bg-red-50 p-4 text-red-800">{error}</div>
      )}

      {result && (
        <section className="mt-8 rounded-lg border border-gray-200 p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900">Review result</h2>
            <span
              className={`rounded-full px-4 py-1 text-sm font-semibold ${
                result.overall_status === "clear" ? "bg-green-100 text-green-800" : "bg-amber-100 text-amber-800"
              }`}
            >
              {result.overall_status === "clear" ? "Clear" : "Needs review"}
            </span>
          </div>
          <p className="mt-1 text-sm text-gray-500">
            {result.model_used} · {(result.latency_ms / 1000).toFixed(1)}s
          </p>

          <div className="mt-4 divide-y divide-gray-200 border-t border-gray-200">
            {result.comparisons.map((c, i) => (
              <div key={`${c.field_name}-${i}`} className="grid grid-cols-1 gap-2 py-3 sm:grid-cols-[1fr_auto]">
                <div>
                  <div className="font-medium text-gray-900">{fieldLabel(c.field_name)}</div>
                  {(c.application_value || c.extracted_value) && (
                    <div className="mt-1 text-sm text-gray-600">
                      {c.application_value && <div>Declared: {c.application_value}</div>}
                      {c.extracted_value && <div>On label: &ldquo;{c.extracted_value}&rdquo;</div>}
                    </div>
                  )}
                  {c.detail && <div className="mt-1 text-sm text-gray-500">{c.detail}</div>}
                </div>
                <div className="sm:justify-self-end">
                  <StatusBadge status={c.status} />
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <p className="mt-8 text-sm text-gray-500">
        This tool is a pre-screen only. Type-size and contrast requirements can&apos;t be verified
        from a photo and require manual review.
      </p>
    </main>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-gray-800">
        {label}
        {required && <span className="text-red-600"> *</span>}
      </span>
      {children}
    </label>
  );
}
