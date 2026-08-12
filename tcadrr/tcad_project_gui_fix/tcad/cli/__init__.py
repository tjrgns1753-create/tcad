"""JSON-config-driven CLI for the full Process -> Mesh -> Doping ->
Device -> Characterization pipeline. Pure orchestration of existing
Phase 1-9 functions — no new physics.

Public API:
    from tcad.cli.run_pipeline import run_pipeline, main

Not imported eagerly here on purpose: `python -m tcad.cli.run_pipeline`
re-executes that module as __main__, and eagerly importing it here too
(as a normal package's __init__.py might) causes a
"found in sys.modules ... prior to execution" RuntimeWarning.
"""

__all__ = ["run_pipeline", "main"]


def __getattr__(name):
    if name in __all__:
        from tcad.cli import run_pipeline as _module
        return getattr(_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
