// Run with `npm test` (Node's built-in test runner; Node strips the types).
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseCsv, planBatch, planFromCsv, planFromImages } from "./intake.ts";

const defaults = { beverageClass: "distilled_spirits" as const, imported: false };
const files = (...names: string[]) => names.map((name) => ({ name, size: 1000 }));

test("parseCsv handles quotes, embedded commas and newlines, CRLF, and a BOM", () => {
  const csv = '﻿a,b,c\r\n1,"x, y","say ""hi"""\r\n2,"two\nlines",\r\n\r\n';
  assert.deepEqual(parseCsv(csv), [
    ["a", "b", "c"],
    ["1", "x, y", 'say "hi"'],
    ["2", "two\nlines", ""],
  ]);
});

test("a clean spreadsheet plans one row per line with declared values", () => {
  const csv = [
    "Reference,Front Image,back_image,beverage_class,imported,brand_name,abv,net_contents",
    "HI-1,hi-1_FRONT.jpg,hi-1_back.jpg,wine,yes,Casa Fiorentina,13.5%,750 mL",
  ].join("\n");
  const plan = planFromCsv(csv, files("HI-1_front.jpg", "HI-1_back.jpg"), defaults);
  assert.deepEqual(plan.problems, []);
  assert.equal(plan.rows.length, 1);
  const row = plan.rows[0];
  assert.equal(row.front_image, "HI-1_front.jpg"); // matched case-insensitively, real name kept
  assert.equal(row.beverage_class, "wine");
  assert.equal(row.imported, true);
  assert.equal(row.abv, 13.5);
  assert.equal(row.brand_name, "Casa Fiorentina");
  assert.equal(row.class_type, null);
});

test("every problem is reported up front, with the line and a suggestion", () => {
  const csv = [
    "front_image,back_image,beverage_class,abv,imported",
    "NW-114_front.jpg,NW-114_bak.jpg,distilled_spirits,40,no",
    "NW-115_front.jpg,,cider,,no",
    "NW-116_front.jpg,,wine,forty,maybe",
    "NW-114_front.jpg,,wine,,",
  ].join("\n");
  const plan = planFromCsv(csv, files("NW-114_front.jpg", "NW-114_back.jpg", "NW-115_front.jpg", "NW-116_front.jpg"), defaults);
  assert.equal(plan.rows.length, 0); // every line has something wrong
  const messages = plan.problems.map((p) => `${p.line}: ${p.message}`);
  assert.ok(messages.some((m) => m.startsWith("2:") && m.includes('did you mean "NW-114_back.jpg"')), messages.join("\n"));
  assert.ok(messages.some((m) => m.startsWith("3:") && m.includes("cider")));
  assert.ok(messages.some((m) => m.startsWith("4:") && m.includes("forty")));
  assert.ok(messages.some((m) => m.startsWith("4:") && m.includes("maybe")));
  assert.ok(messages.some((m) => m.startsWith("5:") && m.includes("also used on line 2")));
});

test("rows without a beverage_class use the chosen default", () => {
  const plan = planFromCsv("front_image\na.jpg", files("a.jpg"), { beverageClass: "malt_beverage", imported: true });
  assert.equal(plan.rows[0].beverage_class, "malt_beverage");
  assert.equal(plan.rows[0].imported, true);
});

test("a spreadsheet without a front_image column is rejected", () => {
  const plan = planFromCsv("brand_name\nFoo", files("a.jpg"), defaults);
  assert.equal(plan.rows.length, 0);
  assert.match(plan.problems[0].message, /front_image/);
});

test("photos with no spreadsheet pair NAME_front / NAME_back, others stand alone", () => {
  const plan = planFromImages(files("HI-2_back.png", "HI-2_front.png", "lonely.jpg", "notes.txt", "HI-3-back.jpg"), defaults);
  assert.deepEqual(
    plan.rows.map((r) => [r.reference, r.front_image, r.back_image]),
    [
      ["HI-2", "HI-2_front.png", "HI-2_back.png"],
      ["lonely", "lonely.jpg", null],
    ],
  );
  assert.match(plan.problems[0].message, /HI-3-back\.jpg.*no matching front/);
  assert.match(plan.warnings[0], /1 file\(s\) that aren't photos/);
});

test("planBatch uses the dropped CSV as the manifest", () => {
  const plan = planBatch(files("a.jpg", "list.csv"), { name: "list.csv", text: "front_image\na.jpg" }, defaults);
  assert.equal(plan.rows.length, 1);
  assert.deepEqual(plan.warnings, []);
});
