# FlexForge: Executable Machine-Failure Recovery Demo

**Status: Proof of concept (not peer reviewed).** This is runnable scheduling code, not a simulation claim or screenshot-only mockup. The demo models a small *flexible job shop* with three machines and five two-stage jobs. At time `t=8` machine 0 fails for 8 time units. Work completed before the breakdown and unaffected operations already in progress remain fixed. An interrupted operation on the failed machine restarts from scratch; unstarted work may be reassigned to alternative eligible machines.

## Run in 60 seconds

Python 3.10+ is required.

```bash
python flexforge_demo.py --engine heuristic
```

This **stdlib-only** command exports a verified, feasible EDD recovery schedule to `output/` without external dependencies.

To enable the actual OR-Tools CP-SAT solver:

```bash
python -m pip install -r requirements.txt
python flexforge_demo.py --engine cpsat --seconds 2
```

To run the 100-seed reproducible evaluation:

```bash
python flexforge_demo.py --engine cpsat --seconds 2 --bench 100 --out benchmark_output
```

Outputs:
- `baseline.csv` -- pre-failure dispatching plan
- `recovery_edd.csv` -- feasible EDD recovery baseline
- `recovery_selected.csv` -- CP-SAT result or explicit EDD fallback
- `summary.json` -- failure configuration, frozen work, solver status, KPI measurements
- `benchmark_output/benchmark.csv` -- per-seed comparison when `--bench` is used

## Solver specification

The CP-SAT model uses alternative-machine optional intervals, exactly-one assignment per operation, precedence constraints, machine `NoOverlap`, a fixed downtime interval for the failed machine, and frozen pre-failure tasks.

Objective (integer time units):

`min 10 * Σ_j weight_j * max(0, completion_j - due_j) + makespan + 2 * Σ_(unfrozen ops) |new_start - old_start|`

The `max_time_in_seconds=2` solver **budget is not a guarantee of optimality or an absolute end-to-end wall-clock latency bound**. If CP-SAT cannot return a feasible solution within its solve budget, the code uses the EDD recovery plan, whose feasibility is checked. The heuristic-only run **does not claim CP-SAT was executed**. We do **not** claim a 15% performance gain without measured results.

## Reproduction and integrity

- All inputs are generated deterministically by `random.Random(seed)`.
- Every returned schedule is asserted to obey operation precedence, machine nonoverlap, eligible alternatives, frozen work, and downtime.
- `solver` and `status` fields distinguish OR-Tools results from heuristic fallback.
- Benchmark variants use the same seed and frozen pre-failure schedule.
- No external factory telemetry, neural network, or physical equipment is used.

## Scope and next steps

This prototype demonstrates a **working scheduling mechanism**. It is not yet an autonomous digital twin or a 3D manufacturing platform. Next development milestones are an event-stream interface, React Three Fiber visualization, more realistic repair-time distributions, additional constraints, and statistically sound paired benchmarks.

CP-SAT modeling approach follows Google's public [Flexible Job Shop](https://github.com/google/or-tools/blob/stable/examples/python/flexible_job_shop_sat.py) implementation and [Scheduling documentation](https://github.com/google/or-tools/blob/stable/ortools/sat/docs/scheduling.md).

## Verified here (2026-11-20)

The dependency-free heuristic demo and its four unit tests passed. Across 100 deterministic seeds, both EDD and FIFO recovery schedules passed machine-assignment, precedence, frozen-task, and downtime validity checks. A machine-0 operation is interrupted and reassigned in the default demonstration. See the generated `demo_output/*.csv`, `summary.json`, and Gantt preview images. **The CP-SAT engine could not be executed in this environment because `ortools` could not be installed; its results must be verified with the explicit `--engine cpsat` command.**

Generate optional schedule images with:

```bash
python -m pip install matplotlib
python plot_demo.py
```