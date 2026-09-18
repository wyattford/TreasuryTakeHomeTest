import type { FieldStatus } from "./types";

const STYLES: Record<FieldStatus, string> = {
  match: "bg-green-100 text-green-800 border-green-300",
  mismatch: "bg-red-100 text-red-800 border-red-300",
  flagged: "bg-amber-100 text-amber-800 border-amber-300",
  missing: "bg-gray-100 text-gray-700 border-gray-300",
};

const LABELS: Record<FieldStatus, string> = {
  match: "Match",
  mismatch: "Mismatch",
  flagged: "Needs review",
  missing: "Missing",
};

export function StatusBadge({ status }: { status: FieldStatus }) {
  return (
    <span
      className={`inline-block rounded-full border px-3 py-1 text-sm font-medium whitespace-nowrap ${STYLES[status]}`}
    >
      {LABELS[status]}
    </span>
  );
}
