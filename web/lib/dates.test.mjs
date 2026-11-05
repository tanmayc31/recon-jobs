// Run with: npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { posted, updated } from "./dates.ts";

const NOW = Date.parse("2026-11-05T18:00:00Z");

test("shows updated when edited more than 2 days after posting", () => {
  // Real Robinhood "Software Engineer, AI Security" (Greenhouse 8220757)
  assert.equal(updated("2026-10-09T17:58:39-04:00", "2026-11-05T11:50:21-05:00", NOW), "updated 1 h ago");
});

test("hides updated within 2 days of posting, or without real dates", () => {
  assert.equal(updated("2026-11-04T10:00:00Z", "2026-11-05T10:00:00Z", NOW), null);
  assert.equal(updated("2026-11-03T10:00:00Z", "2026-11-05T10:00:00Z", NOW), null); // exactly 2 days
  assert.equal(updated("Posted 30+ Days Ago", "2026-11-05T10:00:00Z", NOW), null);   // Workday text
  assert.equal(updated("2026-10-09T17:58:39-04:00", null, NOW), null);
});

test("posted label", () => {
  assert.equal(posted("Posted 30+ Days Ago", NOW), "posted 30+ days ago");
  assert.equal(posted("2026-10-09T17:58:39-04:00", NOW), "posted 27 days ago");
});
