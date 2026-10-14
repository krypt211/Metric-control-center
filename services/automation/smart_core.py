"""Pure three-valued condition evaluation over Phase 2 results. No action imports."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal as D
from decimal import localcontext
from typing import Any, Literal
from zoneinfo import ZoneInfo

from services.automation.smart_schema import Condition, Group, SmartRuleInput
from services.economics.core import ratio, serial

Truth = Literal["TRUE", "FALSE", "UNKNOWN"]
STALE = {
    "SOURCE_STALE",
    "INCOMPLETE_WINDOW",
    "PROVIDER_UNAVAILABLE",
    "WINDOW_INCOMPLETE",
    "PROFILE_SOURCE_TIMEZONE_MISMATCH",
}


def combine(operator: str, values: list[Truth]) -> Truth:
    """Kleene logic: FALSE dominates AND, TRUE dominates OR, else UNKNOWN."""
    decisive = "FALSE" if operator == "AND" else "TRUE"
    if decisive in values:
        return decisive  # type: ignore[return-value]
    if "UNKNOWN" in values:
        return "UNKNOWN"
    return "TRUE" if operator == "AND" else "FALSE"


def number(row: dict[str, Any], key: str) -> D | None:
    value = row.get(key)
    return D(str(value)) if value is not None else None


def applied_thresholds(rule: SmartRuleInput, profile: dict[str, Any]) -> dict[str, Any]:
    inherited = {
        "minimum_spend": profile.get("minimum_spend", "0"),
        "minimum_leads": profile.get("minimum_leads", 10),
        "minimum_approved_sales": profile.get("minimum_sales", 2)
        if profile.get("sale_threshold_type", "approved") == "approved"
        else 0,
        "minimum_observed_purchases": profile.get("minimum_observed_purchases", 0),
        "minimum_processed": profile.get("minimum_processed", 30),
        "minimum_data_age_hours": profile.get("minimum_data_age_hours", 0),
        "maturation_hours": profile.get("maturation_hours", 72),
    }
    local = rule.thresholds.model_dump(mode="json")
    return {
        k: {
            "inherited": v,
            "local": local[k],
            "applied": local[k] if local[k] is not None else v,
        }
        for k, v in inherited.items()
    }


def condition(c: Condition, row: dict[str, Any]) -> dict[str, Any]:
    """Compare ready financial values; derived CPS uses the shared safe ratio."""
    original_type = c.type
    positive = {
        "ROI_AT_OR_ABOVE_TARGET": "ROI_BELOW_TARGET",
        "CPL_AT_OR_BELOW_LIMIT": "CPL_ABOVE_LIMIT",
        "CPS_AT_OR_BELOW_LIMIT": "CPS_ABOVE_LIMIT",
    }
    if original_type in positive:
        c = c.model_copy(update={"type": positive[original_type]})
    reasons = []
    estimated = c.source == "estimated" and c.type in (
        "ROI_BELOW_MINIMUM",
        "ROI_BELOW_TARGET",
        "ROI_AT_OR_ABOVE_TARGET",
        "CPS_ABOVE_LIMIT",
        "CPS_AT_OR_BELOW_LIMIT",
        "MINIMUM_SALES_GATE",
    )
    count_only = c.type in ("MINIMUM_LEADS_GATE", "MINIMUM_SALES_GATE")
    if row.get("source_stale") or not row.get("window_complete"):
        reasons.append(
            "WINDOW_INCOMPLETE" if not row.get("window_complete") else "SOURCE_STALE"
        )
    if not count_only and (
        row.get("currency") != row.get("profile_currency")
        or (c.currency and c.currency != row.get("currency"))
    ):
        reasons.append("CURRENCY_MISMATCH")
    actual, limit, key = None, None, ""
    t = c.type
    if t.startswith("ROI_"):
        key = c.source + "_roi"
        actual = number(row, key)
        limit = (
            c.roi
            if c.roi is not None
            else number(
                row, "minimum_roi" if t == "ROI_BELOW_MINIMUM" else "target_roi"
            )
        )
    elif t == "CPL_ABOVE_LIMIT":
        key = "actual_cpl"
        actual = number(row, key)
        limit = (
            c.value
            if c.limit == "custom"
            else number(row, "target_cpl" if c.limit == "target" else "maximum_cpl")
        )
    elif t == "CPS_ABOVE_LIMIT":
        key = {
            "approved": "approved_cps",
            "observed": "observed_purchase_cost",
            "estimated": "estimated_approved_cps",
        }[c.source]
        with localcontext() as ctx:
            ctx.prec = 64
            actual = (
                ratio(number(row, "spend"), number(row, "estimated_sales"))
                if c.source == "estimated"
                else number(row, key)
            )
        limit = (
            c.value
            if c.limit == "custom"
            else number(
                row,
                "target_approved_cps"
                if c.limit == "target"
                else "maximum_approved_cps",
            )
        )
    elif t in ("NO_LEADS_SPEND", "NO_APPROVED_SALES_SPEND", "SPEND_THRESHOLD"):
        key = "spend"
        actual = number(row, key)
        limit = (
            c.value
            if c.limit == "custom"
            else number(
                row,
                {"target": "target_cpl", "maximum": "maximum_cpl", "payout": "payout"}[
                    c.limit
                ],
            )
        )
        if limit is not None:
            limit *= c.multiplier
        if t.startswith("NO_"):
            events = row.get("leads" if t == "NO_LEADS_SPEND" else "approved_sales")
            if events is None:
                reasons.append(
                    "UNKNOWN_LEADS"
                    if t == "NO_LEADS_SPEND"
                    else "UNKNOWN_APPROVED_SALES"
                )
    else:
        key = (
            "leads"
            if t == "MINIMUM_LEADS_GATE"
            else {
                "approved": "approved_sales",
                "observed": "observed_meta_purchases",
                "estimated": "estimated_sales",
            }[c.source]
        )
        actual, limit = number(row, key), c.value
    requires_approval = (
        t == "NO_APPROVED_SALES_SPEND"
        or (t.startswith("ROI_") and c.source == "actual")
        or (t in ("CPS_ABOVE_LIMIT", "MINIMUM_SALES_GATE") and c.source == "approved")
    )
    if requires_approval and (
        row.get("maturity_status") != "MATURE"
        or row.get("pending_sales") is None
        or row.get("pending_sales") != 0
    ):
        reasons.append("APPROVAL_PENDING")
    if actual is None or limit is None:
        reasons.append("CONDITION_UNKNOWN")
    truth: Truth = "UNKNOWN"
    if not reasons:
        assert actual is not None and limit is not None
        hit = (
            actual < limit
            if t.startswith("ROI_")
            else actual > limit
            if t in ("CPL_ABOVE_LIMIT", "CPS_ABOVE_LIMIT")
            else actual >= limit
        )
        if t.startswith("NO_"):
            hit = (
                hit
                and row.get("leads" if t == "NO_LEADS_SPEND" else "approved_sales") == 0
            )
        if original_type in positive:
            hit = not hit
        truth = "TRUE" if hit else "FALSE"
    delta = (
        serial(actual - limit)
        if actual is not None and limit is not None and not reasons
        else None
    )
    return {
        "kind": "condition",
        "type": original_type,
        "source": c.source,
        "metric": key,
        "truth": truth,
        "value": serial(actual),
        "threshold": serial(limit),
        "delta": delta,
        "estimated": estimated,
        "reason_codes": reasons,
    }


def expression(group: Group, row: dict[str, Any]) -> dict[str, Any]:
    children = [
        expression(c, row) if isinstance(c, Group) else condition(c, row)
        for c in group.children
    ]
    return {
        "kind": "group",
        "operator": group.operator,
        "truth": combine(group.operator, [c["truth"] for c in children]),
        "children": children,
    }


def leaves(result: dict[str, Any]) -> list[dict[str, Any]]:
    if result["kind"] == "condition":
        return [result]
    return [leaf for child in result["children"] for leaf in leaves(child)]


def witnesses(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Use the TRUE branches for applicable sample gates, especially zero-event OR."""
    if result["kind"] == "condition":
        return [result] if result["truth"] == "TRUE" else []
    return [
        leaf
        for child in result["children"]
        if child["truth"] == "TRUE"
        for leaf in witnesses(child)
    ]


