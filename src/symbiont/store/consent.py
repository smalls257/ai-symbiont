"""The user's own-history consent, kept beside the store: one explicit setting, default withheld.

A missing file means no consent was given; a file that is not a consent record raises rather than
being read as either answer.
"""

import json
from pathlib import Path

from symbiont.records.privacy import OwnHistoryConsent

CONSENT_FILE = "consent.json"
SETTING = "own_history_to_spark"


class ConsentFileError(ValueError):
    """The consent file exists but does not hold a consent setting; the message names it."""


def read_consent(data_dir: Path) -> OwnHistoryConsent:
    """The recorded setting; WITHHELD when the user never set one."""
    path = data_dir / CONSENT_FILE
    if not path.exists():
        return OwnHistoryConsent.WITHHELD
    try:
        return OwnHistoryConsent(json.loads(path.read_text(encoding="utf-8"))[SETTING])
    except (ValueError, KeyError, TypeError) as exc:
        raise ConsentFileError(f"{path} does not hold a {SETTING} setting") from exc


def record_consent(data_dir: Path, consent: OwnHistoryConsent) -> Path:
    """Write the setting the user chose; returns the file written."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / CONSENT_FILE
    path.write_text(json.dumps({SETTING: consent.value}) + "\n", encoding="utf-8")
    return path
