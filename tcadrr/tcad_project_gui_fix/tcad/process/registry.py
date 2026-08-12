#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Registry mapping (category, name) -> ProcessStep subclass.

Concrete process modules (tcad/process/etching/*.py, and later
deposition/oxidation) register themselves with the @register decorator
on import. The GUI/CLI can then discover available models per category
at runtime via list_categories()/list_models() instead of hardcoding
which recipes exist.
"""

from __future__ import annotations

from typing import Dict, List, Type

from tcad.process.base import ProcessStep

_REGISTRY: Dict[str, Dict[str, Type[ProcessStep]]] = {}


def register(step_cls: Type[ProcessStep]) -> Type[ProcessStep]:
    """Class decorator: register a ProcessStep under its category/name."""
    if not step_cls.category:
        raise ValueError(f"{step_cls.__name__} must set a non-empty 'category'")
    if not step_cls.name:
        raise ValueError(f"{step_cls.__name__} must set a non-empty 'name'")

    _REGISTRY.setdefault(step_cls.category, {})[step_cls.name] = step_cls
    return step_cls


def get(category: str, name: str) -> Type[ProcessStep]:
    """Look up a registered ProcessStep subclass by category and name."""
    try:
        return _REGISTRY[category][name]
    except KeyError as exc:
        raise KeyError(
            f"No process step registered for category={category!r} name={name!r}. "
            f"Available: {_REGISTRY}"
        ) from exc


def list_categories() -> List[str]:
    return sorted(_REGISTRY.keys())


def list_models(category: str) -> List[str]:
    return sorted(_REGISTRY.get(category, {}).keys())
