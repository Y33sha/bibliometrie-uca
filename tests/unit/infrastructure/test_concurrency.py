"""Primitif `run_parallel` : résultats par étiquette, propagation d'erreur, cas vide."""

import pytest

from infrastructure.concurrency import run_parallel


def test_returns_results_by_label():
    assert run_parallel({"a": lambda: 1, "b": lambda: 2}) == {"a": 1, "b": 2}


def test_empty_thunks():
    assert run_parallel({}) == {}


def test_propagates_thunk_exception():
    def boom():
        raise ValueError("échec")

    with pytest.raises(ValueError, match="échec"):
        run_parallel({"ok": lambda: 1, "boom": boom})
