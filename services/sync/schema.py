"""Explicit schema adapter: no assumptions about unverified upstream fields."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class SchemaError(ValueError):
    pass


def field(value: Any, path: str) -> Any:
    if path == "$":
        return value
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise SchemaError("Configured field is missing")
        value = value[part]
    return value


def decimal_value(value: Any, *, count: bool = False) -> Decimal | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise SchemaError("Boolean is not a metric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise SchemaError("Metric is not numeric") from None
    if not result.is_finite() or result < 0:
        raise SchemaError("Metric must be finite and nonnegative")
    if count:
        if result != result.to_integral_value() or result > 2**63 - 1:
            raise SchemaError("Counter must be a nonnegative 64-bit integer")
        return int(result)
    if result >= Decimal("1e16") or result.as_tuple().exponent < -8:
        raise SchemaError("Money exceeds NUMERIC(24,8) precision")
    return result


def page_items(payload: Any, items_path: str, pagination: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """Validate the endpoint-specific completeness evidence on every response."""
    items = field(payload, items_path)
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise SchemaError("Configured items field is not an array of objects")
    if pagination.get("complete_path") and field(payload, pagination["complete_path"]) is not pagination["complete_value"]:
        raise SchemaError("Single-page completion is no longer confirmed")
    for path in pagination.get("require_null_paths", []):
        if field(payload, path) is not None:
            raise SchemaError("Single-page endpoint started reporting a limit/offset; reverify pagination")
    # On catalog endpoints this is the full total; on /insights it is a page count.
    for name in ("total_path", "page_count_path"):
        if pagination.get(name):
            total = field(payload, pagination[name])
            if isinstance(total, bool) or not isinstance(total, int) or total < 0 or total != len(items):
                raise SchemaError("Response row count does not match the verified contract")
    cursor = None
    if pagination["mode"] == "cursor":
        cursor = field(payload, pagination["next_cursor_path"])
        if cursor is not None and (not isinstance(cursor, str) or not cursor):
            raise SchemaError("Next cursor must be a nonempty string or null")
        if pagination.get("has_more_path"):
            more = field(payload, pagination["has_more_path"])
            if not isinstance(more, bool) or more != (cursor is not None):
                raise SchemaError("Cursor and has_more disagree; completeness is unknown")
            if more and not items:
                raise SchemaError("An empty page cannot claim more rows")
    elif pagination["mode"] != "none":
        raise SchemaError("Unsupported pagination mode")
    return items, cursor


@dataclass(frozen=True)
class ParentRow:
    kind: str
    external_id: str
    name: str | None
    state: dict[str, Any]


@dataclass(frozen=True)
class NormalizedRow:
    account_id: str
    account_name: str | None
    currency: str
    timezone: str
    entity_id: str
    entity_name: str | None
    kind: str
    day: date
    metrics: dict[str, Decimal | int | None]
    tracker_present: bool | None
    tracker: dict[str, Decimal | int | None] | None
    tracker_currency: str | None
    state: dict[str, Any]
    parents: list[ParentRow]
    creative_id: str | None
    creative_name: str | None
    media_url: str | None
    labels: dict[str, str | None]
    dimensions: dict[str, str] | None
    raw: dict[str, Any]


class InsightSchema:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.paths = config["fields"]
        self.kind = config["entity_level"]
        if self.kind not in ("campaign", "adset", "ad"):
            raise SchemaError("Unsupported entity level")
        self.items_path = config["items_path"]
        self.pagination = config["pagination"]
        if config.get("endpoint", "insights") not in ("insights", "breakdowns"):
            raise SchemaError("Unsupported sync endpoint")
        if config.get("endpoint") == "breakdowns" and not config.get("dimension_fields"):
            raise SchemaError("Breakdowns require explicit dimension mappings")
        if self.pagination["mode"] not in ("cursor", "none"):
            raise SchemaError("Configure pagination as cursor or explicitly none")
        if self.pagination["mode"] == "cursor":
            for key in ("next_cursor_path", "cursor_parameter"):
                if not isinstance(self.pagination.get(key), str) or not self.pagination[key]:
                    raise SchemaError("Cursor pagination configuration is incomplete")
        required = {"account_id", "currency", "timezone", "entity_id", "date"}
        if not required <= self.paths.keys():
            raise SchemaError("Required field mappings are missing")
        if not isinstance(config.get("query", {}), dict):
            raise SchemaError("Query parameters must be an object")
        if any(k in config.get("query", {}) for k in ("from", "to")):
            raise SchemaError("Date filters are controlled by the Sync Engine")

    @classmethod
    def load(cls, path: str) -> "InsightSchema":
        return cls(json.loads(Path(path).read_text(encoding="utf-8-sig")))

    def value(self, row: dict[str, Any], name: str) -> Any:
        path = self.paths.get(name)
        # Unconfigured fields remain unknown, never coerced to zero.
        return field(row, path) if path else None

    def page(self, payload: Any) -> tuple[list[dict[str, Any]], str | None]:
        items, cursor = page_items(payload, self.items_path, self.pagination)
        if self.config.get("complete_path") and field(payload, self.config["complete_path"]) is not True:
            raise SchemaError("Upstream reports an incomplete response")
        return items, cursor

    def row(self, raw: dict[str, Any]) -> NormalizedRow:
        account_id, entity_id = str(self.value(raw, "account_id")), str(self.value(raw, "entity_id"))
        if not re.fullmatch(r"act_[0-9]+", account_id) or not re.fullmatch(r"[0-9]+", entity_id):
            raise SchemaError("Invalid provider account or entity ID")
        currency, timezone = self.value(raw, "currency"), self.value(raw, "timezone")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            raise SchemaError("Currency must be an explicit three-letter code")
        try:
            ZoneInfo(timezone)
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            raise SchemaError("Timezone must be an explicit IANA timezone") from None
        try:
            day = date.fromisoformat(self.value(raw, "date"))
        except (TypeError, ValueError):
            raise SchemaError("Invalid metric date") from None
        if "date_end" in self.paths and self.value(raw, "date_end") != day.isoformat():
            raise SchemaError("Daily insights cannot contain a multi-day aggregate")
        metrics = {
            name: decimal_value(self.value(raw, name), count=name not in ("spend", "revenue"))
            for name in ("spend", "impressions", "clicks", "conversions", "leads", "sales", "revenue")
        }
        metrics["reach"] = decimal_value(self.value(raw, "reach"), count=True)
        metrics["frequency"] = decimal_value(self.value(raw, "frequency"))
        tracker = None
        tracker_currency = None
        present = None
        if "tracker_present" in self.paths:
            present = self.value(raw, "tracker_present")
            if not isinstance(present, bool):
                raise SchemaError("Tracker presence must be explicit true/false")
            if present:
                tracker_currency = self.value(raw, "tracker_currency")
                if not isinstance(tracker_currency, str) or not re.fullmatch(r"[A-Z]{3}", tracker_currency):
                    raise SchemaError("Tracker currency must be explicit")
                tracker = {
                    name: decimal_value(self.value(raw, "tracker_" + name), count=name != "revenue")
                    for name in ("clicks", "conversions", "leads", "sales", "revenue")
                }
        state = {}
        for name in ("status", "budget", "bid"):
            if name in self.paths:
                value = self.value(raw, name)
                if name != "status":
                    value = decimal_value(value)
                elif value is not None and not isinstance(value, str):
                    raise SchemaError("Status must be a string or null")
                state[name] = value
        parents = []
        for kind in (("campaign", "adset") if self.kind == "ad" else ("campaign",) if self.kind == "adset" else ()):
            if kind + "_id" in self.paths:
                external = str(self.value(raw, kind + "_id"))
                if not re.fullmatch(r"[0-9]+", external):
                    raise SchemaError("Invalid parent ID")
                parent_state = {}
                for name in ("status", "budget", "bid"):
                    if kind + "_" + name in self.paths:
                        value = self.value(raw, kind + "_" + name)
                        parent_state[name] = decimal_value(value) if name != "status" else value
                parents.append(ParentRow(kind, external, self.value(raw, kind + "_name"), parent_state))
        creative_id = self.value(raw, "creative_id")
        if creative_id is not None:
            creative_id = str(creative_id)
            if not re.fullmatch(r"[0-9]+", creative_id):
                raise SchemaError("Invalid creative ID")
        labels = {name: self.value(raw, name) for name in ("buyer", "offer", "tracker_campaign") if name in self.paths}
        if any(value is not None and not isinstance(value, str) for value in labels.values()):
            raise SchemaError("Labels must be strings or null")
        dimensions = None
        if self.config.get("dimension_fields"):
            dimensions = {name: field(raw, path) for name, path in self.config["dimension_fields"].items()}
            if any(not isinstance(value, str) or not value for value in dimensions.values()):
                raise SchemaError("Breakdown dimensions must be nonempty strings")
        return NormalizedRow(
            account_id, self.value(raw, "account_name"), currency, timezone,
            entity_id, self.value(raw, "entity_name"), self.kind, day,
            metrics, present, tracker, tracker_currency, state, parents,
            creative_id, self.value(raw, "creative_name"), self.value(raw, "media_url"), labels, dimensions, raw,
        )
