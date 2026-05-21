"""Tests du module `infrastructure/observability/pipeline_checks.py`.

Couvre la logique pure (sans BDD) : construction des observations à partir
d'un payload courant + payload précédent, calcul des deltas, détection des
observables suspects, rendu du résumé console.
"""

from __future__ import annotations

import datetime

from application.ports.pipeline.checks import CheckReport, Observation
from infrastructure.observability.pipeline_checks import (
    _build_observations,
    _drift_observation,
    _to_ratios,
    render_summary,
)


class TestToRatios:
    def test_basic(self):
        assert _to_ratios({"a": 50, "b": 50}) == {"a": 0.5, "b": 0.5}

    def test_total_zero_returns_zeros(self):
        assert _to_ratios({"a": 0, "b": 0}) == {"a": 0.0, "b": 0.0}

    def test_empty(self):
        assert _to_ratios({}) == {}


class TestDriftObservation:
    def test_no_previous_not_suspect(self):
        o = _drift_observation(
            key="k",
            label="l",
            current=100,
            previous=None,
            threshold_pct=5.0,
            symmetric=True,
        )
        assert o.suspect is False
        assert o.previous is None
        assert o.delta_pct is None
        assert "premier snapshot" in o.threshold_note

    def test_previous_zero_current_positive_is_suspect(self):
        o = _drift_observation(
            key="k",
            label="l",
            current=10,
            previous=0,
            threshold_pct=5.0,
            symmetric=True,
        )
        assert o.suspect is True
        assert "précédent à 0" in o.threshold_note

    def test_previous_zero_current_zero_not_suspect(self):
        o = _drift_observation(
            key="k",
            label="l",
            current=0,
            previous=0,
            threshold_pct=5.0,
            symmetric=True,
        )
        assert o.suspect is False

    def test_symmetric_within_threshold(self):
        o = _drift_observation(
            key="k",
            label="l",
            current=104,
            previous=100,
            threshold_pct=5.0,
            symmetric=True,
        )
        assert o.suspect is False
        assert o.delta_pct == 4.0

    def test_symmetric_above_threshold(self):
        o = _drift_observation(
            key="k",
            label="l",
            current=110,
            previous=100,
            threshold_pct=5.0,
            symmetric=True,
        )
        assert o.suspect is True
        assert o.delta_pct == 10.0

    def test_symmetric_below_threshold(self):
        o = _drift_observation(
            key="k",
            label="l",
            current=90,
            previous=100,
            threshold_pct=5.0,
            symmetric=True,
        )
        assert o.suspect is True
        assert o.delta_pct == -10.0

    def test_asymmetric_growth_above_threshold(self):
        o = _drift_observation(
            key="k",
            label="l",
            current=120,
            previous=100,
            threshold_pct=10.0,
            symmetric=False,
        )
        assert o.suspect is True

    def test_asymmetric_drop_not_suspect(self):
        # Une baisse même forte n'est pas suspecte en asymmetric=False
        o = _drift_observation(
            key="k",
            label="l",
            current=50,
            previous=100,
            threshold_pct=10.0,
            symmetric=False,
        )
        assert o.suspect is False


