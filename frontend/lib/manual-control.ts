import { serializeAuthenticatedWrite } from "./use-column-preferences";

export const manualLabels: Record<string, string> = {
  DRAFT: "Черновик",
  BLOCKED: "Реальное исполнение заблокировано",
  CONFIRMED: "Намерение подтверждено · только локально",
  SIMULATED: "Локальная симуляция",
  CANCELLED: "Отменено",
  EXPIRED: "Срок истёк",
  PREFLIGHT_PENDING: "Проверка",
  PREFLIGHT_FAILED: "LIVE-проверка не пройдена",
  AWAITING_CONFIRMATION: "Ожидание подтверждения",
  PAUSE_AD: "Подготовка отключения",
  ENABLE_AD: "Подготовка включения",
  WRITE_DISABLED: "WRITE выключен на сервере",
  WRITE_CONTRACT_UNVERIFIED: "Контракт WRITE не проверен",
  WRITE_PERMISSION_UNVERIFIED: "Разрешение WRITE не подтверждено",
  WRITE_CREDENTIAL_MISSING: "Отдельный WRITE-ключ не подключён",
  STATUS_STALE: "Статус устарел — дождитесь штатной синхронизации",
  STATUS_CHANGED: "Статус изменился",
  ALREADY_TARGET_STATE: "Объявление уже в целевом статусе",
  PROVIDER_UNAVAILABLE: "Провайдер недоступен",
  IDENTITY_CHANGED: "ID изменился",
  AD_ID_MISMATCH: "Ad ID не совпадает",
  ACCOUNT_MISMATCH: "Кабинет не совпадает",
  ACCOUNT_CHANGED: "Кабинет изменился",
  ACCOUNT_UNCONFIRMED: "Идентичность кабинета не подтверждена",
  HIERARCHY_UNCONFIRMED: "Иерархия не подтверждена",
  HIERARCHY_CHANGED: "Иерархия изменилась",
  CREDENTIAL_CHANGED: "Подключение изменилось",
  ROUTING_CHANGED: "Маршрутизация изменилась",
  PROVIDER_CHANGED: "Провайдер изменился",
  PROVIDER_MISMATCH: "Провайдер не совпадает",
  ROUTING_PROVIDER_MISMATCH: "Источник не совпадает с маршрутизацией",
  RULE_SOURCE_CHANGED: "Данные рекомендации изменились",
  PENDING_ACTION_CONFLICT: "Для объявления уже есть незавершённая команда",
  IDENTICAL_OPERATION_COMPLETED: "Такая операция уже выполнена",
  ACTION_REVISION_CONFLICT:
    "Команда изменена в другой вкладке — откройте её заново",
  MANUAL_CONTROL_PERMISSION_REQUIRED:
    "Нет отдельного разрешения на ручное управление",
  LOCAL_SIMULATION_ONLY: "Рекламные данные не изменены",
  UNVERIFIED: "Не проверено",
};
export const manualLabel = (value: string) => manualLabels[value] ?? value;

export async function manualRead<T>(path: string): Promise<T> {
  const response = await fetch("/api/manual-control" + path, {
    cache: "no-store",
  });
  const data = await response.json();
  if (response.status === 401) window.location.assign("/login");
  if (!response.ok) throw new Error(manualLabel(data.detail));
  return data;
}
export function manualWrite<T>(
  path: string,
  body: unknown,
  key?: string,
  method = "POST",
): Promise<T> {
  return serializeAuthenticatedWrite(async () => {
    const csrf = await fetch("/api/auth/csrf", { cache: "no-store" });
    if (!csrf.ok) throw new Error("Повторите вход");
    const response = await fetch("/api/manual-control" + path, {
      method,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": (await csrf.json()).csrf_token,
        ...(key ? { "Idempotency-Key": key } : {}),
      },
      body: JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok)
      throw new Error(
        typeof result.detail === "string"
          ? manualLabel(result.detail)
          : "Проверьте поля команды",
      );
    return result;
  });
}
