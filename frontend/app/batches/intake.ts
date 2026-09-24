// Turns what an agent dropped (a folder of label photos, usually with a CSV
// manifest) into batch rows, and finds every problem *before* anything is
// uploaded — discovering a misspelled filename at row 173, forty minutes into
// a batch, is the failure this exists to prevent.
//
// Pure functions, no browser or React APIs, so it's unit-tested directly
// (intake.test.ts, run with `npm test`).

export type BeverageClass = "distilled_spirits" | "wine" | "malt_beverage";

export interface DroppedFile {
  name: string; // base filename, no folder
  size: number;
}

export interface PlannedRow {
  line: number; // CSV line number (1 = header), or 0 when there's no CSV
  reference: string | null;
  front_image: string;
  back_image: string | null;
  beverage_class: BeverageClass;
  imported: boolean;
  brand_name: string | null;
  fanciful_name: string | null;
  class_type: string | null;
  abv: number | null;
  net_contents: string | null;
  name_address: string | null;
  country_of_origin: string | null;
  appellation: string | null;
  sulfite_declaration: string | null;
}

export interface Problem {
  line: number | null; // null for problems that aren't about one row
  message: string;
}

export interface BatchPlan {
  rows: PlannedRow[]; // only the rows with no problems
  problems: Problem[]; // rows listed here are left out of `rows`
  warnings: string[]; // worth knowing, but nothing is left out
}

export interface Defaults {
  beverageClass: BeverageClass;
  imported: boolean;
}

export const IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".gif", ".webp"];
export const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
export const MAX_ROWS = 1000;

const BEVERAGE_CLASSES: Record<string, BeverageClass> = {
  distilled_spirits: "distilled_spirits",
  "distilled spirits": "distilled_spirits",
  spirits: "distilled_spirits",
  wine: "wine",
  malt_beverage: "malt_beverage",
  "malt beverage": "malt_beverage",
  beer: "malt_beverage",
};

const TEXT_COLUMNS = [
  "brand_name",
  "fanciful_name",
  "class_type",
  "net_contents",
  "name_address",
  "country_of_origin",
  "appellation",
  "sulfite_declaration",
] as const;

export const TEMPLATE_COLUMNS = [
  "reference",
  "front_image",
  "back_image",
  "beverage_class",
  "imported",
  "brand_name",
  "fanciful_name",
  "class_type",
  "abv",
  "net_contents",
  "name_address",
  "country_of_origin",
  "appellation",
  "sulfite_declaration",
];

export function templateCsv(): string {
  const example = [
    "HI-001",
    "HI-001_front.jpg",
    "HI-001_back.jpg",
    "distilled_spirits",
    "no",
    "Old Tom Distillery",
    "",
    "Kentucky Straight Bourbon Whiskey",
    "45",
    "750 mL",
    '"Old Tom Distillery, Louisville, KY"',
    "",
    "",
    "",
  ];
  return `${TEMPLATE_COLUMNS.join(",")}\n${example.join(",")}\n`;
}

