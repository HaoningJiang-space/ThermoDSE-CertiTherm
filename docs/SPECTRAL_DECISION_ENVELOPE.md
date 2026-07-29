# Spectral Decision Envelope

## Purpose

Frequency is a physical representation of thermal observability, not a new
simulator claim. For one candidate, stack every registered HotSpot model and
thermal-point response into

\[
  \mathcal R=[R_1;\ldots;R_M],\qquad
  \mathcal R^\top\mathcal R=\Phi\Sigma^2\Phi^\top .
\]

The columns of \(\Phi\) are joint thermal input modes. On a homogeneous
rectangular layered package these modes approach the familiar cosine/Fourier
basis. On a finite heterogeneous chiplet package, extracting them from the
provenance-bound Green operators avoids an unjustified shift-invariance
assumption.

Using DCT, Green functions, or convolution for fast chip thermal simulation is
established prior art, including the
[ASP-DAC 2005 DCT method](https://experts.umn.edu/en/publications/fast-computation-of-the-temperature-distribution-in-vlsi-chips-us),
[Power Blurring](https://ieeexplore.ieee.org/document/6729105), and
[generalized integral transforms](https://ir.lib.nycu.edu.tw/handle/11536/7332?locale=en).
The research question here is different: which obtainable EDA observations
cover the thermally amplified modes needed to identify an ordered DSE
decision?

## Certified truncation envelope

For rank \(K\), define

\[
 R_{m,K}=R_m\Phi_K\Phi_K^\top .
\]

Energy retention alone cannot support a peak-temperature claim. The driver
therefore computes the registered-domain peak tail

\[
 E_K=\max_{m,r,p\in P}
 \left|e_r^\top(R_m-R_{m,K})p\right| .
\]

Every inner maximum and minimum is solved exactly for the content-bounded
box-with-total power polytope; a general polytope falls back to LP. The audit
includes rank zero, logarithmic intermediate ranks, and full rank. Full rank
must have residual below \(10^{-7}\) K. DSOS currently continues to use the
full operator, so no truncation error is silently added to the frozen 0.01 K
physical replay bound.

## Observation fibers in mode space

For selected obtainable actions \(A_S\), two powers remain confusable when

\[
  A_S(p-q)=A_S\Phi(\hat p-\hat q)=0.
\]

The corresponding unobserved thermal radius is

\[
 \Gamma(S)=
 \max_{p,q\in P:\ A_Sp=A_Sq}
 \max_{m,r}|e_r^\top R_m(p-q)|.
\]

`measurement_registry.tsv` records each real module, chiplet, region, and
post-route action's single-channel leverage over \(\Sigma^2\). This is an
interpretability statistic, not a certificate or selection objective. The
exact DSOS certificate still comes from cross-decision fiber separation.

### Proposition: orthogonal invariance

For any orthogonal \(\Phi\), substituting \(p=\Phi\hat p\) preserves power-set
membership after coordinate transformation, action equality, thermal state,
and action cost. Hence the minimum registered-library DSOS cost and every
confusability edge are invariant under the spectral change of coordinates.

The spectrum can expose low-dimensional structure and justify a certified
reduction, but it cannot improve an exact cost merely by renaming the
coordinates.

### Measured, 2026-07-29: it does not expose enough structure here

The "could justify a certified reduction" clause above was an open possibility. On the dev
split it is now a measured negative, from `artifacts/dev/spectral_envelopes.tsv`
(transformer / default / arch_b, 227 blocks, 3 models):

| rank | retained operator energy | certified peak tail bound |
| ---: | ---: | ---: |
| 8 | 0.427 | 72.4 K |
| 32 | 0.757 | 66.3 K |
| 64 | 0.909 | 49.9 K |
| 128 | 0.983 | **20.7 K** |
| 227 | 1.000 | 1.9e-13 K |

Retaining 98.3% of the operator energy still leaves a worst-case peak error of 20.7 K,
against a 0.01 K model-error contract and sub-kelvin decision margins. The energy is
compressible; the PEAK is not. That is the physics, not a weakness of the bound: peak
temperature is a worst-case functional over a polytope, so an adversarial power map may put
all of its mass on the 1.7% of energy the truncation discarded, and diffusion smoothing does
not prevent that.

Two consequences worth recording, because both are easy to assume otherwise:

  * A spectral or otherwise coarse-resolution certificate is not available for this decision.
    Per-block resolution is forced by the worst case, not by a conservative formulation.
  * The dev split's certified plans buying roughly 80% of the per-block post-route library
    (U = 4174 of a 5250 full registry, at 8.0 per post-route action against 2.0 for a
    whole-chiplet read covering 112 blocks) are therefore **not** obviously an artifact of a
    weak search. The open question is the size of the certified interval -- L was 22.8-88.3
    against that U -- not whether a cheap coarse plan was overlooked.

## Unrestricted information limit

An idealized rank-\(k\) linear observation lower bound is related to

\[
 e_k^\star=
 \inf_{\operatorname{rank}(A)=k}
 \sup_{\delta p\in(P-P)\cap\ker A}
 \|\mathcal R\delta p\|_\infty .
\]

This constrained width separates two claims:

- DSOS is the exact minimum cost for the finite registered EDA channel library;
- \(e_k^\star\) concerns arbitrary linear measurements and is not yet solved by
  the implementation.

Leading singular modes are optimal for an unconstrained Euclidean
input/output norm, not automatically for a content polytope and peak norm.
They may provide bounds, but must not be labeled the unrestricted theoretical
limit without a matching proof.

## Artifact contract

- `spectral_envelopes.tsv`: rank, retained operator energy, and certified
  peak-tail bound for every workload/candidate/package;
- `measurement_registry.tsv`: real channel class, cost, support, and thermal
  spectral leverage;
- `results.tsv`: full-operator DSOS result; spectral approximation never
  replaces the claim-grade oracle.
