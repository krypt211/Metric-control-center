"""Conservative mapping discovery from READ responses, never synthetic metrics."""
from datetime import date
import re
from zoneinfo import ZoneInfo

from services.sync.schema import InsightSchema, SchemaError, field, page_items


def list_mapping(payload):
    candidates = []
    def visit(value, path, depth=0):
        if depth > 3:
            return
        if isinstance(value, list) and all(isinstance(row, dict) for row in value):
            candidates.append((path or "$", value))
        elif isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, (dict, list)):
                    visit(child, f"{path}.{key}" if path else key, depth+1)
    visit(payload, "")
    if len(candidates) != 1:
        raise SchemaError("Response list is ambiguous. A verified config/metricflow-schema.json is required")
    path, rows = candidates[0]
    # Live MetricFlow /insights uses pagination.cursor as the NEXT cursor.
    if isinstance(payload, dict) and isinstance(payload.get("pagination"), dict) and "cursor" in payload["pagination"] and "has_more" in payload["pagination"]:
        pagination = {"mode": "cursor", "next_cursor_path": "pagination.cursor", "cursor_parameter": "cursor", "has_more_path": "pagination.has_more", "page_count_path": "meta.total"}
        page_items(payload, path, pagination)
        return path, rows, pagination
    # Catalog contract: meta.total is the full length and limit/offset are null.
    if isinstance(payload, dict) and isinstance(payload.get("meta"), dict) and {"total", "limit", "offset"} <= payload["meta"].keys():
        pagination = {"mode": "none", "total_path": "meta.total", "require_null_paths": ["meta.limit", "meta.offset"]}
        page_items(payload, path, pagination)
        return path, rows, pagination
    paging = []
    for cursor_path in ("next_cursor", "pagination.next_cursor", "meta.next_cursor", "paging.next_cursor"):
        try:
            cursor = field(payload, cursor_path)
        except SchemaError:
            continue
        if cursor is not None and (not isinstance(cursor, str) or not cursor):
            raise SchemaError("Unsupported cursor format")
        paging.append({"mode": "cursor", "next_cursor_path": cursor_path, "cursor_parameter": "cursor"})
    if len(paging) > 1:
        raise SchemaError("Pagination is ambiguous")
    if paging:
        return path, rows, paging[0]
    # Only explicit completion proves that a single page is complete.
    confirmations = []
    for complete_path, expected in (("complete", True), ("pagination.complete", True), ("meta.complete", True), ("has_more", False), ("pagination.has_more", False), ("meta.has_more", False)):
        try:
            value = field(payload, complete_path)
        except SchemaError:
            continue
        if not isinstance(value, bool) or value is not expected:
            raise SchemaError("Single-page completion is not confirmed")
        confirmations.append((complete_path, expected))
    if not confirmations:
        raise SchemaError("Pagination is not explicit. A verified schema is required; no truncated data was imported")
    complete_path, complete_value = confirmations[0]
    return path, rows, {"mode": "none", "complete_path": complete_path, "complete_value": complete_value}



def choose(rows, paths, *, required=False):
    found = []
    for path in paths:
        try:
            values = [field(row, path) for row in rows]
        except SchemaError:
            continue
        if any(value is not None for value in values):
            found.append(path)
    if len(found) > 1:
        raise SchemaError("Field mapping is ambiguous; a verified schema is required")
    if not found and required:
        raise SchemaError("A required field is absent; a verified schema is required")
    return found[0] if found else None


def catalog_mapping(payload):
    items_path, rows, pagination = list_mapping(payload)
    if not rows:
        raise SchemaError("No ad accounts returned by MetricFlow")
    fields = {
        "account_id": choose(rows, ("ad_account_id", "account_id", "id", "account.id"), required=True),
        "currency": choose(rows, ("currency", "account.currency"), required=True),
        "timezone": choose(rows, ("timezone", "timezone_name", "account.timezone"), required=True),
        "account_name": choose(rows, ("name", "account_name", "account.name")),
        "account_status": choose(rows, ("status",)),
    }
    config = {"items_path": items_path, "pagination": pagination, "fields": {k: v for k, v in fields.items() if v}}
    for row in rows:
        account_values(row, config)
    return config, rows


