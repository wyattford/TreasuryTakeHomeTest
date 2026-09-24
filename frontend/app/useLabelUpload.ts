"use client";

import { useRef, useState } from "react";
import { cancelExtraction, startExtraction, waitForExtraction } from "./api";

// One label image and how far along the backend is with reading it. The
// image is uploaded — and the model starts reading it — as soon as it's
// picked, so it's usually finished before the user has typed in the
// application fields.
export interface LabelUpload {
  file: File;
  extractionId: string | null;
  status: "uploading" | "reading" | "done" | "error";
  latencyMs: number | null;
  error: string | null;
  // True when the upload itself was refused (not an image, too large) —
  // there's nothing for the review to retry, so it can't be submitted.
  rejected: boolean;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function useLabelUpload() {
  const [upload, setUpload] = useState<LabelUpload | null>(null);
  // Refs, not state: async callbacks from an earlier pick need to see the
  // *current* pick to know they're stale.
  const currentFile = useRef<File | null>(null);
  const inFlightId = useRef<string | null>(null);

  function abandonInFlight() {
    if (inFlightId.current) cancelExtraction(inFlightId.current);
    inFlightId.current = null;
  }

  async function choose(file: File | null) {
    abandonInFlight();
    currentFile.current = file;
    if (!file) {
      setUpload(null);
      return;
    }

    const isStale = () => currentFile.current !== file;
    const update = (patch: Partial<LabelUpload>) => {
      if (!isStale()) setUpload((prev) => (prev ? { ...prev, ...patch } : prev));
    };

    setUpload({ file, extractionId: null, status: "uploading", latencyMs: null, error: null, rejected: false });
    let extractionId: string | null = null;
    try {
      const started = await startExtraction(file);
      extractionId = started.id;
      if (isStale()) {
        if (started.status === "pending") cancelExtraction(started.id);
        return;
      }
      if (started.status === "pending") inFlightId.current = started.id;
      update({ extractionId: started.id, status: "reading" });

      const finished = started.status === "pending" ? await waitForExtraction(started.id, isStale) : started;
      if (!finished || isStale()) return;
      inFlightId.current = null;
      if (finished.status === "done") {
        update({ status: "done", latencyMs: finished.latency_ms });
      } else {
        update({ status: "error", error: finished.error_message ?? "The label couldn't be read." });
      }
    } catch (err) {
      update({ status: "error", error: errorMessage(err), rejected: extractionId === null });
    }
  }

  function reset() {
    abandonInFlight();
    currentFile.current = null;
    setUpload(null);
  }

  return { upload, choose, reset };
}