class TestBuildObservations:
    def _current(self):
        return {
            "volumes": {"publications": 1000, "persons": 500},
            "orphans": {"publications_no_authorships": 10, "persons_no_publications": 5},
            "distributions": {
                "doc_type": {"article": 0.7, "thesis": 0.3},
                "source": {"hal": 0.6, "openalex": 0.4},
            },
            "matching_quality": {"ambiguous_name_forms": 20},
        }

    def test_first_run_no_previous_no_suspects(self):
        obs = _build_observations(self._current(), previous=None)
        assert all(not o.suspect for o in obs)
        # 2 vol + 2 orph + (2+2) distrib + 1 matching = 9
        assert len(obs) == 9

    def test_volume_drift_above_threshold_flagged(self):
        previous = {
            "volumes": {"publications": 100, "persons": 500},
            "orphans": {},
            "distributions": {},
            "matching_quality": {},
        }
        obs = _build_observations(self._current(), previous=previous)
        suspects = [o for o in obs if o.suspect]
        # publications a augmenté de 100 à 1000 (×10) — largement > 5%
        assert any(o.key == "volumes.publications" and o.suspect for o in suspects)
        # persons est stable
        assert all(not (o.key == "volumes.persons" and o.suspect) for o in obs)

    def test_distribution_shift_in_points(self):
        previous = {
            "volumes": {},
            "orphans": {},
            "distributions": {
                "doc_type": {"article": 0.65, "thesis": 0.35},
                "source": {"hal": 0.6, "openalex": 0.4},
            },
            "matching_quality": {},
        }
        obs = _build_observations(self._current(), previous=previous)
        article_obs = next(o for o in obs if o.key == "distributions.doc_type.article")
        # 0.7 vs 0.65 = +5 pts > 3 pts → suspect
        assert article_obs.suspect is True

    def test_distribution_new_key_in_current(self):
        previous = {
            "volumes": {},
            "orphans": {},
            "distributions": {"doc_type": {"article": 1.0}},
            "matching_quality": {},
        }
        obs = _build_observations(self._current(), previous=previous)
        thesis_obs = next(o for o in obs if o.key == "distributions.doc_type.thesis")
        # Nouvelle clé : previous=None pour cette clé → non comparable
        assert thesis_obs.previous is None
        assert thesis_obs.suspect is False

    def test_distribution_disappeared_key(self):
        previous = {
            "volumes": {},
            "orphans": {},
            "distributions": {
                "doc_type": {"article": 0.5, "thesis": 0.3, "book": 0.2},
            },
            "matching_quality": {},
        }
        obs = _build_observations(self._current(), previous=previous)
        book_obs = next(o for o in obs if o.key == "distributions.doc_type.book")
        # current=0, previous=0.2 → shift -20 pts → suspect
        assert book_obs.current == 0.0
        assert book_obs.suspect is True

    def test_matching_quality_asymmetric_drop_not_flagged(self):
        previous = {
            "volumes": {},
            "orphans": {},
            "distributions": {},
            "matching_quality": {"ambiguous_name_forms": 100},
        }
        obs = _build_observations(self._current(), previous=previous)
        match_obs = next(o for o in obs if o.key == "matching_quality.ambiguous_name_forms")
        # 20 vs 100 = -80%, mais asymmetric=False → non suspect
        assert match_obs.suspect is False


class TestRenderSummary:
    def _report(self, observations: list[Observation], previous_at=None):
        return CheckReport(
            mode="full",
            ran_at=datetime.datetime(2026, 5, 21, 10, 0, tzinfo=datetime.UTC),
            previous_snapshot_at=previous_at,
            current={},
            observations=observations,
        )

    def test_no_previous_snapshot_message(self):
        out = render_summary(self._report([]))
        assert "premier snapshot" in out
        assert "mode=full" in out

    def test_no_suspects_message(self):
        obs = [
            Observation(
                key="volumes.publications",
                label="volume publications",
                current=100,
                previous=100,
                delta_pct=0.0,
                suspect=False,
                threshold_note="delta +0.0%",
            )
        ]
        out = render_summary(
            self._report(
                obs,
                previous_at=datetime.datetime(2026, 5, 20, 10, 0, tzinfo=datetime.UTC),
            )
        )
        assert "Aucune observation suspecte" in out

    def test_lists_suspects_only(self):
        obs = [
            Observation(
                key="volumes.publications",
                label="volume publications",
                current=200,
                previous=100,
                delta_pct=100.0,
                suspect=True,
                threshold_note="delta +100.0% (seuil ±5.0%)",
            ),
            Observation(
                key="volumes.persons",
                label="volume persons",
                current=500,
                previous=500,
                delta_pct=0.0,
                suspect=False,
                threshold_note="delta +0.0%",
            ),
        ]
        out = render_summary(
            self._report(
                obs,
                previous_at=datetime.datetime(2026, 5, 20, 10, 0, tzinfo=datetime.UTC),
            )
        )
        assert "volume publications" in out
        assert "volume persons" not in out
        assert "1 observation(s) suspecte(s) sur 2" in out
