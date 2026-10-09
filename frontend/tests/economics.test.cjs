const { test } = require("node:test");
const assert = require("node:assert/strict");
const e = require("../.test-build/lib/economics.js");
const c = require("../.test-build/lib/column-model.js");
const r = require("../.test-build/lib/metric-registry.js");
test("decimal percentage input preserves precision and boundaries", () => {
  for (const [percent, rate] of [
    ["30", "0.3"],
    ["0", "0"],
    ["100", "1"],
    ["0.000001", "0.00000001"],
    ["99.123456", "0.99123456"],
  ]) {
    assert.equal(e.percentToRate(percent), rate);
    assert.equal(e.rateToPercent(rate), percent);
  }
  for (const bad of ["101", "-1", "30,5", "Infinity", "0.0000001"])
    assert.throws(() => e.percentToRate(bad));
});
test("economic default excludes current Moscow day across timezone boundary", () => {
  assert.deepEqual(
    e.economicRange("closed7", new Date("2026-10-08T21:00:00Z")),
    ["2026-10-02", "2026-10-08"],
  );
  assert.deepEqual(e.economicRange("1", new Date("2026-10-08T21:00:00Z")), [
    "2026-10-09",
    "2026-10-09",
  ]);
});
test("economics scopes are independent and existing saved selections survive", () => {
  const old = {
    version: 1,
    columns: [
      { key: "name", width: 400 },
      { key: "roi", width: 200 },
    ],
    widths: { roi: 200 },
    sorting: { key: "roi", direction: "asc" },
  };
  assert.deepEqual(c.normalizeColumns(old, "ad"), old);
  for (const scope of ["eco_account", "eco_campaign", "eco_adset", "eco_ad"]) {
    const keys = c.systemPresets(scope)[0].config.columns.map((x) => x.key);
    assert.ok(keys.includes("actual_roi"));
    assert.ok(keys.includes("estimated_roi"));
    assert.ok(!keys.includes("roi"));
    for (const key of [
      "tracker_sales",
      "meta_leads",
      "meta_purchases",
      "meta_conversions",
    ])
      assert.ok(r.scopeMetrics(scope).some((m) => m.key === key));
  }
  assert.ok(!r.scopeMetrics("ad").some((m) => m.key === "actual_roi"));
});
test("unknown actual values remain null and source quality is localized", () => {
  const row = e.economicRow({
    actual_roi: null,
    economics_data_quality: "ESTIMATED",
    reason_codes: ["ACTUAL_REVENUE_UNCONFIRMED"],
    metric_provenance: {},
  });
  assert.equal(row.actual_roi, null);
  assert.equal(row.economics_data_quality, "Прогноз");
  assert.equal(row.economics_reasons, "Выручка не подтверждена");
  assert.ok(!("metric_provenance" in row));
});
test("profile commands never trust server metadata or actor fields", () => {
  const payload = e.profileCommand({
    ...e.emptyProfile,
    id: "id",
    version: 5,
    workspace_id: "foreign",
    created_by: "admin",
  });
  assert.ok(!("workspace_id" in payload));
  assert.ok(!("id" in payload));
  assert.equal(payload.payout, "30");
});
