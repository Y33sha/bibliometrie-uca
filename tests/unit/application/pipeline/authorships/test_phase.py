"""Orchestrateur de la phase `authorships` : build, purge des orphelines, refresh des compteurs.

Le propos testé ici est l'enchaînement et la boucle de purge : celle-ci supprime par lots jusqu'à épuisement, en committant chaque lot, et rapporte son total dans le résumé du build. Le build lui-même a ses propres tests.
"""

import logging
from unittest.mock import patch

from application.pipeline.authorships import phase
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.authorships.pub_counts import PubCountChanges

_LOG = logging.getLogger("test")


class _FakePurgeQueries:
    """Rend les tailles de lots successives, puis zéro — ce qui arrête la boucle."""

    def __init__(self, lots: list[int]) -> None:
        self._lots = [*lots, 0]
        self.limites: list[int | None] = []

    def purge_orphan_publications(self, conn, *, limit=None) -> int:
        self.limites.append(limit)
        return self._lots.pop(0)


class _FakePubCountsQueries:
    def __init__(self) -> None:
        self.appels = 0

    def refresh_pub_counts(self, conn) -> PubCountChanges:
        self.appels += 1
        return PubCountChanges(journals=3, publishers=2)


def _run(open_tx, lots, *, rebuild_authorships=False, build_metrics=None):
    purge = _FakePurgeQueries(lots)
    pub_counts = _FakePubCountsQueries()
    vus: dict[str, object] = {}
    metrics = build_metrics or PhaseMetrics(new=12)
    metrics.details.setdefault("summary", {})
    with patch.object(
        phase,
        "build",
        side_effect=lambda conn, queries, logger, *, rebuild_full: (
            vus.__setitem__("rebuild_full", rebuild_full) or metrics
        ),
    ):
        rendu = phase.run(
            open_tx,
            object(),
            purge,
            pub_counts,
            _LOG,
            rebuild_authorships=rebuild_authorships,
        )
    return rendu, purge, pub_counts, vus


def test_purge_par_lots_jusqu_a_epuisement(open_tx):
    rendu, purge, pub_counts, _ = _run(open_tx, [5000, 5000, 120])

    assert rendu.details["summary"]["publications_purged"] == 10120
    assert purge.limites == [5000] * 4  # trois lots pleins, puis l'appel qui rend zéro
    assert open_tx.conn.commits == 3  # un commit par lot supprimé, aucun pour le lot vide
    assert pub_counts.appels == 1


def test_rien_a_purger(open_tx):
    rendu, purge, _, _ = _run(open_tx, [])

    assert rendu.details["summary"]["publications_purged"] == 0
    assert open_tx.conn.commits == 0


def test_metriques_du_build_rendues_telles_quelles(open_tx):
    rendu, _, _, _ = _run(open_tx, [], build_metrics=PhaseMetrics(new=42))

    assert rendu.new == 42


def test_rebuild_transmis_au_build(open_tx):
    _, _, _, vus = _run(open_tx, [], rebuild_authorships=True)

    assert vus["rebuild_full"] is True


def test_resume_absent_du_build_laisse_la_purge_sans_trace(open_tx):
    """Le build rend un résumé qui n'est pas un dictionnaire : la purge tourne, sans rien y inscrire."""
    metrics = PhaseMetrics()
    metrics.details["summary"] = "rien à dire"

    rendu, purge, _, _ = _run(open_tx, [7], build_metrics=metrics)

    assert rendu.details["summary"] == "rien à dire"
    assert purge.limites  # la purge a bien tourné


def test_chaque_sous_etape_dans_sa_transaction(open_tx):
    _run(open_tx, [10])

    assert open_tx.transactions == 3  # build, purge, refresh des compteurs
