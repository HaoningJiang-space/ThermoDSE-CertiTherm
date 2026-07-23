"""Frozen instance receipt binding a v4-driver run to the exact instance it ran on.

The 2026-07-23 audit's load-bearing finding (§1): the strong-cut `[L, U]` result
is stitched by hand from two programs, neither of which binds the candidate,
registry, operators, or tolerances it actually ran against. A number that cannot
be traced to a frozen instance is exploration signal, not a certificate.

`InstanceReceipt` is the single digest every downstream v4 artifact (cut ledger,
`[L, U]` interval) must carry. It follows the `rte` receipt-chaining idea and the
`CertiTherm.core` frozen-dataclass convention: build it once from the frozen
instance, embed `receipt.digest` in each artifact, and `verify()` on reload. A
tampered registry, a reordered action list, a different operator export, or a
changed tolerance all change the digest, so a stale or foreign artifact fails
closed instead of being silently trusted.

Deliberately self-contained: it does NOT import `CertiTherm.experiments` (which
pulls the whole HotSpot/thermal chain). The only heavy dependency is numpy.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, Optional, Sequence, Tuple

import numpy as np

if TYPE_CHECKING:  # avoid import cost / cycles at runtime
    from CertiTherm.core import MeasurementAction, PowerPolytope, ThermalFamily

RECEIPT_SCHEMA_VERSION = 1


class InstanceReceiptError(ValueError):
    """Raised when a receipt cannot be built or does not match its instance."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InstanceReceiptError(message)


def _sha256_file(path: Path) -> str:
    """Streaming SHA-256 of a file (operator NPZ exports can be large)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_array(digest: "hashlib._Hash", name: str, array: np.ndarray) -> None:
    """Fold a numpy array into `digest` deterministically and portably.

    Endianness matters (dissent #1): the same float bytes must hash identically on
    any host, so the array is normalised to little-endian float64 and its shape is
    hashed alongside the bytes (so a reshape is never a silent no-op). Two review
    hardenings (F7): signed zero is normalised (`-0.0 -> +0.0`, semantically equal
    for power/response arrays) and the shape is encoded as fixed-width binary
    rather than `repr`, so no textual ambiguity can collide two shapes."""
    arr = np.ascontiguousarray(array, dtype="<f8")
    if not np.all(np.isfinite(arr)):
        raise InstanceReceiptError(f"{name} contains non-finite values")
    arr = arr + 0.0  # -0.0 -> +0.0; finite non-zero and (excluded) inf unchanged
    digest.update(name.encode("utf-8"))
    digest.update(np.asarray(arr.shape, dtype="<i8").tobytes())
    digest.update(arr.tobytes())


def _registry_digest(actions: Sequence["MeasurementAction"]) -> str:
    """SHA-256 over the ordered registry: id, cost, tolerance, and vector of every
    action, in list order. Reordering the registry changes the digest, because the
    action-ID ordering is itself part of the instance identity (audit §1)."""
    digest = hashlib.sha256()
    digest.update(f"n={len(actions)}".encode("utf-8"))
    for index, action in enumerate(actions):
        digest.update(f"|{index}:{action.action_id}".encode("utf-8"))
        # exact float encoding, not JSON's lossy decimal, for cost/tolerance
        digest.update(f":cost={float(action.cost).hex()}".encode("utf-8"))
        digest.update(f":tol={float(action.tolerance).hex()}".encode("utf-8"))
        _hash_array(digest, "vec", np.asarray(action.vector, dtype=float))
    return digest.hexdigest()


def _power_digest(power: "PowerPolytope") -> str:
    """SHA-256 over every constraint array of the admissible-power polytope. Two
    instances with the same registry but different power sets are different
    problems and must not share a digest."""
    digest = hashlib.sha256()
    for name in ("lower_w", "upper_w", "a_eq", "b_eq", "a_ub", "b_ub"):
        _hash_array(digest, name, np.asarray(getattr(power, name), dtype=float))
    return digest.hexdigest()


def _thermal_digest(thermal: "ThermalFamily") -> str:
    """SHA-256 over the SEMANTIC thermal family the oracle actually consumes, not
    just the operator file (audit F4): the operator NPZ SHA binds the *source*, but
    a loader change or an in-memory transform could feed the oracle a different
    family with identical file bytes. Hash ordered model_ids, response, ambient,
    limit, per-model error, and per-model provenance."""
    digest = hashlib.sha256()
    digest.update(("|".join(thermal.model_ids)).encode("utf-8"))
    _hash_array(digest, "response", np.asarray(thermal.response_k_per_w, dtype=float))
    _hash_array(digest, "ambient", np.asarray(thermal.ambient_k, dtype=float))
    digest.update(f"limit={float(thermal.limit_k).hex()}".encode("utf-8"))
    _hash_array(digest, "error", np.asarray(thermal.error_k, dtype=float))
    digest.update(("prov|" + "|".join(thermal.provenance_sha256)).encode("utf-8"))
    return digest.hexdigest()


def _git_revision(root: Path) -> Optional[str]:
    """Repo HEAD, or None if `root` is not a git worktree (the receipt still binds
    the instance content; git SHA is provenance, not the integrity anchor)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root), check=True, capture_output=True, text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    return out.stdout.strip() or None


