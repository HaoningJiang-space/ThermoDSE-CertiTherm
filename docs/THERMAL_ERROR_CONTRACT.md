# Frozen HotSpot Linearization Error Contract

Freeze ID: `method-freeze-v1`  
Registered two-sided bound: 0.01 K

For every architecture × package operator and registered HotSpot model, the
driver compares a direct steady-state replay \(T_{\rm direct}(p)\) with the
impulse superposition \(T_0+Rp\):

\[
 \epsilon(p)=\lVert T_{\rm direct}(p)-(T_0+Rp)\rVert_\infty .
\]

The development gate uses both ResNet-50 and Transformer placed-power
vectors. For each it also registers a bounded-uniform vector and three
deterministic bounded-simplex vectors with seeds 17, 23, and 41. All vectors
conserve captured total power and obey the same content-derived per-block
upper bounds as the DSE query; their numeric SHA-256 digests and per-model
residuals are written to each operator's calibration TSV.

An operator is admitted only if every replay obeys
\(\epsilon(p)\le0.01\) K. The full calibration table is written before a
rejection, so negative evidence is not lost. The same two-sided band is
propagated into every safe/unsafe LP constraint.

Held-out vectors test this bound but cannot enlarge it. Any violation rejects
the operator and leaves the affected query `UNRESOLVED`. The 0.01 K value is
therefore a frozen empirical registered-domain engineering contract. It is
not presented as a formal error bound over every real-valued power vector or
every HotSpot configuration.

For an `UNSYNTHESIZABLE` result, the final continuous-LP witness powers are
also replayed directly through their named HotSpot models. Full direct and
predicted temperature vectors are archived. If any witness residual exceeds
0.01 K, the paper-facing query status is downgraded to `UNRESOLVED`.
