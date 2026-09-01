#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A NON-ZERO body bias is actually SOLVED FOR, not just reported.

run_mosfet_id_vgs_sweep used to apply body_voltage with set_bias(),
which only sets DevSim's bias PARAMETER and never solves. The very next
operation is rampbias(gate, gate_voltages[0], ...), whose own loop is
`while abs(last_bias - end_bias) > min_step` -- so with gate_voltages
== [0.0], the gate's own starting bias, that loop body never executes
and NO solve ever happens with the body bias applied. The returned
BiasPoint still claimed voltages[body_contact] == body_voltage.

So this test runs exactly that case: gate_voltages=[0.0], once at
body_voltage=0.0 and once at a real reverse body bias, and compares the
terminal currents. Under the old code the two runs were bit-identical
by construction.

Scope note, measured not assumed: the brief for this fix asked for a
threshold-voltage DIRECTION check (reverse body bias raises Vth, lowers
Id at a fixed non-zero Vgs). That is not reachable on this device --
direct execution shows the gate ramp to Vgs=4.0V does NOT converge once
a -0.3V body bias is applied (DevSim "Convergence failure!" ->
rampbias "Minimum step size too small"), while the body ramp ALONE
converges cleanly at both -0.1V and -0.3V. What this device's body
contact does at Vgs=0 is also not a threshold shift: this recipe's
implant windows are laterally-windowed but FULL-DEPTH, so Si_ymin (the
substrate bottom) touches both n+ columns and shares a resistive
substrate path with the drain. So the physical check below is Ohm's
law on that path instead -- the drain current must rise by exactly
(Vd - Vb)/Vd -- which is a sharper prediction than a direction, and is
KCL-conserving, i.e. decisive proof a real solve happened.

Reuses test_mosfet_body_contact_real.py's own already-verified
4-terminal device builder rather than duplicating it.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_mosfet_body_contact_real import _build_device, DRAIN_VOLTAGE  # noqa: E402

from tcad.device.devsim import backend as devsim_backend  # noqa: E402
from tcad.characterization.mosfet_sweep import run_mosfet_id_vgs_sweep  # noqa: E402

devsim = devsim_backend.require_devsim()

#: Exactly the gate's own starting bias -- rampbias(gate) is a complete
#: no-op here, so the body ramp is the ONLY thing that can apply the
#: body bias.
GATE_VOLTAGES = [0.0]
BODY_VOLTAGE = -0.3


def _sweep(body_voltage):
    with tempfile.TemporaryDirectory() as tmp:
        imported = _build_device(tmp)
        try:
            return run_mosfet_id_vgs_sweep(
                device=imported.device, si_region="Si", oxide_region="SiO2",
                source_contact="Si_xmin", drain_contact="Si_xmax", gate_contact="SiO2_ymax",
                interface_name="Si_SiO2_interface",
                gate_voltages=GATE_VOLTAGES, drain_voltage=DRAIN_VOLTAGE,
                body_contact="Si_ymin", body_voltage=body_voltage,
            )
        finally:
            devsim.delete_device(device=imported.device)
            devsim.delete_mesh(mesh=imported.mesh)


def main():
    # The BIASED sweep runs FIRST, deliberately. Measured, not assumed:
    # this same -0.3V body ramp converges cleanly as the first device in
    # a process and diverges ("Convergence failure!" -> rampbias
    # "Minimum step size too small") as the SECOND, even with the first
    # device properly delete_device()'d and delete_mesh()'d -- the same
    # cross-solve sensitivity CLAUDE.md already records for this
    # project's DevSim lifecycle. The Vb=0.0 baseline cannot fail that
    # way (its body ramp is start==end, so it never solves at all), so
    # it is the safe one to run second.
    biased = _sweep(BODY_VOLTAGE).points[0]
    assert biased.voltages["Si_ymin"] == BODY_VOLTAGE, biased.voltages
    print(f"[1/4] at Vb={BODY_VOLTAGE} V: currents={biased.currents}")

    baseline = _sweep(0.0).points[0]
    print(f"[2/4] baseline at Vb=0.0 V: currents={baseline.currents}")

    # A real converged solve, not a diverged one that happened to
    # return numbers: the three terminal currents still sum to zero.
    scale = max(abs(v) for v in biased.currents.values())
    total = sum(biased.currents.values())
    assert abs(total) < 0.02 * scale, (
        f"charge not conserved at Vb={BODY_VOLTAGE}: {biased.currents}"
    )
    print(f"[3/4] charge conserved across Source+Drain+Body at Vb={BODY_VOLTAGE} "
          f"(sum={total:.3e} A vs scale {scale:.3e} A)")

    # The decisive check. Same device, same (empty) gate ramp, ONLY the
    # body bias differs -- under the old set_bias()-and-never-solve code
    # these two runs produced identical currents.
    #
    # The expected DIRECTION and MAGNITUDE are Ohm's law on the
    # substrate path this device really has (see the module docstring:
    # full-depth implant windows, so drain and body share a resistive
    # path): the drain sits at DRAIN_VOLTAGE and the body at
    # BODY_VOLTAGE, so pulling the body negative raises the voltage
    # across that path from DRAIN_VOLTAGE to
    # DRAIN_VOLTAGE - BODY_VOLTAGE and the current rises by that ratio.
    id_baseline = abs(baseline.currents["Si_xmax"])
    id_biased = abs(biased.currents["Si_xmax"])
    expected_ratio = (DRAIN_VOLTAGE - BODY_VOLTAGE) / DRAIN_VOLTAGE
    ratio = id_biased / id_baseline
    assert abs(ratio - expected_ratio) < 0.1 * expected_ratio, (
        f"drain current did not follow the body bias: |Id| {id_baseline:.6e} A -> "
        f"{id_biased:.6e} A is {ratio:.4f}x, expected ~{expected_ratio:.4f}x "
        f"((Vd-Vb)/Vd). Equal currents mean the body bias was never solved for."
    )
    print(f"[4/4] a non-zero body bias really moves the solution: |Id| "
          f"{id_baseline:.3e} A -> {id_biased:.3e} A = {ratio:.4f}x, "
          f"(Vd-Vb)/Vd = {expected_ratio:.4f}")

    print()
    print("NON-ZERO BODY BIAS VERIFIED SOLVED against real ViennaPS 4.6.2 + DevSim")


if __name__ == "__main__":
    main()
