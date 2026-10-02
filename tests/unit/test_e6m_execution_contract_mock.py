"""Exercise the actual E6M run entry and observer without backend imports."""
import builtins
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts"))
import judge_e6m as J


class BackendReached(RuntimeError):
    pass


def main():
    runner = runpy.run_path(str(ROOT / "tests/integration/test_pn_2d_1d_consistency_real.py"))
    run, Obs = runner["run"], runner["Obs"]
    real_import = builtins.__import__
    plan = (J.HERE.parent / "PLAN.md").read_bytes().replace(b"\r\n", b"\n")
    for kind in ("different", "missing", "valid_lf", "valid_crlf"):
        events = []

        def backend():
            events.append("backend_prepare")
            raise BackendReached("synthetic stop before any engine")

        def importer(name, *args, **kwargs):
            if name == "tcad.device.devsim":
                events.append("backend_import")
                return SimpleNamespace(backend=SimpleNamespace(require_devsim=backend))
            if name.split(".")[0] in ("devsim", "viennaps"):
                raise AssertionError("an actual engine import was attempted")
            return real_import(name, *args, **kwargs)

        opts = {"side_effect": FileNotFoundError("synthetic missing PLAN")} if kind == "missing" else {
            "return_value": b"changed plan" if kind == "different" else plan if kind == "valid_lf" else plan.replace(b"\n", b"\r\n")}
        mesh, level = Mock(), Mock()
        with patch.object(Path, "read_bytes", **opts), patch("builtins.__import__", side_effect=importer), \
                patch.dict(run.__globals__, write_mesh=mesh, run_level=level):
            try:
                run(None)
            except ValueError as exc:
                assert kind in ("missing", "different") and "PLAN_PREFLIGHT_BLOCKED" in str(exc)
            except BackendReached:
                assert kind in ("valid_lf", "valid_crlf")
            else:
                raise AssertionError("run entry escaped the engine-free trap")
        assert events == ([] if kind in ("missing", "different") else ["backend_import", "backend_prepare"]), events
        mesh.assert_not_called()
        level.assert_not_called()
        print("PLAN", kind, "backend/mesh/write/sweep/solve blocked before engine" if not events else "valid preflight reached synthetic backend")

    for failure in (None, "solve", "snapshot"):
        engine_calls = []

        def fake_solve(*args, **kwargs):
            engine_calls.append("solve")
            if failure == "solve":
                raise RuntimeError("synthetic solve failure")
            return "returned"

        def snapshot():
            if failure == "snapshot":
                raise RuntimeError("synthetic snapshot failure")
            return {"synthetic": True}

        dv = SimpleNamespace(solve=fake_solve, node_model=lambda **k: None, set_node_values=lambda **k: None)
        obs = Obs(dv, "synthetic")
        obs.snapshot = snapshot
        obs.install()
        try:
            result = dv.solve()
            assert failure is None and result == "returned"
        except RuntimeError:
            assert failure in ("solve", "snapshot")
        finally:
            obs.restore()
        expected = (1, int(failure != "solve"), int(failure == "solve"), int(failure == "snapshot"))
        actual = (obs.solve_attempts, obs.solves, obs.solve_failures, obs.snapshot_failures)
        assert actual == expected, (failure, actual, expected)
        assert engine_calls == ["solve"] and dv.solve is fake_solve
        assert len(obs.call_log) == 1 and len(obs.snaps) == int(failure is None)
        assert obs.call_log[0]["status"] == ("solve_failed" if failure == "solve" else "solve_succeeded")
        print("OBSERVER", failure or "success", "attempts/successes/solve_failures/snapshot_failures", actual)
    assert not any(name in sys.modules for name in ("devsim", "viennaps"))
    print("E6M EXECUTION CONTRACT PASS; engine imports=0, real solves=0")


if __name__ == "__main__":
    main()