export function isImageName(name: string): boolean {
  const lower = name.toLowerCase();
  return IMAGE_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

/** RFC 4180 CSV: quoted fields may contain commas, quotes ("") and newlines. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;
  const input = text.replace(/^\uFEFF/, ""); // Excel's byte-order mark

  for (let i = 0; i < input.length; i++) {
    const ch = input[i];
    if (inQuotes) {
      if (ch === '"' && input[i + 1] === '"') {
        field += '"';
        i++;
      } else if (ch === '"') {
        inQuotes = false;
      } else {
        field += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      row.push(field);
      field = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && input[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += ch;
    }
  }
  if (field !== "" || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  // Drop fully blank lines (trailing newlines, spacer rows).
  return rows.filter((r) => r.some((cell) => cell.trim() !== ""));
}

function normalizeHeader(header: string): string {
  return header.trim().toLowerCase().replace(/[\s/-]+/g, "_");
}

function parseYesNo(value: string): boolean | null {
  const v = value.trim().toLowerCase();
  if (["", "no", "n", "false", "0", "domestic"].includes(v)) return false;
  if (["yes", "y", "true", "1", "imported", "import"].includes(v)) return true;
  return null;
}

// Levenshtein distance, for "did you mean" suggestions on filenames.
function editDistance(a: string, b: string): number {
  const prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    let diagonal = prev[0];
    prev[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const above = prev[j];
      prev[j] = Math.min(prev[j] + 1, prev[j - 1] + 1, diagonal + (a[i - 1] === b[j - 1] ? 0 : 1));
      diagonal = above;
    }
  }
  return prev[b.length];
}

function closestName(name: string, candidates: string[]): string | null {
  let best: string | null = null;
  let bestDistance = Math.max(3, Math.floor(name.length / 4));
  for (const candidate of candidates) {
    const d = editDistance(name.toLowerCase(), candidate.toLowerCase());
    if (d <= bestDistance) {
      best = candidate;
      bestDistance = d;
    }
  }
  return best;
}

interface FileIndex {
  byLowerName: Map<string, DroppedFile>;
  imageNames: string[];
}

function indexFiles(files: DroppedFile[]): FileIndex {
  const byLowerName = new Map<string, DroppedFile>();
  for (const f of files) byLowerName.set(f.name.toLowerCase(), f);
  return { byLowerName, imageNames: files.filter((f) => isImageName(f.name)).map((f) => f.name) };
}

function checkImage(index: FileIndex, name: string, column: string): string | null {
  const file = index.byLowerName.get(name.toLowerCase());
  if (!file) {
    const suggestion = closestName(name, index.imageNames);
    return `${column} "${name}" isn't in the folder${suggestion ? ` — did you mean "${suggestion}"?` : "."}`;
  }
  if (!isImageName(file.name)) return `${column} "${name}" isn't a JPEG, PNG, GIF, or WebP image.`;
  if (file.size > MAX_IMAGE_BYTES) return `${column} "${name}" is larger than 20 MB.`;
  return null;
}

function emptyDeclared(): Omit<PlannedRow, "line" | "reference" | "front_image" | "back_image" | "beverage_class" | "imported"> {
  return {
    brand_name: null,
    fanciful_name: null,
    class_type: null,
    abv: null,
    net_contents: null,
    name_address: null,
    country_of_origin: null,
    appellation: null,
    sulfite_declaration: null,
  };
}

/** Plan a batch from a CSV manifest plus the dropped files. */
export function planFromCsv(csvText: string, files: DroppedFile[], defaults: Defaults): BatchPlan {
  const table = parseCsv(csvText);
  const problems: Problem[] = [];
  const warnings: string[] = [];
  if (table.length < 2) {
    return { rows: [], problems: [{ line: null, message: "The spreadsheet has no rows under its header." }], warnings };
  }

  const headers = table[0].map(normalizeHeader);
  const col = (name: string) => headers.indexOf(name);
  if (col("front_image") === -1) {
    return {
      rows: [],
      problems: [{ line: null, message: 'The spreadsheet needs a "front_image" column naming each front label photo.' }],
      warnings,
    };
  }
  const known = new Set([...TEMPLATE_COLUMNS]);
  const unknown = headers.filter((h) => h && !known.has(h));
  if (unknown.length) warnings.push(`Ignoring unrecognized column(s): ${unknown.join(", ")}.`);

  const index = indexFiles(files);
  const rows: PlannedRow[] = [];
  const usedImages = new Set<string>();
  const frontSeenOn = new Map<string, number>();

  table.slice(1).forEach((cells, i) => {
    const line = i + 2;
    const get = (name: string) => (col(name) === -1 ? "" : (cells[col(name)] ?? "").trim());
    const rowProblems: string[] = [];

    const front = get("front_image");
    const back = get("back_image") || null;
    if (!front) {
      rowProblems.push("front_image is blank.");
    } else {
      const problem = checkImage(index, front, "front_image");
      if (problem) rowProblems.push(problem);
      const earlier = frontSeenOn.get(front.toLowerCase());
      if (earlier) rowProblems.push(`front_image "${front}" is also used on line ${earlier}.`);
      frontSeenOn.set(front.toLowerCase(), line);
    }
    if (back) {
      const problem = checkImage(index, back, "back_image");
      if (problem) rowProblems.push(problem);
    }

    let beverageClass = defaults.beverageClass;
    const rawClass = get("beverage_class");
    if (rawClass) {
      const parsed = BEVERAGE_CLASSES[rawClass.toLowerCase().replace(/_/g, " ")] ?? BEVERAGE_CLASSES[rawClass.toLowerCase()];
      if (parsed) beverageClass = parsed;
      else rowProblems.push(`beverage_class "${rawClass}" should be distilled_spirits, wine, or malt_beverage.`);
    }

    let imported = defaults.imported;
    if (col("imported") !== -1 && get("imported") !== "") {
      const parsed = parseYesNo(get("imported"));
      if (parsed === null) rowProblems.push(`imported "${get("imported")}" should be yes or no.`);
      else imported = parsed;
    }

    let abv: number | null = null;
    const rawAbv = get("abv").replace(/%.*$/, "").trim();
    if (rawAbv) {
      const parsed = Number(rawAbv);
      if (Number.isFinite(parsed) && parsed >= 0 && parsed <= 100) abv = parsed;
      else rowProblems.push(`abv "${get("abv")}" isn't a percentage.`);
    }

    if (rowProblems.length) {
      for (const message of rowProblems) problems.push({ line, message });
      return;
    }

    const declared = emptyDeclared();
    for (const name of TEXT_COLUMNS) declared[name] = get(name) || null;
    usedImages.add(front.toLowerCase());
    if (back) usedImages.add(back.toLowerCase());
    rows.push({
      line,
      reference: get("reference") || null,
      front_image: index.byLowerName.get(front.toLowerCase())!.name,
      back_image: back ? index.byLowerName.get(back.toLowerCase())!.name : null,
      beverage_class: beverageClass,
      imported,
      ...declared,
      abv,
    });
  });

  const unused = index.imageNames.filter((name) => !usedImages.has(name.toLowerCase()));
  // Only worth mentioning when everything else lined up; with row problems
  // the unused images are usually just the misspelled ones already reported.
  if (unused.length && !problems.length) {
    const shown = unused.slice(0, 5).join(", ");
    warnings.push(`${unused.length} photo(s) aren't used by any row: ${shown}${unused.length > 5 ? ", …" : ""}.`);
  }
  if (rows.length > MAX_ROWS) {
    problems.push({ line: null, message: `A batch can have at most ${MAX_ROWS} applications; this one has ${rows.length}.` });
  }
  return { rows, problems, warnings };
}

const SIDE_SUFFIX = /^(.*?)[\s_-]+(front|back)$/i;

/** Plan a batch from photos alone, with no spreadsheet: every application is
 * checked on the label alone. `NAME_front.jpg` / `NAME_back.jpg` are paired
 * into one application; any other photo is an application on its own. */
export function planFromImages(files: DroppedFile[], defaults: Defaults): BatchPlan {
  const images = files.filter((f) => isImageName(f.name)).sort((a, b) => a.name.localeCompare(b.name));
  const problems: Problem[] = [];
  const warnings: string[] = [];
  const skipped = files.filter((f) => !isImageName(f.name));
  if (skipped.length) warnings.push(`Ignoring ${skipped.length} file(s) that aren't photos.`);

  // Keyed case-insensitively; `label` keeps the name as the agent wrote it.
  const groups = new Map<string, { label: string; front?: DroppedFile; back?: DroppedFile; single?: DroppedFile }>();
  for (const image of images) {
    const stem = image.name.replace(/\.[^.]+$/, "");
    const match = stem.match(SIDE_SUFFIX);
    const label = match ? match[1] : stem;
    const group = groups.get(label.toLowerCase()) ?? { label };
    if (!match) group.single = image;
    else if (match[2].toLowerCase() === "front") group.front = image;
    else group.back = image;
    groups.set(label.toLowerCase(), group);
  }

  const rows: PlannedRow[] = [];
  for (const group of groups.values()) {
    const front = group.front ?? group.single;
    if (!front) {
      problems.push({ line: null, message: `"${group.back!.name}" is a back label with no matching front label photo.` });
      continue;
    }
    if (group.single && group.front) {
      warnings.push(`"${group.single.name}" and "${group.front.name}" look like the same application; using "${group.front.name}".`);
    }
    const tooLarge = [front, group.back].filter((f): f is DroppedFile => !!f && f.size > MAX_IMAGE_BYTES);
    if (tooLarge.length) {
      for (const f of tooLarge) problems.push({ line: null, message: `"${f.name}" is larger than 20 MB.` });
      continue;
    }
    rows.push({
      line: 0,
      reference: group.label,
      front_image: front.name,
      back_image: group.back?.name ?? null,
      beverage_class: defaults.beverageClass,
      imported: defaults.imported,
      ...emptyDeclared(),
    });
  }
  if (!images.length) problems.push({ line: null, message: "No label photos found (JPEG, PNG, GIF, or WebP)." });
  if (rows.length > MAX_ROWS) {
    problems.push({ line: null, message: `A batch can have at most ${MAX_ROWS} applications; this one has ${rows.length}.` });
  }
  return { rows, problems, warnings };
}

/** Picks the manifest out of the dropped files (the one .csv), then plans. */
export function planBatch(
  files: DroppedFile[],
  csv: { name: string; text: string } | null,
  defaults: Defaults,
): BatchPlan {
  if (!csv) return planFromImages(files, defaults);
  const images = files.filter((f) => f.name !== csv.name);
  return planFromCsv(csv.text, images, defaults);
}
