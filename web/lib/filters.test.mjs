import { test } from "node:test";
import assert from "node:assert/strict";
import { activeCount, asState, parseFilters, parseLimit, toQuery } from "./filters.ts";

const parse = (q, tab = "best") => parseFilters(new URLSearchParams(q), tab);

test("round trip: a bookmarked URL gives the same filters back", () => {
  const q = "role=swe&role=backend&level=entry&level=ii&posted=3&minfit=60&unscored=hide&co=Stripe&xco=Amazon&loc=WA&remote=1" +
    "&sponsor=1&minfilings=100&maxyrs=2&cap=hide&clearance=hide&resume=ai&tier=1&tier=2&sort=posted&dir=asc";
  const f = parse(q);
  assert.equal(toQuery(f, "best"), q);
  assert.equal(activeCount(f), 15);
});

test("defaults leave the URL empty, and the tab's default sort isn't written", () => {
  assert.equal(toQuery(parse(""), "best"), "");               // Best bets is the default tab
  assert.equal(toQuery(parse("", "new"), "new"), "tab=new");
  assert.equal(parse("").sort, "fit");                       // Best bets/New/Backlog: best fit first
  assert.equal(parse("", "applied").sort, "found");
  assert.equal(toQuery(parse("sort=fit", "backlog"), "backlog"), "tab=backlog");
});

test("bad values fall back to defaults", () => {
  assert.deepEqual(parse("level=senior&level=entry").levels, ["entry"]);
  const f = parse("role=ceo&posted=2&minfit=500&tier=9&sort=salary&dir=up&maxyrs=10&resume=x");
  assert.deepEqual([f.roles, f.posted, f.minFit, f.tiers, f.sort, f.dir, f.maxYears, f.resume],
    [[], null, 0, [], "fit", "desc", null, null]);
});

test("state codes and names", () => {
  assert.deepEqual(asState("wa"), ["WA", "Washington"]);
  assert.deepEqual(asState("New York"), ["NY", "New York"]);
  assert.equal(asState("Boston"), null);
});

test("company sorts A→Z by default; other sorts high to low", () => {
  assert.equal(parse("sort=company").dir, "asc");
  assert.equal(toQuery(parse("sort=company"), "best"), "sort=company");            // default order not written
  assert.equal(toQuery(parse("sort=company&dir=desc"), "best"), "sort=company&dir=desc");
  assert.equal(parse("sort=posted").dir, "desc");
});

test("load more: limit grows in pages of 500, up to 5,000", () => {
  assert.deepEqual(["1000", "5000", null, "750", "5500", "-500", "500"].map(parseLimit),
    [1000, 5000, 500, 500, 500, 500, 500]);
});
