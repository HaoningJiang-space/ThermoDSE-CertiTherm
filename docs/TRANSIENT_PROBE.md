# Transient probe (NON-CLAIM, ~20 minutes)

A probe, not a gate — run under the process rule that while a framing is fresh the artefact
stays small until the question stops moving. It asks one thing: **is the transient mechanism
that the paper's Finding 3 depends on actually present in this package, or is thermal
inertia negligible here?**

If a short high-power burst dissipates faster than a workload phase, a steady-state
abstraction loses nothing and "steady-state ranking differs from transient ranking" cannot
happen. That would make the transient framing unsupportable before any IR is written.

## Measurement

moe-server, clean clone at `bc4ad86`, HotSpot built from the patched export, candidate
`arch_c` floorplan (181 units), `block` model, the pipeline's own `package.config` and
`example.materials`. A 20 W impulse on `eblk0` held for one 1 ms step, then idle.

| t (ms) | eblk0 (K) | above ambient |
| ---: | ---: | ---: |
| 0 | 323.22 | **+5.07** |
| 1 | 319.32 | +1.17 |
| 2 | 318.61 | +0.46 |
| 3 | 318.40 | +0.25 |
| 4 | 318.30 | +0.15 |
| 5 | 318.25 | +0.10 |
| 6 | 318.22 | +0.07 |
| 7 | 318.20 | +0.05 |
| 8 | 318.19 | +0.04 |

Ambient 318.15 K. `sampling_intvl` in the frozen config is `0.01`; the probe overrode it to
`0.001` to resolve the decay.

## What it establishes

**Thermal inertia is present and is not negligible at millisecond scale.** The decay is
clearly multi-exponential — roughly 77% of the excursion is gone after one millisecond (a
fast chip-level component) while a long tail persists at +0.04 K after eight (a slower
package-level component). A single time constant would not produce that shape.

**The mechanism Finding 3 needs exists here.** Over the nine steps the burst averages
20 W x 1/9 = 2.2 W, which is what a steady-state abstraction consuming time-averaged power
would see, while the instantaneous excursion is set by the 20 W peak. Two traces with equal
mean power and equal energy can therefore reach different peak temperatures — the premise
covered by `test_two_traces_can_share_a_mean_yet_differ_in_shape`.

## What it does NOT establish

- **Not that a decision actually flips.** A mechanism existing is not the same as a
  counterexample existing at the `THERMAL_LIMIT_K = 330.0` boundary with legal schedules of
  competing architectures. That is the experiment, and it is not this.
- One block, one candidate, one package, one impulse magnitude. Nothing about how the
  excursion scales with realistic concurrent power, nor about blocks with different
  neighbours.
- Nothing about whether real phase durations sit near these time constants. If workload
  phases are much longer than the slow component, steady state is recovered within each
  phase and the effect disappears. **That ratio is the next thing to measure**, and it
  decides whether transient belongs in the paper at all.
- The 5.07 K excursion is from a deliberately large 20 W single-block impulse chosen to make
  the decay legible, not from a physically-argued power level.

## Consequence

The transient operator is buildable and worth building: HotSpot's `-o` transient output
gives the impulse response directly, so the convolution kernel `G_k` can be extracted with
one run per block — the same order of cost as the existing steady operator build — and
`T_t = sum_{k<=t} G_{t-k} p_k` stays **linear in the phase powers**, which keeps the
collision oracle an LP and lets the entire certificate machinery carry over unchanged.

Next: measure real phase durations against these time constants before building the
operator.
