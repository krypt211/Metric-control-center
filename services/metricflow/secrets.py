from pathlib import Path
import re

from .errors import ConfigurationError


def validate_key(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"(?:mfk_|mf_live_)[\x21-\x7e]+", value) or "*" in value:
        raise ConfigurationError("Expected a complete MetricFlow API key beginning with mfk_ or mf_live_ (no spaces or masking characters)")
    return value


def read_key_file(path: str | None) -> str:
    if not path:
        raise ConfigurationError("API key file is not configured")
    try:
        value = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        raise ConfigurationError("Cannot read API key file") from None
    return validate_key(value)
