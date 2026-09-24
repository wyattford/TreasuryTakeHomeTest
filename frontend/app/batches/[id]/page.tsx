"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useState } from "react";
import { batchExportUrl, cancelBatch, getBatch, getReview, labelImageUrl, retryFailedBatchItems } from "../../api";
import { ReviewResultView } from "../../ReviewResultView";
import type { BatchItemOut, BatchOut, ReviewResult } from "../../types";
import { DropZone } from "../DropZone";
import {
  BATCH_STATUS_LABELS,
  OUTCOME_LABELS,
  OUTCOME_ORDER,
  OUTCOME_STYLES,
  type Outcome,
  ProgressBar,
  formatDuration,
  outcomeDetail,
  outcomeOf,
} from "../shared";
import { uploadBatchImages } from "../upload";

const POLL_MS = 2000;

const DECISION_LABELS = { accept: "Accepted", reject: "Rejected", follow_up: "Follow-up" } as const;

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function triageOrder(items: BatchItemOut[]): BatchItemOut[] {
  return [...items].sort(
    (a, b) => OUTCOME_ORDER.indexOf(outcomeOf(a)) - OUTCOME_ORDER.indexOf(outcomeOf(b)) || a.row_number - b.row_number,
  );
}

export default function BatchPage({ params }: PageProps<"/batches/[id]">) {
  const { id } = use(params);
  const [batch, setBatch] = useState<BatchOut | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Outcome | "all">("all");
  const [openItemId, setOpenItemId] = useState<string | null>(null);
  const [upload, setUpload] = useState<{ done: number; total: number } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setBatch(await getBatch(id));
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
    }
  }, [id]);

  const active = batch?.status === "running" || batch?.status === "uploading" || !!upload;
  useEffect(() => {
    // Initial load, then keep polling while there's work in progress.
    let stopped = false;
    const refresh = () =>
      getBatch(id).then(
        (fresh) => {
          if (stopped) return;
          setBatch(fresh);
          setLoadError(null);
        },
        (err) => !stopped && setLoadError(errorMessage(err)),
      );
    void refresh();
    const timer = active ? setInterval(refresh, POLL_MS) : undefined;
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [id, active]);

  const ordered = useMemo(() => (batch ? triageOrder(batch.items) : []), [batch]);
  const visible = filter === "all" ? ordered : ordered.filter((i) => outcomeOf(i) === filter);
  // Items that can be opened: reviewed ones, in the order shown.
  const openable = visible.filter((i) => i.application_id && i.status === "reviewed");

  if (loadError && !batch) {
    return (
      <main className="mx-auto w-full max-w-5xl px-4 py-10">
        <p className="text-red-700">{loadError}</p>
        <Link href="/batches" className="mt-4 inline-block underline">
          ← All batches
        </Link>
      </main>
    );
  }
  if (!batch) return <main className="mx-auto w-full max-w-5xl px-4 py-10 text-gray-600">Loading…</main>;

  const openIndex = openable.findIndex((i) => i.id === openItemId);
  if (openItemId && openIndex !== -1) {
    const goTo = (index: number) => {
      void load(); // refresh the decisions shown in the list
      setOpenItemId(openable[index]?.id ?? null);
      window.scrollTo({ top: 0 });
    };
    return (
      <main className="mx-auto w-full max-w-5xl px-4 py-6">
        <ItemDetail
          key={openable[openIndex].id}
          item={openable[openIndex]}
          position={`${openIndex + 1} of ${openable.length}${filter === "all" ? "" : ` (${OUTCOME_LABELS[filter]})`}`}
          onBack={() => goTo(-1)}
          onPrevious={openIndex > 0 ? () => goTo(openIndex - 1) : null}
          onNext={openIndex < openable.length - 1 ? () => goTo(openIndex + 1) : null}
        />
      </main>
    );
  }

  const { counts } = batch;
  const finished = counts.clear + counts.flagged + counts.error + counts.skipped;
  const counted = (outcome: Outcome) =>
    outcome === "working" ? counts.awaiting_images + counts.queued : counts[outcome];

  async function onRedrop(files: File[]) {
    if (!batch) return;
    setNotice(null);
    setUpload({ done: 0, total: 0 });
    try {
      const result = await uploadBatchImages(batch.id, batch.items, files, (done, total) => setUpload({ done, total }));
      const parts = [`Uploaded photos for ${result.uploaded} application(s).`];
      if (result.failures.length) parts.push(`${result.failures.length} couldn't be uploaded: ${result.failures[0].message}`);
      if (result.missing.length) {
        const n = result.missing.length;
        parts.push(`${n} still ${n === 1 ? "has" : "have"} no matching photos in what you dropped.`);
      }
      setNotice(parts.join(" "));
    } catch (err) {
      setNotice(errorMessage(err));
    } finally {
      setUpload(null);
      void load();
    }
  }

  async function onCancel() {
    if (!batch || !window.confirm(`Stop reviewing "${batch.name}"? Applications already reviewed keep their results.`)) {
      return;
    }
    setBatch(await cancelBatch(batch.id));
  }

  async function onRetry() {
    if (!batch) return;
    setBatch(await retryFailedBatchItems(batch.id));
  }

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-10">
      <Link href="/batches" className="text-sm text-gray-700 underline">
        ← All batches
      </Link>
      <h1 className="mt-2 text-2xl font-semibold text-gray-900">{batch.name}</h1>
      <p className="mt-1 text-gray-600">
        {batch.total} applications · started {new Date(batch.created_at).toLocaleString()} ·{" "}
        {BATCH_STATUS_LABELS[batch.status]}
      </p>

      <section className="mt-6 rounded-lg border border-gray-200 p-6">
        <ProgressBar value={finished} total={batch.total} />
        <p className="mt-3 text-lg text-gray-900">
          {batch.status === "done" && `All ${batch.total} applications reviewed.`}
          {batch.status === "cancelled" && `Cancelled after ${finished - counts.skipped} of ${batch.total}.`}
          {batch.status === "running" &&
            `${finished} of ${batch.total} reviewed${batch.eta_seconds ? ` · ${formatDuration(batch.eta_seconds)} left` : ""}. You can close this page and come back.`}
          {batch.status === "uploading" && `${finished} of ${batch.total} reviewed · waiting for photos.`}
        </p>
        {counts.decided > 0 && (
          <p className="text-sm text-gray-600">
            You&apos;ve made a decision on {counts.decided} of {batch.total}.
          </p>
        )}

        <div className="mt-4 flex flex-wrap gap-3">
          <a
            href={batchExportUrl(batch.id)}
            className="rounded-md border border-gray-400 px-4 py-2 text-base font-medium text-gray-900 hover:bg-gray-100"
          >
            Download results (CSV)
          </a>
          {counts.error > 0 && batch.status !== "cancelled" && (
            <button
              type="button"
              onClick={onRetry}
              className="rounded-md border border-gray-400 px-4 py-2 text-base font-medium text-gray-900 hover:bg-gray-100"
            >
              Try the {counts.error} unreadable one{counts.error === 1 ? "" : "s"} again
            </button>
          )}
          {(batch.status === "running" || batch.status === "uploading") && (
            <button
              type="button"
              onClick={onCancel}
              className="rounded-md border border-red-300 px-4 py-2 text-base font-medium text-red-800 hover:bg-red-50"
            >
              Cancel batch
            </button>
          )}
        </div>
      </section>

      {counts.awaiting_images > 0 && batch.status !== "cancelled" && (
        <section className="mt-6">
          {upload ? (
            <div className="rounded-lg border border-gray-200 p-6">
              <ProgressBar value={upload.done} total={upload.total} />
              <p className="mt-2 text-base text-gray-800">
                Uploading photos: {upload.done} of {upload.total}. Please keep this page open until it finishes.
              </p>
            </div>
          ) : (
            <DropZone
              onFiles={onRedrop}
              title={`${counts.awaiting_images} application${counts.awaiting_images === 1 ? " is" : "s are"} still waiting for photos`}
              hint="If the upload was interrupted, drop the same folder here to finish it. Photos already uploaded are skipped."
            />
          )}
        </section>
      )}
      {notice && <p className="mt-3 text-base text-gray-800">{notice}</p>}

      <section className="mt-8">
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Filter applications">
          {(["all", ...OUTCOME_ORDER] as const).map((key) => {
            const count = key === "all" ? batch.total : counted(key);
            if (key !== "all" && count === 0) return null;
            return (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={filter === key}
                onClick={() => setFilter(key)}
                className={`rounded-full border px-4 py-2 text-base font-medium ${
                  filter === key ? "border-gray-900 bg-gray-900 text-white" : "border-gray-300 bg-white text-gray-800 hover:bg-gray-100"
                }`}
              >
                {key === "all" ? "All" : OUTCOME_LABELS[key]} ({count})
              </button>
            );
          })}
        </div>

        <ul className="mt-4 divide-y divide-gray-200 rounded-lg border border-gray-200">
          {visible.map((item) => (
            <ItemRow
              key={item.id}
              item={item}
              onOpen={item.application_id && item.status === "reviewed" ? () => setOpenItemId(item.id) : null}
            />
          ))}
        </ul>
      </section>
    </main>
  );
}

