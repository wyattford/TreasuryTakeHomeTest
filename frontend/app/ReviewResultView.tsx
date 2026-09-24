"use client";

import { useState } from "react";
import { labelImageUrl, saveDecision } from "./api";
import { StatusBadge } from "./StatusBadge";
import type { Decision, DecisionOut, FieldComparisonOut, ReviewResult } from "./types";

const FIELD_LABELS: Record<string, string> = {
  brand_name: "Brand name",
  class_type: "Class / type designation",
  abv: "Alcohol content",
  proof: "Proof",
  net_contents: "Net contents",
  name_address: "Name and address",
  government_warning: "Government warning statement",
  country_of_origin: "Country of origin",
  appellation: "Appellation of origin",
  sulfite_declaration: "Sulfite declaration",
  other_disclosure: "Other disclosure",
};

// Result field name -> the extracted field it was read from, where they
// differ, for looking up which side of the label it came from.
const SOURCE_FIELD: Record<string, string> = {
  abv: "abv_percent",
  government_warning: "government_warning_text",
};

function fieldLabel(fieldName: string): string {
  return FIELD_LABELS[fieldName] ?? fieldName;
}

// A "match" with nothing declared means the label was checked on its own —
// say what was actually established instead of implying a comparison.
function badgeLabel(c: FieldComparisonOut): string | undefined {
  if (c.status !== "match" || c.application_value !== null) return undefined;
  if (c.field_name === "proof" || c.field_name === "government_warning") return undefined;
  return c.extracted_value ? "Found" : "Not required";
}

const DECISIONS: { value: Decision; label: string; classes: string }[] = [
  { value: "accept", label: "Accept", classes: "border-green-600 bg-green-600 text-white hover:bg-green-700" },
  { value: "reject", label: "Reject", classes: "border-red-600 bg-red-600 text-white hover:bg-red-700" },
  { value: "follow_up", label: "Needs follow-up", classes: "border-amber-500 bg-amber-500 text-white hover:bg-amber-600" },
];

const DECISION_LABELS: Record<Decision, string> = {
  accept: "Accepted",
  reject: "Rejected",
  follow_up: "Marked for follow-up",
};

export function ReviewResultView({
  result,
  onNext,
  nextLabel = "Review next label →",
  inBatch = false,
}: {
  result: ReviewResult;
  onNext: () => void;
  nextLabel?: string;
  // In a batch, nobody pressed Review and waited — the timing line would be
  // meaningless (it includes the time spent queued behind other labels).
  inBatch?: boolean;
}) {
  const images = [
    { id: result.front_extraction_id, label: "Front label" },
    ...(result.back_extraction_id ? [{ id: result.back_extraction_id, label: "Back label" }] : []),
  ];
  const waitedSeconds = (result.latency_ms / 1000).toFixed(1);
  const readSeconds = (result.extraction_ms / 1000).toFixed(1);

  return (
    <section className="mt-8 rounded-lg border border-gray-200 p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-semibold text-gray-900">Review result</h2>
        <span
          className={`rounded-full px-4 py-1 text-base font-semibold ${
            result.overall_status === "clear" ? "bg-green-100 text-green-800" : "bg-amber-100 text-amber-800"
          }`}
        >
          {result.overall_status === "clear" ? "Everything checks out" : "Needs your review"}
        </span>
      </div>
      <p className="mt-1 text-sm text-gray-500">
        {inBatch
          ? `Read by ${result.model_used}`
          : `Ready ${waitedSeconds}s after you pressed Review · the label took ${readSeconds}s to read · ${result.model_used}`}
      </p>

      <div className="mt-4 grid grid-cols-1 gap-6 md:grid-cols-[240px_1fr]">
        <div className="flex gap-3 md:flex-col">
          {images.map((image) => (
            <a key={image.id} href={labelImageUrl(image.id)} target="_blank" rel="noreferrer" className="block flex-1">
              {/* eslint-disable-next-line @next/next/no-img-element -- served by the backend, not a static asset */}
              <img
                src={labelImageUrl(image.id)}
                alt={image.label}
                className="w-full rounded-md border border-gray-200 bg-gray-50 object-contain"
              />
              <span className="mt-1 block text-center text-sm text-gray-600">{image.label} (click to enlarge)</span>
            </a>
          ))}
        </div>

        <div className="divide-y divide-gray-200 border-t border-gray-200 md:border-t-0">
          {result.comparisons.map((c, i) => {
            const side = result.field_sources[SOURCE_FIELD[c.field_name] ?? c.field_name];
            return (
              <div key={`${c.field_name}-${i}`} className="grid grid-cols-1 gap-2 py-3 sm:grid-cols-[1fr_auto]">
                <div>
                  <div className="text-base font-medium text-gray-900">{fieldLabel(c.field_name)}</div>
                  {(c.application_value || c.extracted_value) && (
                    <div className="mt-1 text-sm text-gray-700">
                      {c.application_value && (
                        <div>
                          {/* The warning is compared against the text the regulation prescribes, not the application. */}
                          {c.field_name === "government_warning" ? "Required wording" : "Application says"}:{" "}
                          {c.application_value}
                        </div>
                      )}
                      {c.extracted_value && (
                        <div>
                          Label says: &ldquo;{c.extracted_value}&rdquo;
                          {side && images.length > 1 && <span className="text-gray-500"> ({side} label)</span>}
                        </div>
                      )}
                    </div>
                  )}
                  {c.detail && <div className="mt-1 text-sm text-gray-500">{c.detail}</div>}
                </div>
                <div className="sm:justify-self-end">
                  <StatusBadge status={c.status} label={badgeLabel(c)} />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <DecisionPanel
        applicationId={result.application.id}
        initial={result.decision}
        onNext={onNext}
        nextLabel={nextLabel}
      />
    </section>
  );
}

function DecisionPanel({
  applicationId,
  initial,
  onNext,
  nextLabel,
}: {
  applicationId: string;
  initial: DecisionOut | null;
  onNext: () => void;
  nextLabel: string;
}) {
  const [saved, setSaved] = useState<DecisionOut | null>(initial);
  const [note, setNote] = useState(initial?.note ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function decide(decision: Decision) {
    setSaving(true);
    setError(null);
    try {
      setSaved(await saveDecision(applicationId, decision, note));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-6 rounded-lg bg-gray-50 p-4">
      <h3 className="text-base font-semibold text-gray-900">Your decision</h3>
      <p className="text-sm text-gray-600">This tool only pre-screens — the final call is yours.</p>
      <label className="mt-3 block text-sm">
        <span className="mb-1 block font-medium text-gray-800">Note (optional)</span>
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} className="input" />
      </label>
      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {DECISIONS.map((d) => (
          <button
            key={d.value}
            type="button"
            disabled={saving}
            onClick={() => decide(d.value)}
            className={`rounded-md border-2 px-4 py-3 text-base font-semibold disabled:opacity-50 ${d.classes} ${
              saved?.decision === d.value ? "ring-4 ring-gray-900/30" : ""
            }`}
          >
            {d.label}
          </button>
        ))}
      </div>
      {error && <p className="mt-2 text-sm text-red-700">{error}</p>}
      {saved && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-base text-gray-800">
            ✓ {DECISION_LABELS[saved.decision]} at {new Date(saved.decided_at).toLocaleTimeString()}
          </p>
          <button
            type="button"
            onClick={onNext}
            className="rounded-md bg-gray-900 px-4 py-3 text-base font-medium text-white hover:bg-gray-800"
          >
            {nextLabel}
          </button>
        </div>
      )}
    </div>
  );
}
