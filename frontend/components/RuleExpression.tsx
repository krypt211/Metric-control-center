"use client";
import {
  conditionNames,
  newCondition,
  type Condition,
  type ConditionType,
  type Group,
} from "../lib/smart-rules";

export default function RuleExpression({
  value,
  change,
  depth = 1,
}: {
  value: Group;
  change: (next: Group) => void;
  depth?: number;
}) {
  function replace(i: number, child: Group | Condition) {
    change({
      ...value,
      children: value.children.map((c, n) => (n === i ? child : c)),
    });
  }
  return (
    <fieldset className="rule-expression">
      <legend>Группа условий · уровень {depth}</legend>
      <label>
        Оператор группы
        <select
          aria-label={`Оператор группы ${depth}`}
          value={value.operator}
          onChange={(e) =>
            change({ ...value, operator: e.target.value as "AND" | "OR" })
          }
        >
          <option value="AND">И (AND) — все условия</option>
          <option value="OR">ИЛИ (OR) — любое условие</option>
        </select>
      </label>
      {value.children.map((c, i) => (
        <div className="rule-condition" key={i}>
          {c.kind === "group" ? (
            <RuleExpression
              value={c}
              depth={depth + 1}
              change={(next) => replace(i, next)}
            />
          ) : (
            <>
              <label>
                Условие {i + 1}
                <select
                  value={c.type}
                  onChange={(e) =>
                    replace(i, newCondition(e.target.value as ConditionType))
                  }
                >
                  {Object.entries(conditionNames).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
              {(c.type.startsWith("ROI_") ||
                c.type === "CPS_ABOVE_LIMIT" ||
                c.type === "MINIMUM_SALES_GATE") && (
                <label>
                  Источник метрики
                  <select
                    value={c.source}
                    onChange={(e) =>
                      replace(i, {
                        ...c,
                        source: e.target.value as Condition["source"],
                      })
                    }
                  >
                    {c.type.startsWith("ROI_") ? (
                      <>
                        <option value="actual">Фактический ROI</option>
                        <option value="estimated">Прогнозный ROI</option>
                      </>
                    ) : (
                      <>
                        <option value="approved">Подтверждённые продажи</option>
                        <option value="observed">
                          Покупки Meta (не апрувы)
                        </option>
                        <option value="estimated">Прогнозные апрувы</option>
                      </>
                    )}
                  </select>
                </label>
              )}
              {c.type.startsWith("ROI_") ? (
                <label>
                  ROI, % · пусто = профиль
                  <input
                    inputMode="decimal"
                    value={c.roi ?? ""}
                    onChange={(e) =>
                      replace(i, { ...c, roi: e.target.value || null })
                    }
                  />
                </label>
              ) : (
                <>
                  {!c.type.startsWith("NO_") &&
                    !c.type.startsWith("MINIMUM_") && (
                      <label>
                        Источник порога
                        <select
                          value={c.limit}
                          onChange={(e) =>
                            replace(i, {
                              ...c,
                              limit: e.target.value as Condition["limit"],
                              value:
                                e.target.value === "custom"
                                  ? (c.value ?? "20")
                                  : null,
                            })
                          }
                        >
                          <option value="target">
                            Целевой ориентир профиля
                          </option>
                          <option value="maximum">
                            Максимальный ориентир профиля
                          </option>
                          <option value="custom">Свой порог</option>
                          {c.type === "SPEND_THRESHOLD" && (
                            <option value="payout">Выплата за апрув</option>
                          )}
                        </select>
                      </label>
                    )}
                  {c.limit === "custom" && (
                    <label>
                      {c.type.startsWith("MINIMUM_")
                        ? "Количество событий"
                        : "Порог в валюте профиля"}
                      <input
                        required
                        inputMode="decimal"
                        value={c.value ?? ""}
                        onChange={(e) =>
                          replace(i, { ...c, value: e.target.value })
                        }
                      />
                    </label>
                  )}
                  {c.type === "SPEND_THRESHOLD" && (
                    <label>
                      Кратность порога
                      <input
                        required
                        inputMode="decimal"
                        value={c.multiplier}
                        onChange={(e) =>
                          replace(i, { ...c, multiplier: e.target.value })
                        }
                      />
                    </label>
                  )}
                  {!c.type.startsWith("MINIMUM_") && c.limit === "custom" && (
                    <label>
                      Валюта · пусто = профиль
                      <input
                        maxLength={3}
                        pattern="[A-Z]{3}|"
                        value={c.currency ?? ""}
                        onChange={(e) =>
                          replace(i, {
                            ...c,
                            currency: e.target.value.toUpperCase() || null,
                          })
                        }
                      />
                    </label>
                  )}
                </>
              )}
              <p className="card-note">
                {c.type.startsWith("ROI_")
                  ? "Сигнал, если ROI ниже выбранного ориентира; прогноз и факт проверяются отдельно."
                  : c.type.startsWith("NO_")
                    ? "Расход достиг порога и подтверждён ноль событий. Неизвестное значение не считается нулём."
                    : c.type.startsWith("MINIMUM_")
                      ? "Проверка достаточности выборки по выбранному типу событий."
                      : "Сравнение с ориентиром профиля в совместимой валюте."}
              </p>
            </>
          )}
          <button
            type="button"
            disabled={value.children.length === 1}
            onClick={() =>
              change({
                ...value,
                children: value.children.filter((_, n) => n !== i),
              })
            }
          >
            Удалить условие {i + 1}
          </button>
        </div>
      ))}
      <button
        type="button"
        disabled={value.children.length >= 20}
        onClick={() =>
          change({ ...value, children: [...value.children, newCondition()] })
        }
      >
        Добавить условие
      </button>
      {depth < 3 && (
        <button
          type="button"
          disabled={value.children.length >= 20}
          onClick={() =>
            change({
              ...value,
              children: [
                ...value.children,
                { kind: "group", operator: "AND", children: [newCondition()] },
              ],
            })
          }
        >
          Добавить группу
        </button>
      )}
    </fieldset>
  );
}
