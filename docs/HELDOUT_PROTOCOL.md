# Frozen Held-out Protocol

Freeze ID: `method-freeze-v1`  
Freeze date: 2026-07-21  
State: protocol frozen; no held-out result has been inserted here.

## Separation

Development workloads are ResNet-50 and Transformer on three development
architectures and three package regimes (nine physical architecture ×
package operators). All algorithm choices,
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

The three held-out architecture vectors are disjoint from the development
set:

1. `5 6 1 2 0.0011 160 80 524288 144 128`
2. `8 1 8 1 0.0005 160 176 4194304 64 128`
3. `4 2 4 2 0.0005 176 160 4194304 208 128`

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

Candidate preference is not a static architecture label order. For each
workload, the driver records ThermoDSE latency, energy, and die yield, computes
\(\mathrm{EDYP}=\mathrm{latency}\times\mathrm{energy}/\mathrm{yield}\), and
sorts candidates by ascending measured EDYP before asking the thermal
feasibility query.

The common measurement registry contains module, chiplet, placement-region,
and post-route per-block reports at normalized costs 1, 2, 4, and 8. The
coarse input reveals total workload power only. Costs encode increasing EDA
stage/tool effort and are frozen in `experiments/measurements.tsv`; they are
not claimed as elapsed seconds or sensor dollars.

Before an operator is admitted, the driver replays every ResNet/Transformer
placed-power vector, a bounded-uniform vector, and three deterministic
bounded-simplex vectors directly through every registered HotSpot model and
compares them with \(T_0+Rp\). Every vector conserves total power and obeys
the registered content-derived upper bounds. Development froze a 0.01 K
two-sided model-error band
after the first grid replay exposed a 0.00327 K numerical superposition
residual. Every vector identity and digest is archived. The band is included
in every robust SAFE/REJECT LP; held-out replay may reject it but may not enlarge it.
This is a frozen empirical registered-domain error contract, not a formal
all-power floating-point error proof.

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

Each exact or heuristic query method has a frozen 1800-second wall-clock
budget. A timeout is recorded per method in `FAILURES.tsv`; other methods for
the same query still run, and no timeout is converted into a certificate.

## Artifact contract

Outputs are TSV/CSV/NPZ/Markdown, plus:

- `ARTIFACTS.tsv` with role, path, producing command, Git SHA, and input SHA;
- `SHA256SUMS`;
- final non-identifiability witness powers and direct HotSpot replay vectors;
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
