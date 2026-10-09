const { test } = require("node:test");
const assert = require("node:assert/strict");
const r = require("../.test-build/lib/smart-rules.js");
const c = require("../.test-build/lib/column-model.js");
test("rule defaults are AD-only dry run with completed seven days", () => {
  const d = r.newRule();
  assert.equal(d.level, "ad");
  assert.equal(d.mode, "DRY_RUN");
  assert.equal(d.period, "last_7");
  assert.equal(d.estimated_policy, "review");
  assert.equal(d.profile_id, null);
  assert.deepEqual(d.selection.account_ids, []);
  assert.equal(d.thresholds.minimum_leads, null);
});
test("unknown facts and approval labels survive flattening", () => {
  const row = r.ruleRow({
    approved_sales: null,
    actual_roi: null,
    status: "REVIEW",
    reason_codes: ["UNKNOWN_APPROVED_SALES", "ESTIMATED_MODEL"],
    economics_data_quality: "ESTIMATED",
  });
  assert.equal(row.approved_sales, null);
  assert.equal(row.actual_roi, null);
  assert.match(row.rule_reason, /неизвестно/);
  assert.equal(row.rule_status, "Требует проверки");
});
test("zero-event conditions have dedicated spend threshold", () => {
  for (const key of ["NO_LEADS_SPEND", "NO_APPROVED_SALES_SPEND"]) {
    const d = r.newCondition(key);
    assert.equal(d.limit, "custom");
    assert.equal(d.value, "20");
  }
  assert.equal(r.newCondition("CPS_ABOVE_LIMIT").source, "approved");
  assert.equal(r.newCondition("ROI_BELOW_MINIMUM").source, "estimated");
});
test("rule column scope does not replace saved economics or statistics presets", () => {
  const existing = {
    version: 1,
    columns: [
      { key: "name", width: 400 },
      { key: "roi", width: 200 },
    ],
    widths: { roi: 200 },
    sorting: { key: "roi", direction: "asc" },
  };
  assert.deepEqual(c.normalizeColumns(existing, "ad"), existing);
  const keys = c.systemPresets("rule_ad")[0].config.columns.map((x) => x.key);
  assert.ok(
    keys.includes("rule_status") &&
      keys.includes("actual_roi") &&
      keys.includes("estimated_roi"),
  );
  assert.ok(!keys.includes("roi"));
  assert.equal(keys[0], "name");
});
