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
