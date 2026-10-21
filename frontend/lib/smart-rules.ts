import type {Target} from "./rule-targets";
import { localized } from "./economics";
import type { StatisticsRow } from "../components/StatisticsTable";
import { serializeAuthenticatedWrite } from "./use-column-preferences";

export const conditionNames = {
  ROI_AT_OR_ABOVE_TARGET: "ROI достиг целевого",
  CPL_AT_OR_BELOW_LIMIT: "Цена лида не выше лимита",
  CPS_AT_OR_BELOW_LIMIT: "Стоимость продажи не выше лимита",
  ROI_BELOW_MINIMUM: "ROI ниже минимального",
  ROI_BELOW_TARGET: "ROI ниже целевого",
  CPL_ABOVE_LIMIT: "Цена лида выше лимита",
  CPS_ABOVE_LIMIT: "Стоимость продажи выше лимита",
  NO_LEADS_SPEND: "Расход без лидов",
  NO_APPROVED_SALES_SPEND: "Расход без подтверждённых продаж",
  MINIMUM_LEADS_GATE: "Достигнут минимум лидов",
  MINIMUM_SALES_GATE: "Достигнут минимум продаж",
  SPEND_THRESHOLD: "Достигнут порог расхода",
};
export type ConditionType = keyof typeof conditionNames;
export type Condition = {
  kind: "condition";
  type: ConditionType;
  source: "actual" | "estimated" | "approved" | "observed";
  limit: "target" | "maximum" | "custom" | "payout";
  value: string | null;
  roi: string | null;
  multiplier: string;
  currency: string | null;
};
export type Group = {
  kind: "group";
  operator: "AND" | "OR";
  children: (Group | Condition)[];
};
export const thresholdNames = {
  minimum_spend: "Минимальный расход",
  minimum_leads: "Минимум лидов",
  minimum_approved_sales: "Минимум подтверждённых продаж",
  minimum_observed_purchases: "Минимум наблюдаемых покупок",
  minimum_processed: "Минимум решений по апруву",
  minimum_data_age_hours: "Минимальный возраст периода, часов",
  maturation_hours: "Созревание апрува, часов",
};
export type ThresholdKey = keyof typeof thresholdNames;
export type Definition = {
  schema_version: 3;
  mode: "DRY_RUN";
  level: "ad";
  name: string;
  action?: "PAUSE_AD" | "ENABLE_AD" | "NOTIFY_ONLY";
  enabled?: boolean;
  priority?: number;
  cooldown_seconds?: number;
  allow_reenable?: boolean;
  description: string;
  profile_id: string | null;
  selection: {
    target_mode?: boolean;
    targets?: Target[];
    account_ids: string[];
    provider: "metricflow" | "meta" | null;
    campaign: string | null;
    adset: string | null;
    ad: string | null;
    offer: string | null;
    geo: string | null;
    status: "ACTIVE" | "PAUSED" | null;
  };
  period:
    | "today"
    | "yesterday"
    | "last_3"
    | "last_7"
    | "last_14"
    | "last_30"
    | "custom";
  start: string | null;
  end: string | null;
  effective_start: string | null;
  effective_end: string | null;
  estimated_policy: "review" | "allow_simulated";
  thresholds: Record<ThresholdKey, number | string | null>;
  expression: Group;
};
export type Rule = {
  id: string;
  revision: number;
  deleted: boolean;
  created_at: string;
  updated_at?: string;
  updated_by?: string;
  last_simulation_at?: string;
  definition: Definition;
};
export type Row = Record<string, unknown>;
export type Simulation = {
  id: string;
  rule_id: string;
  rule_revision: number;
  created_at: string;
  actor_id: string;
  start: string;
  end: string;
  reporting_timezone?: string;
  counts: Record<string, number>;
  rows: Row[];
  total: number;
  missing_profiles: number;
  definition: Definition;
  previous_simulation_id: string | null;
};
export type History = {
  versions: {
    revision: number;
    at: string;
    actor_id: string;
    snapshot: Rule;
  }[];
  simulations: Simulation[];
  audit: { event: string; actor_id: string; at: string; notification?: Record<string,unknown> }[];
};
export function newCondition(
  type: ConditionType = "CPL_ABOVE_LIMIT",
): Condition {
  const zero = type.startsWith("NO_"),
    sample = type.startsWith("MINIMUM_");
  return {
    kind: "condition",
    type,
    source:
      type.startsWith("CPS_") || type === "MINIMUM_SALES_GATE"
        ? "approved"
        : type.startsWith("ROI_")
          ? "estimated"
          : "actual",
    limit: zero || sample ? "custom" : "maximum",
    value: zero ? "20" : sample ? "10" : null,
    roi: null,
    multiplier: "1",
    currency: null,
  };
}
export function newRule(): Definition {
  return {
    schema_version: 3,
    mode: "DRY_RUN",
    level: "ad",
    name: "",
    action: "PAUSE_AD", enabled: false, priority: 0, cooldown_seconds: 3600, allow_reenable: false,
    description: "",
    profile_id: null,
    selection: {
      target_mode: false,
      targets: [],
      account_ids: [],
      provider: null,
      campaign: null,
      adset: null,
      ad: null,
      offer: null,
      geo: null,
      status: null,
    },
    period: "last_7",
    start: null,
    end: null,
    effective_start: null,
    effective_end: null,
    estimated_policy: "review",
    thresholds: {
      minimum_spend: null,
      minimum_leads: null,
      minimum_approved_sales: null,
      minimum_observed_purchases: null,
      minimum_processed: null,
      minimum_data_age_hours: null,
      maturation_hours: null,
    },
    expression: { kind: "group", operator: "AND", children: [newCondition()] },
  };
}
const messages: Record<string, string> = {
  KEEP: "Оставить",
  REVIEW: "Требует проверки",
  WOULD_ENABLE: "Кандидат на включение · симуляция",
  NOTIFY: "Уведомление в MCC",
  NOTIFY_ONLY: "Только уведомление",
  MANUAL_OVERRIDE: "Явная ручная блокировка",
  ANTI_LOOP_COOLDOWN: "Удержание противоположного действия: cooldown",
  CONFLICT_UNVERIFIED: "Конфликт или неподтверждённое состояние другого правила",
  CONFLICT_HIGHER_PRIORITY: "Приоритет другого правила",
  PAUSE_OWNERSHIP_UNVERIFIED: "Отключение нашей системой не подтверждено",
  PARENT_STATE_UNVERIFIED: "Родительские объекты не подтверждены как активные",
  ENABLE_SPEND_EVIDENCE_REQUIRED: "Нужен положительный подтверждённый расход",
  ENABLE_RECOVERY_EVIDENCE_REQUIRED: "Нужны факты завершённого периода до отключения либо подтверждённое созревание апрува",
  ACTION_OUTCOME_UNRESOLVED: "Исход предыдущей рекламной команды неизвестен",
  ENABLE_PERMISSION_REQUIRED: "Нужно явное разрешение повторного включения",
  POSITIVE_ENABLE_EVIDENCE_REQUIRED: "Недостаточно положительных фактических условий включения",
  PROFILE_PERIOD_AMBIGUOUS: "Назначение профиля неоднозначно на границе календарных периодов",
  SELECT_EXPLICIT_PROFILE_FOR_TIMEZONE_SCOPE: "Для более чем 8 timezone выберите явный профиль в правиле",
  PROFILE_SOURCE_TIMEZONE_MISMATCH: "Timezone профиля и дневных фактов не совпадает",
  WOULD_PAUSE: "Кандидат на отключение · симуляция",
  INSUFFICIENT_DATA: "Недостаточно данных",
  DATA_STALE: "Устаревшее или неполное окно",
  TRUE: "Выполнено",
  FALSE: "Не выполнено",
  UNKNOWN: "Неизвестно",
  WINDOW_INCOMPLETE: "Полнота завершённого периода не подтверждена",
  ATTRIBUTION_UNVERIFIED: "Атрибуция источника не подтверждена",
  APPROVAL_PENDING: "Ожидаем апрув или зрелость когорты",
  UNKNOWN_APPROVED_SALES: "Количество апрувов неизвестно",
  UNKNOWN_LEADS: "Количество лидов неизвестно",
  NO_ECONOMIC_PROFILE: "Экономический профиль не назначен",
  CONDITION_UNKNOWN: "Для условия отсутствуют достоверные значения",
  ESTIMATED_MODEL:
    "Фактический ROI не подтверждён; сигнал использует прогнозную модель",
  DRY_RUN_ONLY: "Выполнение запрещено: только симуляция",
  PHASE2_EVIDENCE_NOT_ELIGIBLE:
    "Строгие требования Phase 2 к подтверждениям не выполнены",
  DATA_TOO_YOUNG: "Период ещё слишком молодой",
  RULE_VERSION_CONFLICT:
    "Правило изменено в другой вкладке. Откройте его заново.",
  RULE_EDIT_REQUIRED: "Редактирование правил не разрешено",
  RULE_ARCHIVED: "Правило в архиве",
  RULE_OUTSIDE_EFFECTIVE_DATES: "Правило вне срока действия",
  RULE_NOT_FOUND: "Правило не найдено",
  RULE_VERSION_NOT_FOUND: "Версия не найдена",
  SIMULATION_NOT_FOUND: "Симуляция не найдена",
  SIMULATION_TOO_MANY_ADS_SELECT_SCOPE:
    "Выберите меньше аккаунтов: максимум 500 объявлений",
  SIMULATION_CATALOG_TOO_LARGE:
    "Каталог превышает лимит безопасной синхронной проверки",
  SIMULATION_TIME_LIMIT_SELECT_SCOPE:
    "Проверка превысила лимит времени. Сузьте выборку.",
  CREATE: "Создано",
  UPDATE: "Изменено",
  ARCHIVE: "Архивировано",
  RESTORE: "Восстановлено",
  SIMULATE: "Симуляция",
  GRANT: "Изменены права",
};
export function ruleLabel(value: unknown): string {
  const key = String(value ?? "UNKNOWN");
  if (key.startsWith("INSUFFICIENT_"))
    return (
      "Не достигнут минимальный порог: " +
      ({
        SPEND: "расход",
        LEADS: "лиды",
        APPROVED_SALES: "апрувы",
        PROCESSED_DECISIONS: "решения по апруву",
        OBSERVED_META_PURCHASES: "покупки Meta",
      }[key.slice(13)] ?? key.slice(13))
    );
  return messages[key] ?? localized(key);
}
export function ruleRow(row: Row): StatisticsRow {
  const output: StatisticsRow = {};
  for (const [key, value] of Object.entries(row))
    if (
      value === null ||
      ["string", "number", "boolean"].includes(typeof value)
    )
      output[key] = value as string | number | boolean | null;
  output.rule_status = ruleLabel(row.status);
  output.rule_reason = Array.isArray(row.reason_codes)
    ? row.reason_codes.map(ruleLabel).join("; ")
    : "";
  output.economics_data_quality = localized(row.economics_data_quality);
  output.last_synced = row.source_facts_timestamp as string | null;
  return output;
}
export async function readRules<T>(
  path = "",
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch("/api/smart-rules" + path, {
    cache: "no-store",
    signal,
  });
  const body = await response.json();
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("Повторите вход");
  }
  if (!response.ok) throw new Error(ruleLabel(body.detail));
  return body;
}
export function writeRules<T>(
  path: string,
  method: string,
  body: unknown,
): Promise<T> {
  return serializeAuthenticatedWrite(async () => {
    const csrf = await fetch("/api/auth/csrf", { cache: "no-store" });
    if (!csrf.ok) throw new Error("Повторите вход");
    const response = await fetch("/api/smart-rules" + path, {
      method,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": (await csrf.json()).csrf_token,
      },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok)
      throw new Error(
        typeof data.detail === "string"
          ? ruleLabel(data.detail)
          : "Проверьте поля, пороги и глубину условий: не более 3 групп и 40 элементов.",
      );
    return data;
  });
}
