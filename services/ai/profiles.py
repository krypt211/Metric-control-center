"""Typed GEO/offer instructions and atomic scaling cooldowns."""
from datetime import timedelta
from decimal import Decimal
import json
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from services.actions.engine import ActionRejected
from services.analytics.table import Filters, table_data
from services.analytics.recommendations import fresh
from services.storage.models import Ad, AdSet, AdAccount, Breakdown, Entity, MediaBuyerCooldown, MediaBuyerProfile
from services.storage.repository import insert_for
from services.sync.engine import aware


class MediaProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    country: str = Field(pattern=r"^[A-Z]{2}$")
    offer: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    target_cpl: Decimal = Field(default=Decimal("8"), gt=0, allow_inf_nan=False, max_digits=24, decimal_places=8)
    critical_cpl: Decimal = Field(default=Decimal("15"), gt=0, allow_inf_nan=False, max_digits=24, decimal_places=8)
    target_roi: Decimal = Field(default=Decimal("70"), allow_inf_nan=False, max_digits=24, decimal_places=8)
    scaling_percent: Decimal = Field(default=Decimal("15"), gt=0, le=20, allow_inf_nan=False)
    scaling_cooldown_seconds: int = Field(default=28800, ge=60, le=604800)
    max_adset_budget: Decimal = Field(default=Decimal("250"), gt=0, le=300, allow_inf_nan=False, max_digits=24, decimal_places=8)
    stop_spend: Decimal = Field(default=Decimal("20"), gt=0, allow_inf_nan=False, max_digits=24, decimal_places=8)

    @model_validator(mode="after")
    def check(self):
        if not self.offer.strip() or self.critical_cpl < self.target_cpl:
            raise ValueError("Offer is required; critical CPL cannot be below target")
        return self


def save(sessions, workspace, config, revision, now):
    identity = str(uuid5(NAMESPACE_URL, json.dumps(["profile", workspace, config.country, config.offer])))
    try:
        with sessions.begin() as session:
            if revision == 0:
                session.add(MediaBuyerProfile(id=identity, workspace_id=workspace, country=config.country, offer=config.offer,
                    revision=1, payload=config.model_dump(mode="json"), updated_at=now))
            else:
                changed = session.execute(update(MediaBuyerProfile).where(MediaBuyerProfile.id == identity,
                    MediaBuyerProfile.workspace_id == workspace, MediaBuyerProfile.revision == revision).values(
                        revision=revision+1, payload=config.model_dump(mode="json"), updated_at=now))
                if changed.rowcount != 1:
                    raise ActionRejected("Media buyer profile changed; reload before saving")
    except IntegrityError:
        raise ActionRejected("Media buyer profile changed; reload before saving") from None
    return identity


def related_ads(session, entity):
    ads = session.scalars(select(Ad).join(Entity).where(Entity.account_id == entity.account_id)).all()
    sets = {s.entity_id: s for s in session.scalars(select(AdSet).join(Entity).where(Entity.account_id == entity.account_id))}
    return [a.entity_id for a in ads if (entity.kind == "ad" and a.entity_id == entity.id) or
        (entity.kind == "adset" and a.adset_id == entity.id) or (entity.kind == "creative" and a.creative_id == entity.id) or
        (entity.kind == "campaign" and a.adset_id in sets and sets[a.adset_id].campaign_id == entity.id)]


def snapshot_profiles(session, workspace, entity, now):
    account = session.get(AdAccount, entity.account_id)
    ids = related_ads(session, entity)
    offers = {r.labels.get("offer") for r in session.scalars(select(Entity).where(Entity.id.in_(ids)))}
    offers.add(entity.labels.get("offer"))
    today = now.astimezone(ZoneInfo(account.timezone)).date()
    countries = {r.dimensions.get("country") for r in session.scalars(select(Breakdown).where(
        Breakdown.entity_id.in_(ids), Breakdown.day == today, Breakdown.source == "metricflow")) if set(r.dimensions) == {"country"}}
    # Declared GEO labels may identify scope, but never substitute for metrics.
    countries.update(r.labels.get("country", r.labels.get("geo")) for r in session.scalars(select(Entity).where(Entity.id.in_(ids))))
    profiles = session.scalars(select(MediaBuyerProfile).where(MediaBuyerProfile.workspace_id == workspace)).all()
    results = []
    for profile in profiles:
        config = MediaProfile.model_validate(profile.payload)
        if not config.enabled or profile.country not in countries or profile.offer not in offers or config.currency != account.currency:
            continue
        rows = table_data(session, workspace, Filters(today, today, account=account.id, geo=profile.country, offer=profile.offer),
            level=entity.kind, limit=1_000_000, exact_ratios=True)["rows"]
        row = next((r for r in rows if r["id"] == entity.id and r["currency"] == account.currency and r["timezone"] == account.timezone), None)
        timely = bool(row and fresh(row["oldest_observation"], now, 1800))
        metrics = {k: row[k] if row else None for k in ("spend", "leads", "cpl", "roi")}
        scale = timely and metrics["cpl"] is not None and metrics["roi"] is not None and Decimal(metrics["cpl"]) <= config.target_cpl and Decimal(metrics["roi"]) >= config.target_roi
        stop = timely and metrics["spend"] is not None and metrics["leads"] == 0 and Decimal(metrics["spend"]) > config.stop_spend
        critical = timely and metrics["cpl"] is not None and Decimal(metrics["cpl"]) >= config.critical_cpl
        results.append({"id": profile.id, "revision": profile.revision, "config": config.model_dump(mode="json"),
            "fresh": timely, "metrics": metrics, "scale_candidate": bool(scale), "stop_candidate": bool(stop), "critical_cpl": bool(critical)})
    return sorted(results, key=lambda p: p["id"])


def check_budget(subject, change, target):
    for profile in subject.get("profiles", []):
        config = MediaProfile.model_validate(profile["config"])
        if target > config.max_adset_budget:
            raise ActionRejected("Budget exceeds the GEO/offer profile ceiling")
        if change > 0 and (change > config.scaling_percent or not profile["scale_candidate"]):
            raise ActionRejected("Scaling does not meet the GEO/offer profile targets or step")


def reserve_scaling(session, workspace, entity, action, value, current_budget, now):
    if action != "budget_set" or current_budget is None or value <= current_budget:
        return
    profiles = snapshot_profiles(session, workspace, entity, now)
    for profile in profiles:
        config = MediaProfile.model_validate(profile["config"])
        session.execute(insert_for(session, MediaBuyerCooldown.__table__).values(profile_id=profile["id"],
            entity_id=entity.id, last_queued_at=None).on_conflict_do_nothing(index_elements=["profile_id", "entity_id"]))
        row = session.scalar(select(MediaBuyerCooldown).where(MediaBuyerCooldown.profile_id == profile["id"],
            MediaBuyerCooldown.entity_id == entity.id).with_for_update())
        if row.last_queued_at and now < aware(row.last_queued_at)+timedelta(seconds=config.scaling_cooldown_seconds):
            raise ActionRejected("Scaling cooldown from the GEO/offer profile is active")
        row.last_queued_at = now
