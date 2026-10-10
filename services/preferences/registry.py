"""Shared UI metadata; does not define provider contracts or statistical formulas."""
from functools import lru_cache
import json
from pathlib import Path
from decimal import Decimal, InvalidOperation

@lru_cache
def registry():
    return json.loads((Path(__file__).resolve().parents[2] / "frontend/lib/metric-registry.json").read_text(encoding="utf-8"))

def metrics(scope):
    if scope not in registry()["scopes"]:
        raise ValueError("INVALID_SCOPE")
    return {k:v for k,v in registry()["metrics"].items() if scope in v["scopes"]}

def system_presets(scope):
    allowed=metrics(scope)
    out=[]
    for key,item in registry()["systems"].items():
        preset_keys = registry()["manual_default"] if scope == "manual_ad" and key == "basic" else registry()["rules_default"] if scope == "rule_ad" and key == "basic" else registry()["economics_default"] if scope.startswith("eco_") and key == "basic" else item["keys"]
        keys=["name"]+[k for k in preset_keys if k in allowed and k!="name"]
        sorting={"key":"spend" if "spend" in keys else "clicks" if "clicks" in keys else "name","direction":"desc" if "spend" in keys or "clicks" in keys else "asc"}
        out.append({"id":"system:"+key,"name":item["name"],"scope":scope,"system":True,"version":0,
            "config":{"version":1,"columns":[{"key":k,"width":allowed[k]["defaultWidth"]} for k in keys],"widths":{},"sorting":sorting}})
    return out

def validate_config(config,scope):
    allowed=metrics(scope)
    cols=config["columns"]
    keys=[c["key"] for c in cols]
    if not keys or keys[0]!="name" or len(keys)!=len(set(keys)) or len(keys)>len(allowed):
        raise ValueError("INVALID_COLUMN_ORDER")
    for col in cols:
        spec=allowed.get(col["key"])
        if not spec:raise ValueError("INVALID_METRIC")
        if not spec["minWidth"]<=col["width"]<=spec["maxWidth"]:raise ValueError("INVALID_COLUMN_WIDTH")
    for key,width in config["widths"].items():
        spec=allowed.get(key)
        if not spec or not spec["minWidth"]<=width<=spec["maxWidth"]:raise ValueError("INVALID_COLUMN_WIDTH")
    if config["sorting"] and config["sorting"]["key"] not in allowed:raise ValueError("INVALID_SORT_KEY")
    return config

def normalize_config(config,scope):
    """Registry additions never replace a saved selection; retired keys are ignored on read."""
    allowed=metrics(scope)
    seen=set();columns=[]
    for col in config.get("columns",[]):
        key=col.get("key")
        if key not in allowed or key in seen:continue
        seen.add(key);spec=allowed[key]
        columns.append({"key":key,"width":max(spec["minWidth"],min(spec["maxWidth"],col.get("width",spec["defaultWidth"])))})
    name=next((c for c in columns if c["key"]=="name"),{"key":"name","width":allowed["name"]["defaultWidth"]})
    sorting=config.get("sorting")
    return {"version":1,"columns":[name]+[c for c in columns if c["key"]!="name"],
        "widths":{k:max(allowed[k]["minWidth"],min(allowed[k]["maxWidth"],v)) for k,v in config.get("widths",{}).items() if k in allowed},
        "sorting":sorting if sorting and sorting.get("key") in allowed else None}

def sort_rows(rows,key,direction,scope):
    allowed=metrics(scope)
    if key not in allowed or direction not in ("asc","desc"):raise ValueError("INVALID_SORT")
    numeric=allowed[key]["unit"]!="text"
    def value(row):
        v=row.get(key)
        if v is None:return None
        if not numeric:return str(v).casefold()
        try:
            v=Decimal(str(v))
            return v if v.is_finite() else None
        except (InvalidOperation,ValueError):return None
    # Stable identity tie-break makes pagination deterministic in either direction.
    rows=sorted(rows,key=lambda r:(str(r.get("id","")),str(r.get("currency","")),str(r.get("timezone",""))))
    present=[r for r in rows if value(r) is not None]
    missing=[r for r in rows if value(r) is None]
    return sorted(present,key=value,reverse=direction=="desc")+missing
