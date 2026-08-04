"""One shape for "a certified case", so a consumer reads a field instead of guessing a name.

## The defect this fixes, and it already cost something

Across the drivers, the certified peak is written under **four** names -- `certified_peak_k`,
`worst_case_max_cell_average_k`, `thermodse_mapping_certified_k`, and inside a `curve` entry keyed by
span -- and the nominal peak under three. `limit_parametric_disagreement` therefore harvested by
trying names in order, which is a heuristic, and a heuristic over names **fails silently**: adding one
more fallback took its population from **46 cases to 230**. Four fifths of the evidence had been
invisible, and nothing said so.

The fix is not another fallback. It is that a driver **declares** its cases under one key, and the
reader takes them or reports that it could not.

## The contract

* `CASE_RECORD_KEY` is the one array name. A payload carrying it is self-describing.
* `CaseRecord` is frozen and validated: a certified peak below its nominal is a contradiction (the
  envelope contains the nominal point), and a non-finite peak is `UNRESOLVED`, not a number.
* `read_cases()` returns `(records, legacy, skipped)`. **Legacy files still parse** -- the tree is
  full of them -- but they are counted separately and the count is printed, so the silent loss
  becomes a reported one. A file with neither shape is skipped and counted, never assumed empty.

`CertiTherm/result_schema.py` does exactly this for the production pipeline; this is the same idea
for the research drivers, which had grown their own dialects.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

CASE_RECORD_KEY = "certified_cases"

# The dialects already on disk, newest name first. Kept ONLY so historical files still read, and
# every hit through this table is counted as legacy rather than silently accepted.
_LEGACY_CERTIFIED = ("certified_peak_k", "worst_case_max_cell_average_k",
                     "thermodse_mapping_certified_k")
_LEGACY_NOMINAL = ("nominal_peak_k", "thermodse_mapping_nominal_k")


@dataclass(frozen=True)
class CaseRecord:
    """One design, one envelope, one pair of peaks -- the unit every consumer actually wants."""

    case: str
    nominal_peak_k: float
    certified_peak_k: float
    span: float = 0.30
    ceiling_k: float = float("nan")
    model: str = ""
    edyp: float = float("nan")
    source: str = ""

    def __post_init__(self) -> None:
        for name in ("nominal_peak_k", "certified_peak_k"):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"{self.case}: {name} is {value!r}; UNRESOLVED, not a number")
        if self.certified_peak_k < self.nominal_peak_k - 1e-9:
            raise ValueError(
                f"{self.case}: certified {self.certified_peak_k!r} is below nominal "
                f"{self.nominal_peak_k!r}. The envelope contains the nominal point, so its supremum "
                "cannot be lower; the two numbers came from different objects."
            )
        if not self.case.strip():
            raise ValueError("a case record must name what it is about")

    @property
    def uplift_k(self) -> float:
        """What the envelope adds over the point evaluation the field reports."""
        return self.certified_peak_k - self.nominal_peak_k

    def as_dict(self) -> dict:
        return {"case": self.case, "span": self.span, "model": self.model,
                "nominal_peak_k": self.nominal_peak_k,
                "certified_peak_k": self.certified_peak_k,
                "ceiling_k": self.ceiling_k, "edyp": self.edyp, "source": self.source}


def attach(payload: dict, records) -> dict:
    """Put the declared cases into a driver's own payload under the one key."""
    payload[CASE_RECORD_KEY] = [r.as_dict() for r in records]
    return payload


def _legacy_from(record: dict, span: float, source: str):
    """One `CaseRecord` from a pre-contract dict, or `None`. Never guesses beyond the named table."""
    nominal = next((record[k] for k in _LEGACY_NOMINAL if record.get(k) is not None), None)
    certified = next((record[k] for k in _LEGACY_CERTIFIED if record.get(k) is not None), None)
    if certified is None and isinstance(record.get("curve"), list):
        # The radius driver stores the certified peak per span. Matched EXACTLY, because reading a
        # different span here would mix envelopes across a population without saying so.
        for point in record["curve"]:
            if isinstance(point, dict) and abs(float(point.get("span", -1)) - span) < 1e-12:
                certified = point.get("peak_k")
                break
    if nominal is None or certified is None:
        return None
    label = str(record.get("architecture_id") or record.get("case") or record.get("trace")
                or record.get("tag") or source)
    try:
        return CaseRecord(case=f"{source}/{label}", nominal_peak_k=float(nominal),
                          certified_peak_k=float(certified), span=span,
                          ceiling_k=float(record.get("ceiling_k", float("nan"))),
                          edyp=float(record.get("edyp", float("nan"))), source=source)
    except ValueError:
        return None


def read_cases(root: Path, *, span: float = 0.30):
    """`(records, legacy_count, skipped_files)` over every JSON under `root`.

    A file that declares `CASE_RECORD_KEY` is read exactly. One that does not is read through the
    named legacy table and counted. One that yields nothing is counted as skipped -- **never treated
    as an empty result**, which is how the four-fifths loss stayed invisible.
    """
    records, legacy, skipped = [], 0, []
    for path in sorted(Path(root).rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            skipped.append(str(path))
            continue
        if isinstance(payload, dict) and isinstance(payload.get(CASE_RECORD_KEY), list):
            # A DECLARATION IS AUTHORITATIVE AND EXCLUSIVE. The legacy tables must not also run over
            # the same payload: a driver that declares its cases AND still writes the old key would
            # otherwise have every case counted twice -- once exactly, once as legacy -- which makes
            # the legacy counter, the one number that measures migration progress, stop falling as
            # drivers migrate. It is the metric lying about its own subject.
            for entry in payload[CASE_RECORD_KEY]:
                records.append(CaseRecord(**entry))
            continue
        found = 0
        candidates = [payload] if isinstance(payload, dict) else list(payload)
        for key in ("all", "rows", "table"):
            if isinstance(payload, dict) and isinstance(payload.get(key), list):
                candidates += [r for r in payload[key] if isinstance(r, dict)]
        for record in candidates:
            if not isinstance(record, dict):
                continue
            got = _legacy_from(record, span, path.parent.name)
            if got is not None:
                records.append(got)
                found += 1
        legacy += found
        if not found:
            skipped.append(str(path))
    return records, legacy, skipped
