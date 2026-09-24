"use client";

import { FormEvent, useState } from "react";
import { extractApplicationPdf, submitReview } from "./api";
import { ReviewResultView } from "./ReviewResultView";
import type { ExtractedApplicationFields, ReviewResult } from "./types";
import { type LabelUpload, useLabelUpload } from "./useLabelUpload";

const FILE_INPUT_CLASSES =
  "block w-full text-sm text-gray-600 file:mr-3 file:rounded-md file:border-0 file:bg-gray-900 " +
  "file:px-3 file:py-2 file:text-sm file:font-medium file:text-white file:cursor-pointer " +
  "hover:file:bg-gray-800";

// Every key of ExtractedApplicationFields mapped to the form field it fills.
// Keeping this as one exhaustive table (rather than hand-written per-field
// branches) means adding a field to ExtractedApplicationFields is a type
// error here until it's mapped, instead of silently doing nothing.
const EXTRACTED_FIELD_MAP: { [K in keyof ExtractedApplicationFields]: keyof typeof EMPTY_FORM } = {
  beverage_class: "beverageClass",
  imported: "imported",
  brand_name: "brandName",
  fanciful_name: "fancifulName",
  name_address: "nameAddress",
  appellation: "appellation",
};
const PDF_MAPPED_FIELD_COUNT = Object.keys(EXTRACTED_FIELD_MAP).length;