function ItemRow({ item, onOpen }: { item: BatchItemOut; onOpen: (() => void) | null }) {
  const outcome = outcomeOf(item);
  const content = (
    <div className="flex items-center gap-4 p-3">
      <div className="h-16 w-12 flex-none overflow-hidden rounded border border-gray-200 bg-gray-50">
        {item.front_extraction_id && (
          // eslint-disable-next-line @next/next/no-img-element -- served by the backend, not a static asset
          <img src={labelImageUrl(item.front_extraction_id)} alt="" className="h-full w-full object-cover" loading="lazy" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-base font-medium text-gray-900">
          {item.brand_name ?? item.front_image_name}
        </div>
        <div className="truncate text-sm text-gray-600">
          Row {item.row_number}
          {item.reference ? ` · ${item.reference}` : ""}
          {outcomeDetail(item) ? ` · ${outcomeDetail(item)}` : ""}
        </div>
      </div>
      <div className="flex flex-none flex-col items-end gap-1">
        <span className={`rounded-full border px-3 py-1 text-sm font-medium whitespace-nowrap ${OUTCOME_STYLES[outcome]}`}>
          {OUTCOME_LABELS[outcome]}
        </span>
        {item.decision && (
          <span className="text-sm text-gray-700">✓ {DECISION_LABELS[item.decision.decision]}</span>
        )}
      </div>
    </div>
  );
  return (
    <li>
      {onOpen ? (
        <button type="button" onClick={onOpen} className="block w-full text-left hover:bg-gray-50">
          {content}
        </button>
      ) : (
        content
      )}
    </li>
  );
}

function ItemDetail({
  item,
  position,
  onBack,
  onPrevious,
  onNext,
}: {
  item: BatchItemOut;
  position: string;
  onBack: () => void;
  onPrevious: (() => void) | null;
  onNext: (() => void) | null;
}) {
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Keyed by item in the parent, so each item starts with fresh state.
  useEffect(() => {
    let current = true;
    getReview(item.application_id!)
      .then((r) => current && setResult(r))
      .catch((err) => current && setError(errorMessage(err)));
    return () => {
      current = false;
    };
  }, [item.application_id]);

  const navButton = "rounded-md border border-gray-400 px-4 py-2 text-base font-medium text-gray-900 hover:bg-gray-100 disabled:opacity-40";
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button type="button" onClick={onBack} className={navButton}>
          ← Back to the list
        </button>
        <span className="text-base text-gray-700">
          Application {position} · row {item.row_number}
          {item.reference ? ` · ${item.reference}` : ""}
        </span>
        <div className="flex gap-2">
          <button type="button" onClick={onPrevious ?? undefined} disabled={!onPrevious} className={navButton}>
            ← Previous
          </button>
          <button type="button" onClick={onNext ?? undefined} disabled={!onNext} className={navButton}>
            Next →
          </button>
        </div>
      </div>
      {error && <p className="mt-4 text-red-700">{error}</p>}
      {!result && !error && <p className="mt-6 text-gray-600">Loading…</p>}
      {result && (
        <ReviewResultView
          key={result.application.id}
          result={result}
          onNext={onNext ?? onBack}
          nextLabel={onNext ? "Next application →" : "Back to the list"}
          inBatch
        />
      )}
    </div>
  );
}
