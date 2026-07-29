# RETRACTED: the per-cell decomposition is not a lower bound

**Every quantitative claim in the previous version of this file is withdrawn.** It reported a
certified lower bound on the real dev instance rising from the production path's 22.8-88.3 to
215, then 260.73, then 345.1, and finally 311.83 from a two-cell subset -- described as a 3.5x
to 13.7x improvement on the same quantity. **None of those are valid lower bounds.** The
argument they rested on is false.

## The argument, and why it fails

    a plan sufficient for the whole instance is sufficient for any SUBSET of its reject
    cells, because dropping cells only removes constraints, so C*(whole) >= C*(subset).

Dropping a cell does remove its REJECT option, which makes collisions rarer. It also removes
that cell's **SAFE row**, and SAFE is a CONJUNCTION -- every (model, point) must be below the
limit. So the SAFE set grows, which makes collisions commoner. The two effects run in opposite
directions and neither ordering survives.

`robust_safe_cell_rows` makes this concrete: a four-cell family yields four SAFE rows, a
one-cell restriction yields one. The restricted problem is not a relaxation of the whole
problem. It is a different problem.

## The counterexample

On the fixture in `CertiTherm/tests/test_cell_subset_bound.py`, the whole four-cell instance
certifies at **cost 0.0** and the same instance restricted to cell 0 costs **6.0**. A bound
that exceeds the quantity it bounds is not a bound.

## How it was caught, and why so late

By writing the test. The property was asserted in prose across four commits and used to
report five numbers before anything checked it. Every measurement was real -- the runs
happened, the numbers are what the solver returned -- but they were measurements of a
DIFFERENT problem than the one they were attributed to, and no amount of measuring the
restricted instances could reveal that. Only checking the inequality could.

The session had already established the habit that a claim needs a discriminating check
before it is reported. This claim was the exception, and it was the load-bearing one.

## What survives

  * `research/triangle/per_cell_bound_probe.py` and `cell_subset_bound_probe.py` still work
    and still measure real optima of the restricted instances. Those instances are simply not
    relaxations of the real one, so their optima say nothing about it.
  * The observation that restricted instances are far better conditioned -- 51.99 versus 4.57
    of bound per doubling of cuts -- is a real property of those instances, and may still be
    worth something if a decomposition with a valid direction can be found.
  * The tests in `CertiTherm/tests/test_cell_subset_bound.py` pin the counterexample so the
    argument cannot be reintroduced.

## What a correct decomposition would need

Any restriction used for a lower bound must RELAX the instance: keep the SAFE conjunction
intact while dropping REJECT options. Restricting the REJECT model/point set while retaining
every SAFE row is such a relaxation, and it is not what these probes did -- they used one
`ThermalFamily` for both roles, so the two moved together. Whether the machinery can express
the asymmetry is unexamined.

Until that exists, the certified lower bound on the real instance is what the production path
reports: **22.8 to 88.3** on the six dev queries.