def decision(
    rule: SmartRuleInput, row: dict[str, Any], profile: dict[str, Any], now: datetime
) -> dict[str, Any]:
    """Simulation permission and strict Phase 2 evidence eligibility remain distinct."""
    thresholds = applied_thresholds(rule, profile)
    values = {k: v["applied"] for k, v in thresholds.items()}
    tree = expression(rule.expression, row)
    checks = leaves(tree)
    applicable = witnesses(tree) if tree["truth"] == "TRUE" else checks
    reasons = sorted({r for c in checks for r in c["reason_codes"]})
    reasons.extend(
        code
        for code in row.get("reason_codes", [])
        if code == "PROFILE_PERIOD_AMBIGUOUS"
    )
    blockers = ["DRY_RUN_ONLY"]
    if row.get("evaluation_timezone", row.get("timezone")) != profile.get(
        "timezone", "Europe/Moscow"
    ):
        reasons.append("PROFILE_SOURCE_TIMEZONE_MISMATCH")
    zero_only = all(
        c["type"] in ("NO_LEADS_SPEND", "SPEND_THRESHOLD") for c in applicable
    )
    approved_required = any(
        c["type"] == "NO_APPROVED_SALES_SPEND"
        or (
            c["source"] in ("actual", "approved")
            and c["type"]
            in (
                "ROI_BELOW_MINIMUM",
                "ROI_BELOW_TARGET",
                "ROI_AT_OR_ABOVE_TARGET",
                "CPS_ABOVE_LIMIT",
                "CPS_AT_OR_BELOW_LIMIT",
                "MINIMUM_SALES_GATE",
            )
        )
        for c in applicable
    )
    observed_required = any(
        c["source"] == "observed"
        and c["type"]
        in ("CPS_ABOVE_LIMIT", "CPS_AT_OR_BELOW_LIMIT", "MINIMUM_SALES_GATE")
        for c in applicable
    )
    gates = [("minimum_spend", "spend")]
    if not zero_only:
        gates.append(("minimum_leads", "leads"))
    if approved_required:
        gates += [
            ("minimum_approved_sales", "approved_sales"),
            ("minimum_processed", "processed_decisions"),
        ]
    if observed_required:
        gates.append(("minimum_observed_purchases", "observed_meta_purchases"))
    for threshold, metric in gates:
        known = number(row, metric)
        if known is None or known < D(str(values[threshold])):
            reasons.append("INSUFFICIENT_" + metric.upper())
    mature_at = None
    if row.get("period_end") and row.get("timezone"):
        end = datetime.fromisoformat(row["period_end"]).date()
        boundary = datetime.combine(
            end + timedelta(days=1),
            time.min,
            tzinfo=ZoneInfo(row.get("evaluation_timezone", row["timezone"])),
        )
        boundary = boundary.astimezone(UTC)
        mature_at = boundary + timedelta(hours=int(values["maturation_hours"]))
        if now < boundary + timedelta(hours=int(values["minimum_data_age_hours"])):
            reasons.append("DATA_TOO_YOUNG")
        if approved_required and (
            now < mature_at or row.get("maturity_status") != "MATURE"
        ):
            reasons.append("APPROVAL_PENDING")
    if not row.get("profile_id"):
        reasons.append("NO_ECONOMIC_PROFILE")
    if not row.get("source_attribution"):
        reasons.append("ATTRIBUTION_UNVERIFIED")
    insufficient = any(
        r.startswith("INSUFFICIENT_")
        or r in ("NO_ECONOMIC_PROFILE", "CURRENCY_MISMATCH", "DATA_TOO_YOUNG")
        for r in reasons
    )
    estimated = any(c["estimated"] and c["truth"] == "TRUE" for c in checks)
    unknown = any(c["truth"] == "UNKNOWN" for c in checks)
    if (
        row.get("source_stale")
        or not row.get("window_complete")
        or STALE.intersection(reasons)
    ):
        status = "DATA_STALE"
    elif insufficient:
        status = "INSUFFICIENT_DATA"
    elif tree["truth"] == "UNKNOWN":
        status = (
            "REVIEW"
            if any(c["truth"] == "TRUE" for c in checks)
            else "INSUFFICIENT_DATA"
        )
    elif tree["truth"] == "FALSE":
        status = "KEEP"
    elif (
        unknown
        or "APPROVAL_PENDING" in reasons
        or "ATTRIBUTION_UNVERIFIED" in reasons
        or (estimated and rule.estimated_policy == "review")
    ):
        status = "REVIEW"
    else:
        status = "WOULD_PAUSE"
    if estimated:
        reasons.append("ESTIMATED_MODEL")
    if status == "WOULD_PAUSE" and rule.action == "NOTIFY_ONLY":
        status = "NOTIFY"
    elif status == "WOULD_PAUSE" and rule.action == "ENABLE_AD":
        # Cost ratios must not turn missing/zero post-pause spend into recovery.
        # For cost-only ENABLE, require a completed cohort ending before the
        # verified pause. Mature factual approval may supply new positive evidence.
        cohort_before_pause = False
        if (
            row.get("verified_pause_at")
            and row.get("period_end")
            and row.get("timezone")
        ):
            cohort_end = datetime.combine(
                datetime.fromisoformat(row["period_end"]).date() + timedelta(days=1),
                time.min,
                tzinfo=ZoneInfo(row.get("evaluation_timezone", row["timezone"])),
            ).astimezone(UTC)
            paused_at = datetime.fromisoformat(row["verified_pause_at"])
            cohort_before_pause = (
                paused_at.tzinfo is not None and cohort_end <= paused_at
            )
        mature_factual_recovery = bool(
            row.get("eligible_for_rule_evaluation")
            and any(
                c["truth"] == "TRUE"
                and c["source"] in ("actual", "approved")
                and c["type"] in ("ROI_AT_OR_ABOVE_TARGET", "CPS_AT_OR_BELOW_LIMIT")
                for c in applicable
            )
        )
        required = {
            "ENABLE_SPEND_EVIDENCE_REQUIRED": number(row, "spend") is not None
            and number(row, "spend") > 0,
            "ENABLE_RECOVERY_EVIDENCE_REQUIRED": cohort_before_pause
            or mature_factual_recovery,
            "ENABLE_PERMISSION_REQUIRED": rule.allow_reenable
            and row.get("reenable_allowed") is True,
            "PAUSE_OWNERSHIP_UNVERIFIED": row.get("paused_by_system") is True,
            "PARENT_STATE_UNVERIFIED": row.get("parents_active") is True,
            "AD_NOT_PAUSED": row.get("ad_status") == "PAUSED",
            "POSITIVE_ENABLE_EVIDENCE_REQUIRED": any(
                c["type"]
                in (
                    "ROI_AT_OR_ABOVE_TARGET",
                    "CPL_AT_OR_BELOW_LIMIT",
                    "CPS_AT_OR_BELOW_LIMIT",
                )
                and c["truth"] == "TRUE"
                and not c["estimated"]
                for c in applicable
            ),
        }
        reasons.extend(k for k, v in required.items() if not v)
        status = "WOULD_ENABLE" if all(required.values()) else "REVIEW"
    strict = bool(
        row.get("eligible_for_rule_evaluation")
        and not reasons
        and tree["truth"] == "TRUE"
    )
    if not row.get("eligible_for_rule_evaluation"):
        blockers.append("PHASE2_EVIDENCE_NOT_ELIGIBLE")
    blockers += reasons
    return {
        "status": status,
        "requested_action": rule.action,
        "priority": rule.priority,
        "cooldown_seconds": rule.cooldown_seconds,
        "condition_matched": tree["truth"],
        "analytical_signal": any(c["truth"] == "TRUE" for c in checks),
        "simulated_decision": status,
        "safe_to_consider_for_future_action": strict,
        "action_eligibility": False,
        "real_action": False,
        "expression_result": tree,
        "applied_thresholds": thresholds,
        "reason_codes": sorted(set(reasons)),
        "future_action_blockers": sorted(set(blockers)),
        "estimated": estimated,
        "mature_at": mature_at.isoformat() if mature_at else None,
    }


