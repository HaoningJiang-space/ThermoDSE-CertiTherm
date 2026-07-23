"""Clean-room, exact-arithmetic verifier for the DSOS lower-bound certificate.

`verifier-first` (round-start review F15): before the v4 driver produces `[L, U]`
artifacts, this module defines what an *independent* checker accepts, so the driver
can only publish artifacts this verifier validates — not artifacts that merely
re-run the producer's own assumptions.

Scope of THIS module (the load-bearing lower-bound certificate):

  * `separator_set`   — the exact set S of actions that distinguish a witness pair.
  * `validate_witness`— the pair is a genuine robust-SAFE / robust-REJECT collision.
  * `validate_cut`    — a ledger cut equals EXACTLY the full separator set of its
                        witness (review F4), and no already-`selected` action lies
                        in it (review F5).
  * `exact_lagrangian`+ `lattice_lift` + `verify_lower_bound` — the certified `L`
                        in exact `Fraction`, valid for ANY non-negative dual, so it
                        never re-trusts a solver (review F8).

Deliberately INDEPENDENT of `synthesis.py`'s derivation path (review F7): it shares
no masking helper with the producer and recomputes every predicate from the raw
`ArchitectureSpec`-level arrays in exact rational arithmetic. A systematic bug in
the producer's `_cut_from_pair` therefore cannot certify itself here.

NOT yet in scope (next increment, tracked in docs/V4_DRIVER_ROUND_START.md):
  * the upper-bound certificate (`U` collision-free re-proof via Farkas / full
    re-run, review F8) — `verify_upper_bound` fails closed until that lands;
  * the on-disk canonical artifact schema + `RunReceipt` serialisation;
  * the atomic publisher.

Every check is fail-closed: an input that cannot be *established* (borderline
witness, ambiguous separator gap, malformed dual) raises `CertificateUnresolved`,
never a silent pass.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, FrozenSet, Sequence, Tuple

import numpy as np

if TYPE_CHECKING:
    from CertiTherm.core import MeasurementAction, PowerPolytope, ThermalFamily


class CertificateError(ValueError):
    """A certificate input is provably invalid (a real refutation)."""


class CertificateUnresolved(ValueError):
    """A certificate input cannot be established one way or the other (borderline
    witness, ambiguous gap, malformed dual) -> UNRESOLVED, never a fabricated pass."""


# --- exact rational helpers (float-derived, lossless) ---------------------

def _fr(value) -> Fraction:
    """Exact rational of a Python/NumPy float. `Fraction(float(x))` is lossless
    because IEEE-754 doubles are dyadic rationals; we never approximate an input."""
    return Fraction(float(value))


def _fr_vec(values: Sequence) -> Tuple[Fraction, ...]:
    return tuple(_fr(v) for v in values)


def _dot(a: Sequence[Fraction], b: Sequence[Fraction]) -> Fraction:
    if len(a) != len(b):
        raise CertificateError(f"dimension mismatch in dot: {len(a)} vs {len(b)}")
    return sum((x * y for x, y in zip(a, b)), Fraction(0))


# --- separator set (clean-room; no import of the producer's masking) ------

def separator_set(
    safe_w: Sequence[Fraction],
    unsafe_w: Sequence[Fraction],
    actions: Sequence["MeasurementAction"],
    guard: Fraction,
) -> FrozenSet[int]:
    """S = { a : |v_a · (safe_w - unsafe_w)| > tol_a }, computed exactly.

    Adding any a in S to the selected set would violate that action's
    indistinguishability constraint on this pair, so S is exactly the set of
    actions any of which separates the collision -> the necessary constraint is
    `sum_{a in S} x_a >= 1`.

    `guard >= 0` is an ambiguity band (review F6 / dissent): the witness is only
    feasible to the solver tolerance, so a gap `|v_a·Δ|` sitting within `guard` of
    `tol_a` cannot be robustly classified as separator-or-not; such a pair is
    `CertificateUnresolved`, not silently placed on either side."""
    delta = tuple(s - u for s, u in zip(safe_w, unsafe_w))
    members = []
    for index, action in enumerate(actions):
        vec = _fr_vec(action.vector)
        gap = abs(_dot(vec, delta))
        tol = _fr(action.tolerance)
        if gap > tol + guard:
            members.append(index)          # robustly a separator
        elif gap <= tol - guard:
            continue                       # robustly NOT a separator (|v·Δ| <= tol ok)
        else:
            raise CertificateUnresolved(
                f"action {action.action_id}: |v·Δ|={float(gap):.3e} within guard "
                f"of tol={float(tol):.3e}; separator membership not establishable")
    return frozenset(members)


# --- witness validity (robust SAFE / robust REJECT collision) -------------

def validate_witness(
    safe_w: Sequence[Fraction],
    unsafe_w: Sequence[Fraction],
    reject_model: int,
    reject_point: int,
    power: "PowerPolytope",
    thermal: "ThermalFamily",
    margin_k: float,
    slack: Fraction,
) -> None:
    """Fail closed unless (safe_w, unsafe_w) is a genuine collision for reject cell
    (reject_model, reject_point), checked in exact arithmetic with a declared
    `slack` (the run's feasibility tolerance, from the RunReceipt):

      * both worlds are power-feasible: `a_eq·p = b_eq` (|·| <= slack), `a_ub·p <=
        b_ub + slack`, `lower <= p <= upper` (+- slack);
      * safe_w is robustly SAFE: for EVERY (m,q),
        `response[m,q]·safe_w <= limit - margin - error[m] - ambient[m,q] + slack`;
      * unsafe_w is robustly REJECT at its cell:
        `response[rm,rp]·unsafe_w >= limit + margin - error[rm] - ambient[rm,rp] - slack`.

    The +-margin_k built into the SAFE/REJECT rows is what keeps the two sides
    robustly separated across the model-error band; `slack` only absorbs the LP's
    own residual. If `slack >= margin_k` the sides are not robustly established and
    the witness is `CertificateUnresolved`."""
    if slack < 0:
        raise CertificateError("slack must be non-negative")
    margin = _fr(margin_k)
    if slack >= margin and margin > 0:
        raise CertificateUnresolved(
            "feasibility slack >= margin: SAFE/REJECT sides not robustly separable")

    n = power.dimension
    for name, world in (("safe", safe_w), ("unsafe", unsafe_w)):
        if len(world) != n:
            raise CertificateError(f"{name} world has dim {len(world)} != {n}")
        _check_power_feasible(world, power, slack, name)

    resp = thermal.response_k_per_w
    ambient = thermal.ambient_k
    limit = _fr(thermal.limit_k)
    error = _fr_vec(thermal.error_k)
    n_models, n_points = resp.shape[0], resp.shape[1]
    if not (0 <= reject_model < n_models and 0 <= reject_point < n_points):
        raise CertificateError("reject cell out of range")

    # robust SAFE on safe_w for all (m, q)
    for m in range(n_models):
        for q in range(n_points):
            load = _dot(_fr_vec(resp[m, q]), safe_w)
            ceil_ = limit - margin - error[m] - _fr(ambient[m, q])
            if load > ceil_ + slack:
                raise CertificateError(
                    f"safe world violates SAFE ceiling at model {m} point {q}: "
                    f"{float(load):.4f} > {float(ceil_):.4f}")

    # robust REJECT on unsafe_w at the declared cell
    load = _dot(_fr_vec(resp[reject_model, reject_point]), unsafe_w)
    floor_ = limit + margin - error[reject_model] - _fr(ambient[reject_model, reject_point])
    if load < floor_ - slack:
        raise CertificateError(
            f"unsafe world does not reach REJECT floor at cell "
            f"({reject_model},{reject_point}): {float(load):.4f} < {float(floor_):.4f}")


def _check_power_feasible(
    world: Sequence[Fraction], power: "PowerPolytope", slack: Fraction, name: str
) -> None:
    lower = _fr_vec(power.lower_w)
    upper = _fr_vec(power.upper_w)
    for i, (p, lo, hi) in enumerate(zip(world, lower, upper)):
        if p < lo - slack or p > hi + slack:
            raise CertificateError(f"{name} world out of box at block {i}")
    a_eq = np.asarray(power.a_eq, dtype=float)
    b_eq = _fr_vec(power.b_eq)
    for r in range(a_eq.shape[0]):
        val = _dot(_fr_vec(a_eq[r]), world)
        if abs(val - b_eq[r]) > slack:
            raise CertificateError(f"{name} world violates equality row {r}")
    a_ub = np.asarray(power.a_ub, dtype=float)
    b_ub = _fr_vec(power.b_ub)
    for r in range(a_ub.shape[0]):
        val = _dot(_fr_vec(a_ub[r]), world)
        if val > b_ub[r] + slack:
            raise CertificateError(f"{name} world violates inequality row {r}")


# --- cut validity (exact equality with the full separator set) ------------

def validate_cut(
    cut_indices: FrozenSet[int],
    safe_w: Sequence[Fraction],
    unsafe_w: Sequence[Fraction],
    selected: FrozenSet[int],
    actions: Sequence["MeasurementAction"],
    guard: Fraction,
) -> FrozenSet[int]:
    """Fail closed unless `cut_indices` equals EXACTLY the full separator set of the
    witness. Soundness asymmetry (review F4, corrected):

      * a STRICT SUBSET S'' ⊂ S is UNSOUND -- a feasible cover may separate the
        pair by an action in S \\ S'', satisfying the true necessary constraint
        `Σ_{a∈S} x_a ≥ 1` while violating `Σ_{a∈S''} x_a ≥ 1`, so a subset cut can
        inflate the lower bound;
      * a SUPERSET S' ⊃ S is a VALID but weaker necessary constraint (every
        feasible cover hits S, hence S'); it cannot inflate the bound.

    We nonetheless require EXACT EQUALITY as a deliberately stronger, simpler
    ledger invariant (each cut is precisely its witness's separators), not because
    a superset is mathematically invalid. Exact equality also makes the ledger
    canonical and easy to replay.

    Also require the separator set to be disjoint from `selected` (review F5):
    recomputed WITHOUT any selected-subtraction, so a selected action that really
    does separate the pair reveals the witness is not a collision under `selected`
    and the cut is rejected as numerically invalid. Returns the validated set."""
    mask = separator_set(safe_w, unsafe_w, actions, guard)
    if mask & selected:
        raise CertificateError(
            f"separator set intersects selected actions {sorted(mask & selected)}: "
            f"witness is not a collision under the recorded selection")
    if not mask:
        raise CertificateError("empty separator set: pair is UNSYNTHESIZABLE, not a cut")
    if frozenset(cut_indices) != mask:
        extra = sorted(set(cut_indices) - mask)
        missing = sorted(mask - set(cut_indices))
        raise CertificateError(
            f"ledger cut != full separator set (extra={extra}, missing={missing}); "
            f"only exact equality is a valid necessary cut")
    return mask


# --- exact lower bound (weak duality, valid for any y >= 0) ----------------

def exact_lagrangian(
    costs: Sequence[Fraction],
    cut_rows: Sequence[Sequence[int]],
    dual: Sequence[Fraction],
) -> Fraction:
    """L(y) = sum_i y_i + sum_j min(0, c_j - sum_{i : j in cut_i} y_i), in exact
    Fraction. A valid lower bound on the min-cost hitting set for ANY y >= 0
    (Lagrangian relaxation of `C x >= 1`), so a mis-captured dual can only WEAKEN
    it, never make it exceed the true optimum (review F8). `cut_rows[i]` is the set
    of action indices covered by cut i."""
    m, n = len(cut_rows), len(costs)
    if len(dual) != m:
        raise CertificateError(f"dual length {len(dual)} != #cuts {m}")
    for y in dual:
        if y < 0:
            raise CertificateError("dual has a negative component; project to y>=0 first")
    loading = [Fraction(0)] * n
    for i, row in enumerate(cut_rows):
        yi = dual[i]
        for j in row:
            if not (0 <= j < n):
                raise CertificateError(f"cut {i} references action {j} out of range")
            loading[j] += yi
    total = sum(dual, Fraction(0))
    for j in range(n):
        residual = costs[j] - loading[j]
        if residual < 0:
            total += residual
    return total


def cost_lattice(costs: Sequence[Fraction]) -> Fraction:
    """Largest g > 0 with every cost an integer multiple of g (independent
    reimplementation; the driver's endpoints are lattice-lifted onto it). Exact:
    g = gcd(numerators scaled to a common denominator) / that denominator."""
    fracs = [Fraction(c) for c in costs if c != 0]
    if not fracs:
        raise CertificateError("cannot derive a lattice from all-zero costs")
    denom = 1
    for f in fracs:
        denom = denom * f.denominator // math.gcd(denom, f.denominator)
    g_num = 0
    for f in fracs:
        g_num = math.gcd(g_num, f.numerator * (denom // f.denominator))
    return Fraction(g_num, denom)


def lattice_lift(raw: Fraction, costs: Sequence[Fraction]) -> Fraction:
    """Round a weak-duality bound UP to the next lattice point (review F1/F11):
    since every feasible cover cost is a multiple of `g`, `ceil(raw/g)*g <= C*`
    remains valid and is >= raw."""
    g = cost_lattice(costs)
    q = Fraction(raw) / g                       # exact ceil of the rational ratio
    steps = q.numerator // q.denominator + (1 if q.numerator % q.denominator else 0)
    return Fraction(steps) * g


@dataclass(frozen=True)
class LowerCertificate:
    """The verified lower endpoint and how it was obtained."""
    raw_lagrangian: Fraction
    lattice: Fraction
    L: Fraction


def verify_lower_bound(
    costs: Sequence[Fraction],
    cut_rows: Sequence[Sequence[int]],
    dual: Sequence[Fraction],
) -> LowerCertificate:
    """Compute and return the exact certified lower bound from validated cuts and a
    recorded non-negative dual. Every cut in `cut_rows` MUST already have passed
    `validate_cut`; this function does not re-trust the producer for cut validity,
    only for having supplied validated rows."""
    raw = exact_lagrangian(costs, cut_rows, dual)
    L = lattice_lift(raw, costs)
    return LowerCertificate(raw_lagrangian=raw, lattice=cost_lattice(costs), L=L)


# --- upper bound (deferred, fail-closed) ----------------------------------

def verify_upper_bound(*_args, **_kwargs):
    """NOT YET IMPLEMENTED. `U` is a valid upper bound only if the cover is proved
    collision-free; replaying stored oracle statuses is not a proof (review F8).
    The next increment adds either a full re-run or per-cell Farkas certificates.
    Until then this fails closed rather than pretend."""
    raise CertificateUnresolved(
        "upper-bound verification (collision-free re-proof) not yet implemented")
