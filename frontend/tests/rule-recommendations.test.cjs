const { test } = require("node:test");
const assert = require("node:assert/strict");
const {
  prioritizedRules,
  recommendationRows,
} = require("../.test-build/lib/rule-recommendations.js");

test("review order keeps rechecks first without changing saved decisions", () => {
  const items = [
    { rule_id: "1", name: "Keep", priority: "KEEP", recheck_reasons: [] },
    {
      rule_id: "2",
      name: "Stop",
      priority: "WOULD_PAUSE",
      recheck_reasons: [],
    },
    {
      rule_id: "3",
      name: "Old",
      priority: "KEEP",
      recheck_reasons: ["RULE_CHANGED"],
    },
  ];
  assert.deepEqual(
    prioritizedRules(items).map((item) => item.rule_id),
    ["3", "2", "1"],
  );
  assert.deepEqual(
    items.map((item) => item.priority),
    ["KEEP", "WOULD_PAUSE", "KEEP"],
  );
});

test("search and status use saved results with unknown values intact", () => {
  const rows = [
    {
      id: "a",
      external_id: "123",
      name: "Длинное русское название",
      status: "REVIEW",
      actual_roi: null,
      spend: "50",
    },
    {
      id: "b",
      external_id: "456",
      name: "Другой",
      status: "KEEP",
      actual_roi: "10",
      spend: "20",
    },
  ];
  const found = recommendationRows(rows, "REVIEW", " РУССКОЕ ", null);
  assert.equal(found.length, 1);
  assert.equal(found[0].actual_roi, null);
  assert.equal(recommendationRows(rows, "WOULD_PAUSE", "", null).length, 0);
  assert.equal(recommendationRows(rows, "", "456", null)[0].id, "b");
  assert.deepEqual(
    recommendationRows(rows, "", "", { key: "spend", direction: "asc" }).map(
      (row) => row.id,
    ),
    ["b", "a"],
  );
  assert.equal(rows[0].id, "a");
});
