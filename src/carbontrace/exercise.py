"""Benchmark definitions shared by the original and expanded catalogs."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

Target = Callable[..., object]
Split = Literal["development", "holdout"]


@dataclass(frozen=True)
class TestCase:
    """Literal arguments and an independently specified expected outcome."""

    title: str
    args: tuple[object, ...]
    expected: object = None
    raises: type[Exception] | None = None


@dataclass(frozen=True)
class Mutation:
    """One named, project-owned defective implementation."""

    name: str
    description: str
    target: Target


@dataclass(frozen=True)
class Exercise:
    """A benchmark item with requirements, oracles, and a frozen split."""

    id: str
    title: str
    category: str
    description: str
    function: Target
    mutations: tuple[Mutation, ...]
    compact_cases: tuple[TestCase, ...]
    strong_cases: tuple[TestCase, ...]
    split: Split = "development"

    @property
    def source(self) -> str:
        """Expose the complete correct implementation for review and prompting."""
        return inspect.getsource(self.function)