@dataclass(frozen=True)
class InstanceReceipt:
    """Tamper-evident identity of one frozen v4 candidate instance.

    `digest` is a pure function of every field below; any downstream artifact that
    embeds it can be re-validated against a freshly rebuilt instance with
    `verify()`. Build with `InstanceReceipt.build(...)`, never by hand."""

    schema_version: int
    candidate_id: str
    workload: str
    cand_index: int
    n_actions: int
    action_ids: Tuple[str, ...]
    registry_digest: str
    power_digest: str
    thermal_digest: str
    operator_sha256: str
    margin_k: float
    feas_tol: float
    full_registry_cost: float
    git_sha: Optional[str]

    def __post_init__(self) -> None:
        _require(self.schema_version == RECEIPT_SCHEMA_VERSION,
                 f"unsupported receipt schema {self.schema_version}")
        _require(bool(self.candidate_id) and bool(self.workload),
                 "candidate_id and workload are required")
        _require(self.cand_index >= 0, "cand_index must be non-negative")
        _require(self.n_actions == len(self.action_ids),
                 "n_actions must match action_ids length")
        _require(len(set(self.action_ids)) == len(self.action_ids),
                 "action_ids must be unique")
        _require(np.isfinite(self.margin_k) and self.margin_k >= 0,
                 "margin_k must be finite and non-negative")
        _require(np.isfinite(self.feas_tol) and self.feas_tol >= 0,
                 "feas_tol must be finite and non-negative")
        _require(np.isfinite(self.full_registry_cost) and self.full_registry_cost > 0,
                 "full_registry_cost must be finite and positive")

    # -- construction -----------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        candidate_id: str,
        workload: str,
        cand_index: int,
        actions: Sequence["MeasurementAction"],
        power: "PowerPolytope",
        thermal: "ThermalFamily",
        operator_path: Path,
        margin_k: float,
        feas_tol: float,
        repo_root: Optional[Path] = None,
    ) -> "InstanceReceipt":
        _require(len(actions) > 0, "cannot build a receipt over an empty registry")
        operator_path = Path(operator_path)
        _require(operator_path.is_file(),
                 f"operator export not found: {operator_path}")
        full_cost = float(sum(float(a.cost) for a in actions))
        return cls(
            schema_version=RECEIPT_SCHEMA_VERSION,
            candidate_id=candidate_id,
            workload=workload,
            cand_index=int(cand_index),
            n_actions=len(actions),
            action_ids=tuple(a.action_id for a in actions),
            registry_digest=_registry_digest(actions),
            power_digest=_power_digest(power),
            thermal_digest=_thermal_digest(thermal),
            operator_sha256=_sha256_file(operator_path),
            margin_k=float(margin_k),
            feas_tol=float(feas_tol),
            full_registry_cost=full_cost,
            git_sha=_git_revision(repo_root) if repo_root is not None else None,
        )

    # -- identity ---------------------------------------------------------

    @property
    def digest(self) -> str:
        """SHA-256 over the canonical serialisation of every field. Floats are
        encoded via `.hex()` (exact, not JSON's lossy decimal) so the digest is
        bit-reproducible. `git_sha` is included: a claim-grade run pins its
        revision, and a receipt is not equal across a code change even if the
        instance content is identical."""
        payload = {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "workload": self.workload,
            "cand_index": self.cand_index,
            "n_actions": self.n_actions,
            "action_ids": list(self.action_ids),
            "registry_digest": self.registry_digest,
            "power_digest": self.power_digest,
            "thermal_digest": self.thermal_digest,
            "operator_sha256": self.operator_sha256,
            "margin_k": float(self.margin_k).hex(),
            "feas_tol": float(self.feas_tol).hex(),
            "full_registry_cost": float(self.full_registry_cost).hex(),
            "git_sha": self.git_sha,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    # -- validation on reload --------------------------------------------

    def verify(
        self,
        *,
        actions: Sequence["MeasurementAction"],
        power: "PowerPolytope",
        thermal: "ThermalFamily",
        operator_path: Path,
        margin_k: float,
        feas_tol: float,
    ) -> None:
        """Fail closed if the LIVE instance does not reproduce this receipt. Raises
        `InstanceReceiptError` on the FIRST mismatch, naming it, so a foreign or
        drifted instance cannot masquerade as this one. The caller must treat any
        raise as UNRESOLVED, never continue.

        Checks every semantic field that can move `[L, U]` (audit F3/F4): the
        registry, the power polytope, the *semantic* thermal family (not merely the
        operator file), the operator source SHA, AND the run tolerances `margin_k`
        / `feas_tol` — a changed margin or feasibility tolerance alters collisions
        and the interval while leaving the instance math untouched, so it must be
        checked against the live values here, not just stored."""
        _require(tuple(a.action_id for a in actions) == self.action_ids,
                 "action-ID ordering does not match the receipt")
        _require(_registry_digest(actions) == self.registry_digest,
                 "registry digest mismatch (vectors/costs/tolerances differ)")
        _require(_power_digest(power) == self.power_digest,
                 "power-polytope digest mismatch")
        _require(_thermal_digest(thermal) == self.thermal_digest,
                 "thermal-family digest mismatch (loader or transform drift)")
        operator_path = Path(operator_path)
        _require(operator_path.is_file(),
                 f"operator export not found on reload: {operator_path}")
        _require(_sha256_file(operator_path) == self.operator_sha256,
                 "operator export SHA-256 mismatch")
        _require(float(margin_k).hex() == float(self.margin_k).hex(),
                 "margin_k mismatch: live run uses a different margin than the receipt")
        _require(float(feas_tol).hex() == float(self.feas_tol).hex(),
                 "feas_tol mismatch: live run uses a different tolerance than the receipt")

    # -- serialisation ----------------------------------------------------

    def to_dict(self) -> dict:
        """Plain-dict form for embedding in a JSON artifact. `digest` is included
        so a reader can check it without reconstructing the dataclass."""
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "workload": self.workload,
            "cand_index": self.cand_index,
            "n_actions": self.n_actions,
            "action_ids": list(self.action_ids),
            "registry_digest": self.registry_digest,
            "power_digest": self.power_digest,
            "thermal_digest": self.thermal_digest,
            "operator_sha256": self.operator_sha256,
            "margin_k": self.margin_k,
            "feas_tol": self.feas_tol,
            "full_registry_cost": self.full_registry_cost,
            "git_sha": self.git_sha,
            "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> "InstanceReceipt":
        """Rebuild from `to_dict()` output and fail closed unless the embedded
        `digest` is present, well-formed, and matches the reconstructed fields.

        The digest is MANDATORY (audit F2): an earlier version skipped the check
        when `digest` was absent or `None`, so simply deleting the key bypassed
        tamper detection. Now a missing / non-hex / mismatched digest all raise, so
        neither a stripped nor a hand-edited artifact can be reloaded."""
        receipt = cls(
            schema_version=int(data["schema_version"]),
            candidate_id=str(data["candidate_id"]),
            workload=str(data["workload"]),
            cand_index=int(data["cand_index"]),
            n_actions=int(data["n_actions"]),
            action_ids=tuple(str(a) for a in data["action_ids"]),
            registry_digest=str(data["registry_digest"]),
            power_digest=str(data["power_digest"]),
            thermal_digest=str(data["thermal_digest"]),
            operator_sha256=str(data["operator_sha256"]),
            margin_k=float(data["margin_k"]),
            feas_tol=float(data["feas_tol"]),
            full_registry_cost=float(data["full_registry_cost"]),
            git_sha=(str(data["git_sha"]) if data.get("git_sha") is not None else None),
        )
        embedded = data.get("digest")
        _require(
            isinstance(embedded, str) and len(embedded) == 64
            and all(c in "0123456789abcdef" for c in embedded),
            "artifact is missing a valid 64-char hex digest")
        _require(embedded == receipt.digest,
                 "embedded digest does not match reconstructed receipt fields")
        return receipt
