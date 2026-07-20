# Frozen Held-out Protocol

Freeze ID: `method-freeze-v1`  
Freeze date: 2026-07-21  
State: protocol frozen; no held-out result has been inserted here.

## Separation

Development workloads are ResNet-50 and Transformer on the two existing
architectures and two existing package regimes. All algorithm choices,
measurement costs, margins, tolerances, and model-family rules are frozen
before opening the held-out matrix.

The pinned ThermoDSE revision has one interface inconsistency:
`GemmLayer.total_filter_size` omits the one-byte default used by its base and
Conv implementations. The driver applies only that default-argument
compatibility shim at runtime; the submodule remains byte-clean and pinned.

Held-out workloads are MobileNetV2, U-Net, YOLOv2, and GoogLeNet. The matrix is:

- 4 workloads;
- 3 previously unused architecture configurations;
- 3 package regimes;
- 36 candidate cases grouped into 12 ordered three-candidate DSE queries.

The architecture vectors are:

1. `7 3 1 1 0.0014 144 128 524288 144 128`
2. `4 5 2 1 0.0017 128 128 1048576 112 224`
3. `4 4 2 2 0.0026 160 208 1048576 208 128`

Package parameters are recorded in `experiments/packages.tsv`. All use
ambient 318.15 K, sink thickness 0.0069 m, and interface thickness 0.00002 m.

## Frozen methods

- DSOS exact batch optimum \(C^\star_{\rm batch}\);
- dual-price InfoCertGain greedy;
- uncertainty-width greedy;
- fair sequential fixed order with the same early-stop verifier;
- full-registry upper bound.

Every method sees the same action library, costs, tolerances, power polytope,
HotSpot family, and certification oracle.

Before an operator is admitted, the driver replays the frozen placed-power
vector directly through the same HotSpot model and compares it with
\(T_0+Rp\). Development froze a 0.01 K two-sided model-error band after the
first grid replay exposed a 0.00327 K numerical superposition residual. The
band is included in every safe/unsafe LP; held-out replay may reject it but
may not enlarge it.

## Primary evidence

- false certificates: exactly zero;
- exact cases: primal cost, MILP lower bound, relaxation bound, and gap;
- resolvable or proved non-identifiable: at least 8 of 12 queries;
- median DSOS cost at least 20% below full registry on resolvable queries;
- dual greedy is a positive headline only if it beats width in at least two
  package regimes and in geometric-mean cost.

Any failure, cross-model disagreement, timeout, or negative comparison is
archived unchanged. Post-freeze tuning requires a new freeze ID and a new
held-out split.

## Artifact contract

Outputs are TSV/CSV/NPZ/Markdown, plus:

- `ARTIFACTS.tsv` with role, path, producing command, Git SHA, and input SHA;
- `SHA256SUMS`;
- a compressed release archive and its SHA-256;
- HotSpot binary and submodule revision receipts.

The claim-grade execution must start from a fresh clone on moe-server:

```bash
git clone --recurse-submodules git@github.com:HaoningJiang-space/ThermoDSE-CertiTherm.git
cd ThermoDSE-CertiTherm
make bootstrap
make check
make heldout
```
