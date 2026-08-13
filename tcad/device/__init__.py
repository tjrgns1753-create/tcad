"""Device simulation backends. Each backend (devsim/, and future others)
consumes only tcad.mesh.interface.ProcessResult — never a process
backend (e.g. viennaps) directly.

Public API: see tcad.device.devsim (the only backend implemented so far).
"""
