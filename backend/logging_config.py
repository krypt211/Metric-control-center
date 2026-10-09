"""Structured logs deliberately omit URLs, headers, payloads and exception text."""
import json
import logging
from datetime import datetime, timezone
class SafeFormatter(logging.Formatter):
    def format(self, record):
        data={"timestamp":datetime.now(timezone.utc).isoformat(),"service": "backend",
              "level":record.levelname,"event":record.getMessage() if record.name=="mcc.http" else "service_event"}
        for key in ("request_id","status","method","elapsed_ms","error_code"):
            if hasattr(record,key): data[key]=getattr(record,key)
        return json.dumps(data)
def configure():
    handler=logging.StreamHandler()
    handler.setFormatter(SafeFormatter())
    logger=logging.getLogger("mcc.http");logger.handlers=[handler];logger.setLevel(logging.INFO);logger.propagate=False
