# The impulse loop was one core of fifty-two, and the operator is bit-identical when it is not

RESULT 2026-08-03, `moe-server` (52 cores, two A800s idle at 0 MiB throughout).
NON-CLAIM: a scheduling change, verified against the serial build it replaces.

## What was wrong

`cell_certificate_run.cell_operator` builds a cell response matrix by issuing one HotSpot invocation
per block impulse — 187 to 243 of them — from a Python `for` loop. Each invocation is a separate
process, so the loop used **one core**, and five concurrent operator builds used five.

## Why it is a scheduling change and nothing else

Each impulse writes `{model_id}-{index}.ptrace`, `.steady` and `.grid`, so **no two calls touch a
shared file**; HotSpot is single-threaded C with a ~6 MB resident set and no shared process state; and
the binary is deterministic, so each call sees byte-identical inputs regardless of when it runs. A
thread pool suffices because the work is entirely inside `subprocess.run`, which releases the GIL.

## The check, on the one case that already had a serial answer

`transformer`/`arch_b`, 233 blocks, `grid128-avg`, the same pinned binary
(`sha256 b0040b3e…`):

| | serial | 16 workers |
| --- | ---: | ---: |
| operator build | **1333 s** | **89 s** (**15.0x**) |
| `response_k_per_w` (1, 16384, 233) | — | **bit-identical**, `max abs diff = 0.000e+00` |
| `ambient_k` (1, 16384) | — | **bit-identical**, `max abs diff = 0.000e+00` |
| `worst_case_max_cell_average_k` | 331.55835809624347 | 331.55835809624347 |
| `slack_k` | −1.618358096243469 | −1.618358096243469 |
| `argmax_cell` | 2341 | 2341 |
| `certified` | False | False |

Bit-identical, not "agrees to tolerance". That is the correct bar here: a scheduling change that
moved any digit would mean the calls were not independent after all.

## Why this is not a GPU question, and where the GPU does belong

HotSpot has **no GPU build**, and the endpoint has to be HotSpot's or the number is not comparable
with `CELL_ENDPOINT_RESULT.md` — substituting our own solver changes the object being certified, not
just the hardware. So the available parallelism here is process-level, and it was being left on the
floor.

The committed GPU path is `research/triangle/robustness/fem_batch_gpu.py`: one mesh and stiffness
assembly, one cuDSS factorisation, every right-hand side as one batch. That is the **FEM reference**,
a different model answering a different question. And `FEM_COST_IS_NOT_ON_THE_GPU.md` already measured
where its time goes — the GPU solve is **0.2 %** of the build, against 35 % mesh construction, 30 %
postprocess and 21 % RHS assembly. Both facts point the same way: move work *to* the GPU by default,
but measure before optimising the GPU itself.
