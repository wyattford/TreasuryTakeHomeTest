import type { BatchItemOut, BatchStatus } from "../types";

export const BATCH_STATUS_LABELS: Record<BatchStatus, string> = {
  uploading: "waiting for photos",
  running: "reviewing",
  done: "finished",
  cancelled: "cancelled",
};

export function ProgressBar({ value, total }: { value: number; total: number }) {
  const percent = total ? Math.round((value / total) * 100) : 0;
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={value}
      className="h-4 w-full overflow-hidden rounded-full bg-gray-200"
    >
      <div className="h-full rounded-full bg-gray-900 transition-[width]" style={{ width: `${percent}%` }} />
    </div>
  );
}

export type Outcome = "flagged" | "error" | "clear" | "working" | "skipped";

export function outcomeOf(item: BatchItemOut): Outcome {
  if (item.status === "error") return "error";
  if (item.status === "skipped") return "skipped";
  if (item.overall_status) return item.overall_status;
  return "working";
}

// Triage order: what needs an agent's attention first.
export const OUTCOME_ORDER: Outcome[] = ["flagged", "error", "clear", "working", "skipped"];

export const OUTCOME_LABELS: Record<Outcome, string> = {
  flagged: "Needs your review",
  error: "Couldn't be read",
  clear: "Everything checks out",
  working: "Still working",
  skipped: "Skipped",
};

export const OUTCOME_STYLES: Record<Outcome, string> = {
  flagged: "bg-amber-100 text-amber-900 border-amber-300",
  error: "bg-red-100 text-red-800 border-red-300",
  clear: "bg-green-100 text-green-800 border-green-300",
  working: "bg-gray-100 text-gray-700 border-gray-300",
  skipped: "bg-gray-100 text-gray-500 border-gray-300",
};

export function outcomeDetail(item: BatchItemOut): string {
  switch (outcomeOf(item)) {
    case "flagged":
      return `${item.attention_count} item${item.attention_count === 1 ? "" : "s"} to check`;
    case "error":
      return item.error_message ?? "The label couldn't be read.";
    case "working":
      return item.status === "awaiting_images" ? "Waiting for photos" : "Reading the label…";
    default:
      return "";
  }
}

export function formatDuration(seconds: number): string {
  if (seconds < 90) return "about a minute";
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `about ${minutes} minutes`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `about ${hours} hour${hours === 1 ? "" : "s"}${rest ? ` ${rest} min` : ""}`;
}
