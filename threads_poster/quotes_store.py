import json
import logging
import os
import random
import tempfile
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)


class QuotesStoreError(RuntimeError):
    """Raised when reading or writing the quotes file fails."""


@dataclass(frozen=True)
class QuoteEntry:
    image: str
    caption: str


def _is_valid_entry(entry: object) -> bool:
    return isinstance(entry, dict) and bool(entry.get("image")) and bool(entry.get("caption"))


class QuotesStore:
    def __init__(self, path: str) -> None:
        self.path = path

    def _load(self) -> List[dict]:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError as exc:
            raise QuotesStoreError(f"Quotes file not found: {self.path}") from exc
        except json.JSONDecodeError as exc:
            raise QuotesStoreError(f"Quotes file is not valid JSON: {exc}") from exc

        if not isinstance(data, list):
            raise QuotesStoreError("Quotes file must contain a JSON array")

        return data

    def pick_random(self) -> QuoteEntry:
        entries = self._load()
        valid = [e for e in entries if _is_valid_entry(e)]
        invalid_count = len(entries) - len(valid)

        if invalid_count:
            logger.warning(
                "Skipping %d quote entr%s with missing image or caption",
                invalid_count,
                "y" if invalid_count == 1 else "ies",
            )

        if not valid:
            raise QuotesStoreError(
                "Quotes file has no usable entries (need both image and caption)"
            )

        chosen = random.choice(valid)
        return QuoteEntry(image=chosen["image"], caption=chosen["caption"])

    def remove(self, entry: QuoteEntry) -> None:
        entries = self._load()
        remaining = [
            e for e in entries
            if not (isinstance(e, dict) and e.get("image") == entry.image)
        ]

        if len(remaining) == len(entries):
            # Nothing matched — entry already gone, treat as no-op
            return

        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        try:
            fd, tmp_path = tempfile.mkstemp(
                prefix=".quotes-", suffix=".json.tmp", dir=directory
            )
        except OSError as exc:
            raise QuotesStoreError(f"Failed to create temp file: {exc}") from exc

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(remaining, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self.path)
        except Exception as exc:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise QuotesStoreError(f"Failed to update quotes file: {exc}") from exc
