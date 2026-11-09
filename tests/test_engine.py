"""The engine Agloe depends on answers consistently, and proves impossibility."""

from ortools.sat.python import cp_model

DRIVE_MINUTES = 90
CHECK_IN_MINUTES = 30


def solve(ferry_departure: int | None) -> tuple[str, list[int]]:
    """Schedule a drive that must reach a ferry before check-in closes."""
    model = cp_model.CpModel()
    drive_start = model.new_int_var(0, 600, "drive_start")
    ferry_start = model.new_int_var(0, 600, "ferry_start")
    model.add(ferry_start >= drive_start + DRIVE_MINUTES + CHECK_IN_MINUTES)
    if ferry_departure is not None:
        model.add(ferry_start == ferry_departure)
    model.minimize(ferry_start)
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return solver.status_name(status), []
    return solver.status_name(status), [solver.value(drive_start), solver.value(ferry_start)]


def test_same_answer_every_run() -> None:
    first = solve(None)
    assert first == ("OPTIMAL", [0, 120])
    assert all(solve(None) == first for _ in range(5))


def test_proves_a_ferry_unreachable() -> None:
    assert solve(100) == ("INFEASIBLE", [])
