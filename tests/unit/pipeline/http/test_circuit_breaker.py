"""Tests du `SourceCircuitBreaker` : compteur d'échecs consécutifs par source."""

import pytest

from pipeline.http.circuit_breaker import (
    SourceCircuitBreaker,
    SourceUnavailableError,
    source_circuit_breaker,
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
    b.record_success()  # remet le compteur à zéro
    b.record_failure()
    b.record_failure()
    assert not b.tripped
    b.record_failure()
    assert b.tripped


def test_check_raises_only_when_tripped():
    b = SourceCircuitBreaker("zenodo", threshold=1)
    b.check()  # circuit fermé : aucune exception
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


def test_le_rythme_suit_le_debit_recu():
    with source_circuit_breaker("hal") as breaker:
        assert breaker.pace is None
    with source_circuit_breaker("hal", max_per_second=5) as breaker:
        assert breaker.pace is not None
