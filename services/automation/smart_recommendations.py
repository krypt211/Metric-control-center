"""Read-only overview of saved simulations; no new economic calculations."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.automation.smart_models import RuleSimulation
from services.automation.smart_schema import SmartRuleInput, period
from services.economics.models import (
    ApprovalObservation,
    EconomicsAssignment,
    EconomicsProfile,
)
from services.economics.store import utcnow
from services.storage.models import Rule
from services.sync.engine import aware

STATUSES = ("WOULD_PAUSE", "REVIEW", "DATA_STALE", "INSUFFICIENT_DATA", "KEEP")
MAX_REVIEW_AGE = timedelta(hours=36)


def recommendation_summary(
    s: Session,
    workspace: str,
    *,
    now: datetime | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Return one summary per active rule, reading small JSON fields only.

    Counts are rule/ad occurrences, not deduplicated ads or financial totals.
    Recheck markers never change the original immutable decision.
    """
    now = now or utcnow()
    today = now.astimezone(ZoneInfo("Europe/Moscow")).date()
    changes = [
        s.scalar(
            select(func.max(model.updated_at)).where(model.workspace_id == workspace)
        )
        for model in (EconomicsProfile, EconomicsAssignment, ApprovalObservation)
    ]
    economics_changed = max((aware(t) for t in changes if t), default=None)
    latest = (
        select(RuleSimulation.id)
        .where(
            RuleSimulation.rule_id == Rule.id, RuleSimulation.workspace_id == workspace
        )
        .order_by(RuleSimulation.created_at.desc(), RuleSimulation.id.desc())
        .limit(1)
        .correlate(Rule)
        .scalar_subquery()
    )
    query = (
        select(
            Rule.id,
            Rule.revision,
            Rule.payload,
            RuleSimulation.id.label("simulation_id"),
            RuleSimulation.revision.label("simulation_revision"),
            RuleSimulation.created_at,
            RuleSimulation.payload["counts"].label("counts"),
            RuleSimulation.payload["total"].as_integer().label("total"),
            RuleSimulation.payload["start"].as_string().label("start"),
            RuleSimulation.payload["end"].as_string().label("end"),
        )
        .outerjoin(RuleSimulation, RuleSimulation.id == latest)
        .where(Rule.workspace_id == workspace, Rule.status == "SMART_DRY_RUN")
        .order_by(Rule.created_at.desc(), Rule.id.desc())
        .offset(offset)
        .limit(limit)
    )
    items = []
    counts: Counter[str] = Counter()
    for row in s.execute(query).mappings():
        config = SmartRuleInput.model_validate(row["payload"])
        reasons = []
        saved = {key: (row["counts"] or {}).get(key, 0) for key in STATUSES}
        if not row["simulation_id"]:
            reasons.append("NOT_EVALUATED")
        else:
            created = aware(row["created_at"])
            if row["simulation_revision"] != row["revision"]:
                reasons.append("RULE_CHANGED")
            if now - created > MAX_REVIEW_AGE:
                reasons.append("SNAPSHOT_OLD")
            if economics_changed and economics_changed > created:
                reasons.append("ECONOMICS_CHANGED")
            try:
                first, last = period(config, now)
                if (str(first), str(last)) != (row["start"], row["end"]):
                    reasons.append("PERIOD_CHANGED")
            except ValueError:
                reasons.append("PERIOD_CHANGED")
        if (config.effective_start and today < config.effective_start) or (
            config.effective_end and today > config.effective_end
        ):
            reasons.append("OUTSIDE_EFFECTIVE_DATES")
        counts.update(saved)
        items.append(
            {
                "rule_id": row["id"],
                "name": config.name,
                "rule_revision": row["revision"],
                "simulation_id": row["simulation_id"],
                "simulation_revision": row["simulation_revision"],
                "created_at": row["created_at"].isoformat()
                if row["created_at"]
                else None,
                "start": row["start"],
                "end": row["end"],
                "counts": saved,
                "total": row["total"] or 0,
                "recheck_reasons": reasons,
                "priority": next(
                    (key for key in STATUSES if saved[key]), "NOT_EVALUATED"
                ),
            }
        )
    total_rules = (
        s.scalar(
            select(func.count())
            .select_from(Rule)
            .where(Rule.workspace_id == workspace, Rule.status == "SMART_DRY_RUN")
        )
        or 0
    )
    return {
        "mode": "DRY_RUN",
        "real_action": False,
        "as_of": now.isoformat(),
        "rows": items,
        "counts": {key: counts[key] for key in STATUSES},
        "count_semantics": "rule_ad_occurrences_on_page",
        "total_rules": total_rules,
        "offset": offset,
        "next_offset": offset + limit if offset + limit < total_rules else None,
        "review_max_age_hours": 36,
    }
