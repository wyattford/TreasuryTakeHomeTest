"use client";

import { attachBatchImages, startExtraction } from "../api";
import type { BatchItemOut } from "../types";

// Rows uploading at once. Each row's images start being read as soon as
// they arrive, so there's no benefit to flooding the server faster than the
// model can keep up — this just keeps the network busy.
const UPLOAD_CONCURRENCY = 4;
// Matches the server's own normalization (MAX_IMAGE_EDGE_PX), so shrinking
// here loses nothing — and a 300-label batch of phone photos goes from
// gigabytes to tens of megabytes.
const MAX_EDGE_PX = 1024;

/** Every file in a drop, including inside dropped folders (recursively). */
export async function filesFromDrop(dataTransfer: DataTransfer): Promise<File[]> {
  const entries = [...dataTransfer.items]
    .map((item) => item.webkitGetAsEntry?.())
    .filter((entry): entry is FileSystemEntry => !!entry);
  if (!entries.length) return [...dataTransfer.files];
  const files: File[] = [];
  await Promise.all(entries.map((entry) => collect(entry, files)));
  return files;
}

async function collect(entry: FileSystemEntry, into: File[]): Promise<void> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) => (entry as FileSystemFileEntry).file(resolve, reject));
    if (!file.name.startsWith(".")) into.push(file); // skip .DS_Store and friends
    return;
  }
  if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    // readEntries returns results in chunks (~100); keep reading until empty.
    for (;;) {
      const chunk = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject));
      if (!chunk.length) break;
      await Promise.all(chunk.map((child) => collect(child, into)));
    }
  }
}

/** Upright, at most MAX_EDGE_PX on the long edge, JPEG. Falls back to the
 * original file if the browser can't decode it (the server will then
 * accept or reject it with a clear message). */
export async function shrinkForUpload(file: File): Promise<File> {
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, MAX_EDGE_PX / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.fillStyle = "#ffffff"; // flatten transparency onto white, like the server does
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
    return blob ? new File([blob], file.name.replace(/\.[^.]+$/, ".jpg"), { type: "image/jpeg" }) : file;
  } catch {
    return file;
  }
}

export interface UploadFailure {
  item: BatchItemOut;
  message: string;
}

/** Uploads the photos for every row still waiting for them, and attaches
 * them to their rows. Rows whose photos aren't among `files` (e.g. the
 * agent re-dropped only part of the folder) are left waiting. */
export async function uploadBatchImages(
  batchId: string,
  items: BatchItemOut[],
  files: File[],
  onProgress: (done: number, total: number) => void,
): Promise<{ uploaded: number; failures: UploadFailure[]; missing: BatchItemOut[] }> {
  const byName = new Map(files.map((f) => [f.name.toLowerCase(), f]));
  const find = (name: string | null) => (name ? byName.get(name.toLowerCase()) : undefined);

  const waiting = items.filter((i) => i.status === "awaiting_images");
  const ready = waiting.filter((i) => find(i.front_image_name) && (!i.back_image_name || find(i.back_image_name)));
  const missing = waiting.filter((i) => !ready.includes(i));
  const failures: UploadFailure[] = [];
  let done = 0;
  onProgress(done, ready.length);

  const queue = [...ready];
  async function worker() {
    for (let item = queue.shift(); item; item = queue.shift()) {
      try {
        const front = await startExtraction(await shrinkForUpload(find(item.front_image_name)!), "batch");
        const backFile = find(item.back_image_name);
        const back = backFile ? await startExtraction(await shrinkForUpload(backFile), "batch") : null;
        await attachBatchImages(batchId, item.id, front.id, back?.id ?? null);
      } catch (err) {
        failures.push({ item, message: err instanceof Error ? err.message : String(err) });
      }
      onProgress(++done, ready.length);
    }
  }
  await Promise.all(Array.from({ length: UPLOAD_CONCURRENCY }, worker));
  return { uploaded: ready.length - failures.length, failures, missing };
}
