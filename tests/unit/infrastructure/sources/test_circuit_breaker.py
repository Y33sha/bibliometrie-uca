"""Tests du `SourceCircuitBreaker` : compteur d'échecs consécutifs par source."""

import pytest

from infrastructure.sources.circuit_breaker import (
    SourceCircuitBreaker,
    SourceUnavailableError,
)


def test_trips_after_threshold_consecutive_failures():
    b = SourceCircuitBreaker("wos", threshold=3)
    b.record_failure()
    b.record_failure()
    assert not b.tripped
    b.record_failure()
    assert b.tripped


def test_success_resets_counter():
    b = SourceCircuitBreaker("wos", threshold=3)
    b.record_failure()
    b.record_failure()
    b.record_success()  # remet à 0
    b.record_failure()
    b.record_failure()
    assert not b.tripped
    b.record_failure()
    assert b.tripped


def test_check_raises_only_when_tripped():
    b = SourceCircuitBreaker("zenodo", threshold=1)
    b.check()  # pas tripé → ne lève rien
    b.record_failure()
    assert b.tripped
    with pytest.raises(SourceUnavailableError) as exc:
        b.check()
    assert exc.value.source == "zenodo"


def test_default_threshold_is_10():
    b = SourceCircuitBreaker("openalex")
    for _ in range(9):
        b.record_failure()
    assert not b.tripped
    b.record_failure()
    assert b.tripped
