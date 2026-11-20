#!/usr/bin/env python3
"""FlexForge proof-of-work: reproducible failure-triggered flexible job-shop rescheduling.

Run with only Python 3.10+: python flexforge_demo.py --engine heuristic
For CP-SAT: pip install ortools && python flexforge_demo.py --engine cpsat

The heuristic demo is tested without OR-Tools; CP-SAT needs OR-Tools installed.
This is a scheduling proof-of-concept, not a fully developed smart factory.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Operation:
    alternatives: tuple[tuple[int, int], ...]  # (machine_id, integer processing_time)


@dataclass(frozen=True)
class Job:
    due: int
    weight: int
    operations: tuple[Operation, ...]


@dataclass(frozen=True)
class Slot:
    job: int
    op: int
    machine: int
    start: int
    end: int


MACHINES = 3
HORIZON = 160
FAIL_TIME = 8
DOWN_TIME = 8


def make_jobs(seed: int) -> tuple[Job, ...]:
    """Small but nontrivial flexible job shop; deterministic perturbations by seed."""
    rng = random.Random(seed)
    raw = [
        (21, 3, [[(0, 5), (1, 7)], [(1, 5), (2, 6)]]),
        (22, 3, [[(1, 6), (0, 6)], [(0, 6), (2, 6)]]),
        (29, 2, [[(2, 5), (1, 6)], [(0, 7), (2, 7)]]),
        (31, 2, [[(0, 5), (2, 7)], [(1, 6), (2, 6)]]),
        (36, 1, [[(1, 5), (2, 6)], [(0, 7), (2, 5)]]),
    ]
    jobs = []
    for due, weight, ops in raw:
        due += rng.randint(-2, 2)
        new_ops = []
        for alternatives in ops:
            new_ops.append(Operation(tuple((m, max(2, duration + rng.randint(-1, 1)))
                                           for m, duration in alternatives)))
        jobs.append(Job(due, weight, tuple(new_ops)))
    return tuple(jobs)


def is_conflict(start: int, end: int, reservations: list[tuple[int, int]]) -> bool:
    return any(start < other_end and other_start < end for other_start, other_end in reservations)


def earliest_slot(ready: int, duration: int, reservations: list[tuple[int, int]]) -> int:
    start = ready
    for begin, finish in sorted(reservations):
        if start + duration <= begin:
            break
        if start < finish and begin < start + duration:
            start = finish
    return start


def build_fixed(prior: list[Slot], failed_machine: int, failure: int):
    """Freeze completed work and unaffected work already in progress.

    A task interrupted on failed_machine must restart fully: nonpreemptive policy.
    """
    fixed: dict[tuple[int, int], Slot] = {}
    interrupted = []
    for slot in prior:
        if slot.end <= failure:
            fixed[(slot.job, slot.op)] = slot
        elif slot.start < failure < slot.end:
            if slot.machine == failed_machine:
                interrupted.append((slot.job, slot.op))
            else:
                fixed[(slot.job, slot.op)] = slot
    return fixed, interrupted


def greedy_schedule(
    jobs: tuple[Job, ...],
    fixed: dict[tuple[int, int], Slot] | None = None,
    failure: int = 0,
    failed_machine: int | None = None,
    recovery_time: int = 0,
    mode: str = "edd",
) -> list[Slot]:
    """Feasible deterministic dispatching heuristic; does not claim optimality."""
    fixed = fixed or {}
    schedule = dict(fixed)
    reserved: dict[int, list[tuple[int, int]]] = {m: [] for m in range(MACHINES)}
    for slot in fixed.values():
        reserved[slot.machine].append((slot.start, slot.end))
    if failed_machine is not None:
        reserved[failed_machine].append((failure, failure + recovery_time))
    job_order = sorted(range(len(jobs)), key=lambda j: (jobs[j].due, j)) if mode == "edd" else list(range(len(jobs)))
    for j in job_order:
        prev_end = 0
        for k, op in enumerate(jobs[j].operations):
            key = (j, k)
            if key in fixed:
                prev_end = fixed[key].end
                continue
            ready = max(prev_end, failure)
            options = []
            for machine, duration in op.alternatives:
                start = earliest_slot(ready, duration, reserved[machine])
                options.append((start + duration, start, machine, duration))
            _, start, machine, duration = min(options)
            slot = Slot(j, k, machine, start, start + duration)
            schedule[key] = slot
            reserved[machine].append((slot.start, slot.end))
            prev_end = slot.end
    return sorted(schedule.values(), key=lambda s: (s.start, s.machine, s.job, s.op))


def validate_schedule(jobs: tuple[Job, ...], schedule: list[Slot],
                      fixed: dict[tuple[int, int], Slot] | None = None,
                      failure: int = 0, failed_machine: int | None = None,
                      recovery_time: int = 0) -> None:
    expected = {(j, k) for j, job in enumerate(jobs) for k in range(len(job.operations))}
    slots = {(s.job, s.op): s for s in schedule}
    assert len(schedule) == len(expected) and set(slots) == expected, "Missing/duplicate operations"
    for key, slot in slots.items():
        j, k = key
        assert slot.start >= 0 and slot.end <= HORIZON, (key, "outside horizon")
        assert (slot.machine, slot.end-slot.start) in jobs[j].operations[k].alternatives, (key, "invalid machine or processing time")
        if k:
            assert slot.start >= slots[(j, k-1)].end, (key, "precedence violated")
        if fixed and key in fixed:
            assert slot == fixed[key], (key, "frozen interval changed")
        elif failed_machine is not None:
            assert slot.start >= failure, (key, "rescheduled task starts in the past")
        if failed_machine is not None and slot.machine == failed_machine:
            assert not (slot.start < failure + recovery_time and failure < slot.end), "Downtime overlap"
    for m in range(MACHINES):
        machine_slots = sorted([s for s in schedule if s.machine == m], key=lambda s: s.start)
        for left, right in zip(machine_slots, machine_slots[1:]):
            assert left.end <= right.start, (m, left, right)


def metrics(jobs: tuple[Job, ...], schedule: list[Slot]) -> dict[str, int]:
    finish = {j: max(s.end for s in schedule if s.job == j) for j in range(len(jobs))}
    return {
        "makespan": max(finish.values()),
        "weighted_tardiness": sum(job.weight * max(0, finish[j] - job.due) for j, job in enumerate(jobs)),
        "completed_jobs": len(jobs),
    }


def cpsat_schedule(jobs: tuple[Job, ...], previous: list[Slot],
                   fixed: dict[tuple[int, int], Slot], failed_machine: int,
                   failure: int, recovery_time: int, seconds: float) -> tuple[list[Slot] | None, str]:
    """CP-SAT model; optional machine intervals, freeze, machine downtime, penalize perturbation.

    Returns None if no feasible result within time budget. Uses official OR-Tools CP-SAT API.
    """
    try:
        from ortools.sat.python import cp_model
    except ImportError as exc:
        raise RuntimeError("OR-Tools is not installed. Run: python -m pip install ortools") from exc
    model = cp_model.CpModel()
    machine_intervals = {m: [] for m in range(MACHINES)}
    machine_intervals[failed_machine].append(
        model.new_fixed_size_interval_var(failure, recovery_time, "machine_downtime")
    )
    starts, ends, chosen = {}, {}, {}
    previous_by_key = {(s.job, s.op): s for s in previous}
    # A feasible EDD schedule provides valid CP-SAT hints (including machine reassignments).
    warm_schedule = greedy_schedule(jobs, fixed, failure, failed_machine, recovery_time, mode="edd")
    warm_by_key = {(s.job, s.op): s for s in warm_schedule}
    validate_schedule(jobs, warm_schedule, fixed, failure, failed_machine, recovery_time)
    shift_penalty = []
    for j, job in enumerate(jobs):
        for k, operation in enumerate(job.operations):
            key = (j, k)
            start = model.new_int_var(0, HORIZON, f"start_{j}_{k}")
            end = model.new_int_var(0, HORIZON, f"end_{j}_{k}")
            starts[key], ends[key] = start, end
            present_list = []
            for alt_id, (machine, duration) in enumerate(operation.alternatives):
                present = model.new_bool_var(f"use_{j}_{k}_{alt_id}")
                interval = model.new_optional_interval_var(
                    start, duration, end, present, f"task_{j}_{k}_{alt_id}")
                machine_intervals[machine].append(interval)
                present_list.append(present)
                chosen[(j, k, alt_id)] = present
                if key in fixed:
                    model.add(present == int(machine == fixed[key].machine))
                else:
                    model.add_hint(present, int(machine == warm_by_key[key].machine))
            model.add_exactly_one(present_list)
            if key in fixed:
                model.add(start == fixed[key].start)
                model.add(end == fixed[key].end)
            else:
                model.add(start >= failure)
                shift = model.new_int_var(0, HORIZON, f"shift_{j}_{k}")
                model.add_abs_equality(shift, start - previous_by_key[key].start)
                shift_penalty.append(shift)
                model.add_hint(start, warm_by_key[key].start)
                model.add_hint(end, warm_by_key[key].end)
            if k > 0:
                model.add(start >= ends[(j, k-1)])
    for machine in range(MACHINES):
        model.add_no_overlap(machine_intervals[machine])
    makespan = model.new_int_var(0, HORIZON, "makespan")
    job_ends = [ends[(j, len(job.operations)-1)] for j, job in enumerate(jobs)]
    model.add_max_equality(makespan, job_ends)
    tardiness_terms = []
    for j, job in enumerate(jobs):
        delay = model.new_int_var(0, HORIZON, f"tardiness_{j}")
        model.add(delay >= job_ends[j] - job.due)
        tardiness_terms.append(job.weight * delay)
    model.minimize(10 * sum(tardiness_terms) + makespan + 2 * sum(shift_penalty))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.01, seconds)
    solver.parameters.num_search_workers = 1  # deterministic across repeated runs on same machine
    solver.parameters.random_seed = 2026
    result = solver.solve(model)
    if result not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, solver.status_name(result)
    assigned = []
    for j, job in enumerate(jobs):
        for k, op in enumerate(job.operations):
            machine = next(machine for a, (machine, _) in enumerate(op.alternatives)
                           if solver.boolean_value(chosen[(j, k, a)]))
            assigned.append(Slot(j, k, machine, solver.value(starts[(j,k)]), solver.value(ends[(j,k)])))
    assigned.sort(key=lambda s: (s.start, s.machine, s.job, s.op))
    validate_schedule(jobs, assigned, fixed, failure, failed_machine, recovery_time)
    return assigned, solver.status_name(result)


def save_csv(path: Path, schedule: list[Slot]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["job", "operation", "machine", "start", "end"])
        writer.writeheader()
        writer.writerows({"job": s.job, "operation": s.op, "machine": s.machine,
                          "start": s.start, "end": s.end} for s in schedule)


def demo(seed: int, engine: str, seconds: float, outdir: Path) -> dict:
    jobs = make_jobs(seed)
    baseline = greedy_schedule(jobs)
    validate_schedule(jobs, baseline)
    fixed, interrupted = build_fixed(baseline, failed_machine=0, failure=FAIL_TIME)
    fallback = greedy_schedule(jobs, fixed, FAIL_TIME, 0, DOWN_TIME, mode="edd")
    validate_schedule(jobs, fallback, fixed, FAIL_TIME, 0, DOWN_TIME)
    if engine == "cpsat":
        t0 = time.perf_counter()
        optimized, status = cpsat_schedule(jobs, baseline, fixed, 0, FAIL_TIME, DOWN_TIME, seconds)
        elapsed = round((time.perf_counter()-t0)*1000, 2)
        selected = optimized if optimized is not None else fallback
        solver = "CP-SAT" if optimized is not None else "EDD fallback after " + status
    else:
        selected, elapsed, solver, status = fallback, 0.0, "EDD heuristic", "HEURISTIC"
    validate_schedule(jobs, selected, fixed, FAIL_TIME, 0, DOWN_TIME)
    result = {
        "seed": seed, "failure_machine": 0,
        "failure_time": FAIL_TIME, "repaired_at": FAIL_TIME + DOWN_TIME,
        "frozen_operations": len(fixed), "interrupted_operations": [list(i) for i in interrupted],
        "solver": solver, "status": status, "solver_elapsed_ms": elapsed,
        "before_failure_plan": metrics(jobs, baseline),
        "recovered_edd": metrics(jobs, fallback),
        "recovered_selected": metrics(jobs, selected),
        "comparison_note": "No optimization gain is claimed unless tested with OR-Tools installed.",
    }
    outdir.mkdir(parents=True, exist_ok=True)
    save_csv(outdir/"baseline.csv", baseline)
    save_csv(outdir/"recovery_edd.csv", fallback)
    save_csv(outdir/"recovery_selected.csv", selected)
    (outdir/"summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def benchmark(n: int, engine: str, seconds: float, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    records=[]
    for seed in range(n):
        jobs=make_jobs(seed)
        baseline=greedy_schedule(jobs)
        fixed,_=build_fixed(baseline,0,FAIL_TIME)
        edd=greedy_schedule(jobs,fixed,FAIL_TIME,0,DOWN_TIME,mode="edd")
        fifo=greedy_schedule(jobs,fixed,FAIL_TIME,0,DOWN_TIME,mode="fifo")
        validate_schedule(jobs,edd,fixed,FAIL_TIME,0,DOWN_TIME)
        validate_schedule(jobs,fifo,fixed,FAIL_TIME,0,DOWN_TIME)
        selected, status, elapsed=edd,"HEURISTIC",0.0
        if engine=="cpsat":
            t0=time.perf_counter()
            attempt,status=cpsat_schedule(jobs,baseline,fixed,0,FAIL_TIME,DOWN_TIME,seconds)
            elapsed=(time.perf_counter()-t0)*1000
            if attempt is not None:
                selected=attempt
        for algorithm, schedule in [("EDD",edd),("FIFO",fifo),("CP-SAT" if engine=="cpsat" and status in ("OPTIMAL","FEASIBLE") else "EDD fallback", selected)]:
            row={"seed":seed,"algorithm":algorithm,"status":status if algorithm.startswith("CP-SAT") else "FEASIBLE",
                 "solver_ms":round(elapsed,2) if algorithm.startswith("CP-SAT") else 0.0}
            row.update(metrics(jobs,schedule))
            records.append(row)
    path=outdir/"benchmark.csv"
    with path.open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=["seed","algorithm","status","solver_ms","makespan","weighted_tardiness","completed_jobs"])
        writer.writeheader();writer.writerows(records)
    print(f"Wrote {len(records)} benchmark rows to {path}")


def main():
    parser=argparse.ArgumentParser(description="Reproducible event-triggered job-shop rescheduling demonstration")
    parser.add_argument("--engine", choices=["heuristic","cpsat"], default="heuristic",
                        help="Choose 'cpsat' after installing OR-Tools (no silent claim of CP-SAT use)")
    parser.add_argument("--seconds", type=float, default=2.0, help="CP-SAT solver time limit in seconds")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--bench", type=int, default=0, help="Run N reproducible scenarios and export benchmark.csv")
    parser.add_argument("--out", type=Path, default=Path("output"))
    args=parser.parse_args()
    if args.bench>0:
        benchmark(args.bench,args.engine,args.seconds,args.out)
    else:
        print(json.dumps(demo(args.seed,args.engine,args.seconds,args.out),indent=2))


if __name__=="__main__":
    main()