function applyExtractedFields(extracted: ExtractedApplicationFields): {
  patch: Partial<typeof EMPTY_FORM>;
  filledCount: number;
} {
  const patch: Partial<typeof EMPTY_FORM> = {};
  let filledCount = 0;
  for (const [srcKey, dstKey] of Object.entries(EXTRACTED_FIELD_MAP) as [
    keyof ExtractedApplicationFields,
    keyof typeof EMPTY_FORM,
  ][]) {
    const value = extracted[srcKey];
    if (value != null) {
      (patch as Record<string, unknown>)[dstKey] = value;
      filledCount += 1;
    }
  }
  return { patch, filledCount };
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
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
  const front = useLabelUpload();
  const back = useLabelUpload();
  // Bumped to remount (and so clear) the file inputs when starting over.
  const [formKey, setFormKey] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [pdfNotice, setPdfNotice] = useState<{ kind: "success" | "error"; message: string } | null>(null);

  const isWine = form.beverageClass === "wine";
  const stillReading = [front.upload, back.upload].some((u) => u?.status === "uploading" || u?.status === "reading");

  function set<K extends keyof typeof EMPTY_FORM>(key: K, value: (typeof EMPTY_FORM)[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function onApplicationPdfChange(file: File | null) {
    if (!file) return;
    setPdfLoading(true);
    setPdfNotice(null);
    try {
      const extracted = await extractApplicationPdf(file);
      const { patch, filledCount } = applyExtractedFields(extracted);
      setForm((prev) => ({ ...prev, ...patch }));
      setPdfNotice({
        kind: "success",
        message:
          filledCount > 0
            ? `Filled ${filledCount} of ${PDF_MAPPED_FIELD_COUNT} fields from the PDF. Class/type, alcohol ` +
              "content, net contents, country of origin, and sulfite declaration aren't captured on the " +
              "application form itself — enter those from the label."
            : "Couldn't find any recognized fields in that PDF — it may not be TTB F 5100.31, or none of " +
              "its fields were filled in. Please enter the application data manually.",
      });
    } catch (err) {
      setPdfNotice({ kind: "error", message: errorMessage(err) });
    } finally {
      setPdfLoading(false);
    }
  }

  function startOver() {
    front.reset();
    back.reset();
    setForm(EMPTY_FORM);
    setResult(null);
    setError(null);
    setPdfNotice(null);
    setFormKey((k) => k + 1);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const blocked = uploadProblem(front.upload, "front", true) ?? uploadProblem(back.upload, "back", false);
    if (blocked) {
      setError(blocked);
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const review = await submitReview({
        frontExtractionId: front.upload!.extractionId!,
        backExtractionId: back.upload?.extractionId ?? null,
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
      requestAnimationFrame(() => document.getElementById("review-result")?.scrollIntoView({ behavior: "smooth" }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-10">
      <h1 className="text-2xl font-semibold text-gray-900">Review one label</h1>
      <p className="mt-1 text-gray-600">
        Add the label photo first — it starts being read right away. Then fill in whatever the
        application (TTB F 5100.31) declares, and press Review.
      </p>

      <div key={`pdf-${formKey}`} className="mt-6 rounded-lg border border-dashed border-gray-300 p-4">
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-gray-800">
            Upload TTB F 5100.31 application (optional)
          </span>
          <input
            type="file"
            accept="application/pdf"
            disabled={pdfLoading}
            onChange={(e) => onApplicationPdfChange(e.target.files?.[0] ?? null)}
            className={FILE_INPUT_CLASSES}
          />
        </label>
        <p className="mt-1 text-xs text-gray-500">
          Pre-fills the fields below from a filled-in copy of the application PDF. Only works for a PDF
          that still has its fillable form fields — not a scanned or flattened copy.
        </p>
        {pdfLoading && <p className="mt-2 text-sm text-gray-600">Reading PDF…</p>}
        {pdfNotice && (
          <p className={`mt-2 text-sm ${pdfNotice.kind === "error" ? "text-red-700" : "text-gray-700"}`}>
            {pdfNotice.message}
          </p>
        )}
      </div>

      <form key={`form-${formKey}`} onSubmit={onSubmit} className="mt-6 space-y-6 rounded-lg border border-gray-200 p-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <LabelPicker title="Front label photo" required upload={front.upload} onChoose={front.choose} />
          <LabelPicker title="Back label photo (if any)" upload={back.upload} onChoose={back.choose} />

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
              className="h-5 w-5"
            />
            <label htmlFor="imported" className="text-base text-gray-800">
              Imported product
            </label>
          </div>
        </div>

        <h2 className="pt-2 text-sm font-semibold tracking-wide text-gray-500 uppercase">
          Application data (TTB F 5100.31)
        </h2>
        <p className="-mt-4 text-sm text-gray-600">
          All optional. Anything you fill in is checked against the label; anything left blank is
          still checked on the label itself (is it there, is it a standard size, and so on).
        </p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Brand name">
            <input value={form.brandName} onChange={(e) => set("brandName", e.target.value)} className="input" />
          </Field>
          <Field label="Fanciful name">
            <input value={form.fancifulName} onChange={(e) => set("fancifulName", e.target.value)} className="input" />
          </Field>
          <Field label="Class / type designation">
            <input value={form.classType} onChange={(e) => set("classType", e.target.value)} className="input" />
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
          <Field label="Net contents">
            <input
              value={form.netContents}
              onChange={(e) => set("netContents", e.target.value)}
              placeholder="e.g. 750 mL or 12 FL OZ"
              className="input"
            />
          </Field>
          <Field label="Name and address">
            <input value={form.nameAddress} onChange={(e) => set("nameAddress", e.target.value)} className="input" />
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
          {loading ? (stillReading ? "Finishing reading the label…" : "Reviewing…") : "Review label"}
        </button>
      </form>

      {error && (
        <div className="mt-6 rounded-md border border-red-300 bg-red-50 p-4 text-red-800">{error}</div>
      )}

      {result && (
        <div id="review-result">
          <ReviewResultView result={result} onNext={startOver} />
        </div>
      )}

      <p className="mt-8 text-sm text-gray-500">
        This tool is a pre-screen only. Type-size and contrast requirements can&apos;t be verified
        from a photo and require manual review.
      </p>
    </main>
  );
}

// Why a label image can't be submitted yet, or null if it's fine. An image
// that's still being read (or failed to be read) is fine — the review waits
// for it, and retries a failed read once.
function uploadProblem(upload: LabelUpload | null, side: string, required: boolean): string | null {
  if (!upload) return required ? `Please add a ${side} label photo.` : null;
  if (upload.rejected) return `The ${side} label photo couldn't be used: ${upload.error} Please choose another.`;
  if (!upload.extractionId) return `The ${side} label photo is still uploading — one moment.`;
  return null;
}

function LabelPicker({
  title,
  required,
  upload,
  onChoose,
}: {
  title: string;
  required?: boolean;
  upload: LabelUpload | null;
  onChoose: (file: File | null) => void;
}) {
  return (
    <Field label={title} required={required}>
      <input
        type="file"
        accept="image/png,image/jpeg,image/gif,image/webp"
        onChange={(e) => onChoose(e.target.files?.[0] ?? null)}
        className={FILE_INPUT_CLASSES}
      />
      {upload && <UploadStatus upload={upload} />}
    </Field>
  );
}

function UploadStatus({ upload }: { upload: LabelUpload }) {
  switch (upload.status) {
    case "uploading":
      return <p className="mt-2 text-sm text-gray-600">Uploading…</p>;
    case "reading":
      return <p className="mt-2 text-sm text-gray-600">Reading the label… you can keep filling in the form.</p>;
    case "done":
      return (
        <p className="mt-2 text-sm text-green-700">
          ✓ Label read{upload.latencyMs !== null ? ` (${(upload.latencyMs / 1000).toFixed(1)}s)` : ""}
        </p>
      );
    case "error":
      return (
        <p className="mt-2 text-sm text-red-700">
          {upload.rejected ? upload.error : `Couldn't read this yet (${upload.error}). It will be tried again when you press Review.`}
        </p>
      );
  }
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
