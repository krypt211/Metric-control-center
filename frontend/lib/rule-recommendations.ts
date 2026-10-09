import type { Row } from "./smart-rules";
import { ruleRow } from "./smart-rules";
import type { Sorting } from "./column-model";

export const reviewStatuses = [
  "WOULD_PAUSE",
  "REVIEW",
  "DATA_STALE",
  "INSUFFICIENT_DATA",
  "KEEP",
];
export const recheckNames: Record<string, string> = {
  NOT_EVALUATED: "Проверка ещё не запускалась",
  RULE_CHANGED: "Правило изменилось после проверки",
  SNAPSHOT_OLD: "Результат старше 36 часов",
  ECONOMICS_CHANGED:
    "В рабочем пространстве изменились профили, назначения или апрувы",
  PERIOD_CHANGED: "Для текущего периода нужна новая проверка",
  OUTSIDE_EFFECTIVE_DATES: "Правило вне срока действия",
};
export type RecommendationItem = {
  rule_id: string;
  name: string;
  rule_revision: number;
  simulation_id: string | null;
  simulation_revision: number | null;
  created_at: string | null;
  start: string | null;
  end: string | null;
  counts: Record<string, number>;
  total: number;
  recheck_reasons: string[];
  priority: string;
};
export type RecommendationSummary = {
  mode: "DRY_RUN";
  real_action: false;
  as_of: string;
  rows: RecommendationItem[];
  counts: Record<string, number>;
  total_rules: number;
  offset: number;
  next_offset: number | null;
};
export function prioritizedRules(
  items: RecommendationItem[],
): RecommendationItem[] {
  return [...items].sort((a, b) => {
    const rank = (item: RecommendationItem) =>
      item.recheck_reasons.length ? -1 : reviewStatuses.indexOf(item.priority);
    return (
      rank(a) - rank(b) ||
      a.name.localeCompare(b.name, "ru") ||
      a.rule_id.localeCompare(b.rule_id)
    );
  });
}
export function recommendationRows(
  rows: Row[],
  status: string,
  search: string,
  sorting: Sorting,
) {
  const query = search.trim().toLocaleLowerCase("ru");
  const result = rows
    .filter(
      (row) =>
        (!status || row.status === status) &&
        (!query ||
          `${row.name} ${row.id} ${row.external_id}`
            .toLocaleLowerCase("ru")
            .includes(query)),
    )
    .map(ruleRow);
  if (!sorting) return result;
  return result.sort((a, b) => {
    const left = a[sorting.key],
      right = b[sorting.key];
    if (left == null || right == null)
      return left == null ? (right == null ? 0 : 1) : -1;
    const numeric =
      typeof left === "number" || /^-?\d+(\.\d+)?$/.test(String(left));
    const difference = numeric
      ? Number(left) - Number(right)
      : String(left).localeCompare(String(right), "ru");
    return sorting.direction === "asc" ? difference : -difference;
  });
}