def arbitrate(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Manual hold, unknown evidence, PAUSE, ENABLE, KEEP; numeric priority breaks ties."""
    actions = {"WOULD_PAUSE", "WOULD_ENABLE"}
    blocked = any(
        c.get("manual_blocked")
        or c["status"] in ("DATA_STALE", "INSUFFICIENT_DATA", "REVIEW")
        for c in candidates
    )
    eligible = [c for c in candidates if c["status"] in actions]
    winner = None
    if any(c.get("pause_condition_active") for c in candidates) and not any(
        c["status"] == "WOULD_PAUSE" for c in candidates
    ):
        blocked = True
    if eligible and not blocked:
        winner = min(
            eligible,
            key=lambda c: (
                0 if c["status"] == "WOULD_PAUSE" else 1,
                -c.get("priority", 0),
                c["rule_id"],
            ),
        )
    for candidate in candidates:
        if candidate["status"] in actions and (blocked or candidate is not winner):
            candidate["status"] = "REVIEW"
            reason = (
                "MANUAL_OVERRIDE"
                if any(c.get("manual_blocked") for c in candidates)
                else ("CONFLICT_UNVERIFIED" if blocked else "CONFLICT_HIGHER_PRIORITY")
            )
            candidate["reason_codes"] = sorted(
                set(candidate.get("reason_codes", []) + [reason])
            )
            candidate["safe_to_consider_for_future_action"] = False
        candidate["simulated_decision"] = candidate["status"]
    return candidates
