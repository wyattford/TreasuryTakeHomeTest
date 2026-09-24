"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { createBatch, listBatches } from "../api";
import type { BatchSummaryOut } from "../types";
import { DropZone } from "./DropZone";
import { type BatchPlan, type BeverageClass, planBatch, templateCsv } from "./intake";
import { uploadBatchImages } from "./upload";
import { BATCH_STATUS_LABELS, ProgressBar } from "./shared";

interface Dropped {
  files: File[];
  csv: { name: string; text: string } | null;
  folderName: string | null;
  error: string | null;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

async function readDrop(files: File[]): Promise<Dropped> {
  const csvFiles = files.filter((f) => f.name.toLowerCase().endsWith(".csv"));
  // webkitRelativePath is "folder/sub/file.jpg" when a folder was picked.
  const folderName = files.find((f) => f.webkitRelativePath)?.webkitRelativePath.split("/")[0] ?? null;
  if (csvFiles.length > 1) {
    return {
      files,
      csv: null,
      folderName,
      error: `Found ${csvFiles.length} spreadsheets (${csvFiles.map((f) => f.name).join(", ")}). Keep just one in the folder.`,
    };
  }
  const csv = csvFiles[0] ? { name: csvFiles[0].name, text: await csvFiles[0].text() } : null;
  return { files, csv, folderName, error: null };
}

export default function StartBatchPage() {
  const router = useRouter();
  const [dropped, setDropped] = useState<Dropped | null>(null);
  const [name, setName] = useState("");
  const [beverageClass, setBeverageClass] = useState<BeverageClass>("distilled_spirits");
  const [imported, setImported] = useState(false);
  const [upload, setUpload] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<BatchSummaryOut[] | null>(null);

  useEffect(() => {
    listBatches()
      .then(setRecent)
      .catch(() => setRecent([]));
  }, []);

  // Leaving mid-upload would strand the rest of the photos (they can be
  // re-dropped on the batch page, but better not to need to).
  useEffect(() => {
    if (!upload) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [upload]);

  const plan: BatchPlan | null = useMemo(() => {
    if (!dropped || dropped.error) return null;
    return planBatch(
      dropped.files.map((f) => ({ name: f.name, size: f.size })),
      dropped.csv,
      { beverageClass, imported },
    );
  }, [dropped, beverageClass, imported]);

  async function onFiles(files: File[]) {
    setError(null);
    const read = await readDrop(files);
    setDropped(read);
    setName((current) => current || read.folderName || `Batch ${new Date().toLocaleDateString()}`);
  }

  async function start() {
    if (!dropped || !plan?.rows.length) return;
    setError(null);
    setUpload({ done: 0, total: plan.rows.length });
    try {
      const batch = await createBatch(name.trim() || "Untitled batch", plan.rows);
      // Any row whose upload failed stays "waiting for photos"; the batch
      // page lists those and takes a re-drop of the same folder.
      await uploadBatchImages(batch.id, batch.items, dropped.files, (done, total) => setUpload({ done, total }));
      router.push(`/batches/${batch.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setUpload(null);
    }
  }

  const problemCount = plan?.problems.length ?? 0;

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-10">
      <h1 className="text-2xl font-semibold text-gray-900">Review a batch</h1>
      <p className="mt-1 max-w-3xl text-gray-700">
        For a large set of applications at once. Put the label photos in one folder, with a spreadsheet (CSV)
        listing each application — or just the photos, to check the labels on their own. The review runs on the
        server: once the photos are uploaded, you can close the page and come back.
      </p>
      <p className="mt-2 text-sm">
        <a
          href={`data:text/csv;charset=utf-8,${encodeURIComponent(templateCsv())}`}
          download="batch-template.csv"
          className="font-medium text-gray-900 underline"
        >
          Download the spreadsheet template
        </a>
        <span className="text-gray-600">
          {" "}
          — one row per application; only <code>front_image</code> is required. Without a spreadsheet, photos named{" "}
          <code>NAME_front.jpg</code> and <code>NAME_back.jpg</code> are paired automatically.
        </span>
      </p>

      <div className="mt-6">
        <DropZone
          onFiles={onFiles}
          disabled={!!upload}
          title="Drop a folder of label photos here"
          hint="Include the spreadsheet in the same folder, if you have one."
        />
      </div>

      {dropped && (
        <section className="mt-6 space-y-4 rounded-lg border border-gray-200 p-6">
          <p className="text-sm text-gray-600">
            {dropped.files.length} file(s){dropped.csv ? `, using spreadsheet "${dropped.csv.name}"` : ", no spreadsheet"}
          </p>
          {dropped.error && <p className="text-base text-red-700">{dropped.error}</p>}

          {plan && (
            <>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <label className="block text-sm sm:col-span-1">
                  <span className="mb-1 block font-medium text-gray-800">Batch name</span>
                  <input value={name} onChange={(e) => setName(e.target.value)} className="input" />
                </label>
                <label className="block text-sm">
                  <span className="mb-1 block font-medium text-gray-800">
                    Beverage class{dropped.csv ? " (for rows that don't say)" : ""}
                  </span>
                  <select
                    value={beverageClass}
                    onChange={(e) => setBeverageClass(e.target.value as BeverageClass)}
                    className="input"
                  >
                    <option value="distilled_spirits">Distilled spirits</option>
                    <option value="wine">Wine</option>
                    <option value="malt_beverage">Malt beverage</option>
                  </select>
                </label>
                <label className="flex items-end gap-2 pb-2 text-base text-gray-800">
                  <input
                    type="checkbox"
                    checked={imported}
                    onChange={(e) => setImported(e.target.checked)}
                    className="h-5 w-5"
                  />
                  Imported{dropped.csv ? " (for rows that don't say)" : ""}
                </label>
              </div>

              <div className={`rounded-md p-4 ${problemCount ? "bg-amber-50" : "bg-green-50"}`}>
                <p className="text-lg font-semibold text-gray-900">
                  {plan.rows.length} application{plan.rows.length === 1 ? "" : "s"} ready to review
                  {problemCount ? ` · ${problemCount} problem${problemCount === 1 ? "" : "s"} to look at` : ""}
                </p>
                {!dropped.csv && plan.rows.length > 0 && (
                  <p className="mt-1 text-sm text-gray-700">
                    No spreadsheet, so each label is checked on its own: required information present, Government
                    Warning exact, standard container size.
                  </p>
                )}
                {problemCount > 0 && (
                  <ul className="mt-3 max-h-64 list-disc space-y-1 overflow-y-auto pl-5 text-sm text-gray-800">
                    {plan.problems.map((p, i) => (
                      <li key={i}>
                        {p.line ? <strong>Line {p.line}: </strong> : null}
                        {p.message}
                      </li>
                    ))}
                  </ul>
                )}
                {plan.warnings.map((w) => (
                  <p key={w} className="mt-2 text-sm text-gray-700">
                    Note: {w}
                  </p>
                ))}
              </div>

              {upload ? (
                <div>
                  <ProgressBar value={upload.done} total={upload.total} />
                  <p className="mt-2 text-base text-gray-800">
                    Uploading photos: {upload.done} of {upload.total} applications. Please keep this page open until
                    the upload finishes — reviewing has already started.
                  </p>
                </div>
              ) : (
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={start}
                    disabled={!plan.rows.length}
                    className="rounded-md bg-gray-900 px-6 py-3 text-base font-medium text-white hover:bg-gray-800 disabled:opacity-50"
                  >
                    {problemCount && plan.rows.length
                      ? `Start review anyway (skip the rows with problems)`
                      : `Start review of ${plan.rows.length} application${plan.rows.length === 1 ? "" : "s"}`}
                  </button>
                  {problemCount > 0 && (
                    <span className="text-sm text-gray-600">Or fix the spreadsheet or folder and drop it again.</span>
                  )}
                </div>
              )}
            </>
          )}
        </section>
      )}

      {error && <div className="mt-6 rounded-md border border-red-300 bg-red-50 p-4 text-red-800">{error}</div>}

      <section className="mt-10">
        <h2 className="text-lg font-semibold text-gray-900">Recent batches</h2>
        {recent === null ? (
          <p className="mt-2 text-sm text-gray-600">Loading…</p>
        ) : recent.length === 0 ? (
          <p className="mt-2 text-sm text-gray-600">None yet.</p>
        ) : (
          <ul className="mt-2 divide-y divide-gray-200 rounded-lg border border-gray-200">
            {recent.map((b) => (
              <li key={b.id}>
                <Link href={`/batches/${b.id}`} className="flex flex-wrap items-center justify-between gap-2 p-4 hover:bg-gray-50">
                  <span className="text-base font-medium text-gray-900">{b.name}</span>
                  <span className="text-sm text-gray-600">
                    {b.total} applications · {BATCH_STATUS_LABELS[b.status]} · {b.counts.flagged} need review ·{" "}
                    {new Date(b.created_at).toLocaleString()}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