def account_values(row, config):
    values = {name: field(row, path) for name, path in config["fields"].items()}
    if not re.fullmatch(r"act_[0-9]+", str(values.get("account_id"))):
        raise SchemaError("Account ID must be the explicit act_ ID")
    if not re.fullmatch(r"[A-Z]{3}", str(values.get("currency"))):
        raise SchemaError("Account currency is missing or invalid")
    try:
        ZoneInfo(values["timezone"])
    except (KeyError, TypeError, ValueError):
        raise SchemaError("Account timezone is missing or invalid") from None
    status = values.get("account_status")
    if status is not None and (not isinstance(status, str) or not status):
        raise SchemaError("Invalid account status")
    values.setdefault("account_name", None)
    return values


def discover(accounts_payload, insights_payload):
    catalog, accounts = catalog_mapping(accounts_payload)
    items_path, rows, pagination = list_mapping(insights_payload)
    if not rows:
        raise SchemaError("No insight rows for the requested period. Schema cannot be verified yet")
    aliases = {
        "account_id": ("ad_account_id", "account_id", "account.id", "ad_account.id"),
        "entity_id": ("ad_id", "entity.id", "ad.id"),
        "entity_name": ("ad_name", "entity.name", "ad.name"),
        "date": ("date", "day", "date_start"),
        "date_end": ("date_stop",),
        "currency": ("currency", "account.currency", "ad_account.currency"),
        "timezone": ("timezone", "timezone_name", "account.timezone", "ad_account.timezone"),
        "campaign_id": ("campaign_id", "campaign.id"),
        "campaign_name": ("campaign_name", "campaign.name"),
        "adset_id": ("adset_id", "ad_set_id", "adset.id", "ad_set.id"),
        "adset_name": ("adset_name", "ad_set_name", "adset.name", "ad_set.name"),
        "creative_id": ("creative_id", "creative.id", "adcreative_id"),
        "creative_name": ("creative_name", "creative.name"),
        "media_url": ("media_url", "creative.media_url", "creative.thumbnail_url"),
        "buyer": ("buyer", "labels.buyer"), "offer": ("offer", "labels.offer"),
        "tracker_campaign": ("tracker_campaign", "labels.tracker_campaign"),
    }
    for metric in ("spend", "impressions", "clicks", "conversions", "leads", "sales", "revenue", "reach", "frequency"):
        aliases[metric] = (metric, f"metrics.{metric}", f"stats.{metric}")
    aliases["sales"] = ("sales", "purchases", "metrics.sales", "stats.sales")
    aliases["status"] = ("effective_status",)
    required = {"account_id", "entity_id", "date", "campaign_id", "adset_id", "spend", "impressions", "clicks"}
    paths = {name: choose(rows, options, required=name in required) for name, options in aliases.items()}
    fields = {name: path for name, path in paths.items() if path}
    fields.setdefault("currency", "_context.currency")
    fields.setdefault("timezone", "_context.timezone")
    fields["account_name"] = "_context.account_name"
    # A tracker is mapped only with an explicit presence flag and currency.
    present = choose(rows, ("has_tracker", "tracker_present"))
    if present:
        fields["tracker_present"] = present
        for name in ("currency", "clicks", "conversions", "leads", "sales", "revenue"):
            path = choose(rows, (f"tracker.{name}", f"tracker_{name}"))
            if path:
                fields["tracker_"+name] = path
    config = {"entity_level": "ad", "items_path": items_path, "pagination": pagination, "query": {"level": "ad", "limit": 100}, "fields": fields, "account_catalog": catalog}
    if pagination.get("has_more_path") == "pagination.has_more":
        # These metadata fields were verified specifically on the live endpoint.
        for metadata in ("meta.data_updated_at", "meta.date_range.from", "meta.date_range.to"):
            if not isinstance(field(insights_payload, metadata), str):
                raise SchemaError("Live insights metadata is incomplete")
        config["snapshot_version_path"] = "meta.data_updated_at"
        config["range_paths"] = {"start": "meta.date_range.from", "end": "meta.date_range.to"}
    mapped = {str(account_values(row, catalog)["account_id"]): account_values(row, catalog) for row in accounts}
    schema = InsightSchema(config)
    for row in rows:
        aid = str(field(row, fields["account_id"]))
        if aid not in mapped:
            raise SchemaError("Insight account is absent from the catalog page; configure schema after verifying catalog pagination")
        schema.row({**row, "_context": mapped[aid]})
    return config
