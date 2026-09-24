"use client";

import { useRef, useState } from "react";
import { filesFromDrop } from "./upload";

/** A large target for dropping a folder (or files), with plain buttons for
 * people who'd rather pick than drag. */
export function DropZone({
  onFiles,
  disabled,
  title,
  hint,
}: {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  title: string;
  hint: string;
}) {
  const [dragging, setDragging] = useState(false);
  const folderInput = useRef<HTMLInputElement>(null);
  const filesInput = useRef<HTMLInputElement>(null);

  function pick(list: FileList | null) {
    if (list?.length) onFiles([...list].filter((f) => !f.name.startsWith(".")));
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={async (e) => {
        e.preventDefault();
        setDragging(false);
        if (!disabled) onFiles(await filesFromDrop(e.dataTransfer));
      }}
      className={`rounded-lg border-2 border-dashed p-8 text-center ${
        dragging ? "border-gray-900 bg-gray-100" : "border-gray-400 bg-gray-50"
      } ${disabled ? "opacity-50" : ""}`}
    >
      <p className="text-lg font-medium text-gray-900">{title}</p>
      <p className="mt-1 text-sm text-gray-600">{hint}</p>
      <div className="mt-4 flex flex-wrap justify-center gap-3">
        <button
          type="button"
          disabled={disabled}
          onClick={() => folderInput.current?.click()}
          className="rounded-md bg-gray-900 px-4 py-3 text-base font-medium text-white hover:bg-gray-800 disabled:opacity-50"
        >
          Choose a folder
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={() => filesInput.current?.click()}
          className="rounded-md border border-gray-400 bg-white px-4 py-3 text-base font-medium text-gray-900 hover:bg-gray-100 disabled:opacity-50"
        >
          Choose files
        </button>
      </div>
      <input
        ref={folderInput}
        type="file"
        className="hidden"
        // Non-standard but supported by every current browser: pick a whole folder.
        {...{ webkitdirectory: "", directory: "" }}
        onChange={(e) => {
          pick(e.target.files);
          e.target.value = "";
        }}
      />
      <input
        ref={filesInput}
        type="file"
        multiple
        accept=".csv,image/png,image/jpeg,image/gif,image/webp"
        className="hidden"
        onChange={(e) => {
          pick(e.target.files);
          e.target.value = "";
        }}
      />
    </div>
  );
}
