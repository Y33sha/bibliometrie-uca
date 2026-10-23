"""Orchestrateur de la phase `contributions` : build, synchronisation, purge des publications, référentiels vides, refresh des compteurs.

Le propos testé ici est l'enchaînement des tâches et la boucle de purge : celle-ci supprime par lots jusqu'à épuisement, en committant chaque lot, et rapporte son total dans le résumé du build. Le build lui-même a ses propres tests.
"""

import logging
from contextlib import ExitStack
from unittest.mock import patch

from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publications.contributions import contributions as phase


class _FakePurgeQueries:
    """Rend les tailles de lots successives, puis zéro — ce qui arrête la boucle."""

    def __init__(self, lots: list[int]) -> None:
        self._lots = [*lots, 0]
        self.limites: list[int | None] = []

    def purge_publications(self, conn, *, limit=None) -> int:
        self.limites.append(limit)
        return self._lots.pop(0)


class _Counts:
    """Requêtes SQL de la phase appelées, dans l'ordre."""

    def __init__(self) -> None:
        self.appels: list[str] = []

    def counter(self, name: str, n: int | None):
        def count(_conn) -> int | None:
            self.appels.append(name)
            return n

        return count


def _patch_sql(counts: _Counts) -> list:
    """Remplace les requêtes de synchronisation et les décomptes de la phase."""
    return [
        patch.object(phase, name, counts.counter(label, n))
        for name, label, n in (
            ("propagate_contribution_attributes", "propagation", 0),
            ("count_contributions_in_perimeter", "périmètre des contributions", 9),
            ("refresh_publications_perimeter_evidence", "périmètre des publications", 0),
            ("refresh_contribution_structures", "structures des contributions", None),
            ("refresh_publication_structures", "structures des publications", None),
            ("recompute_address_publication_count", "adresses", 7),
            ("refresh_journal_publication_counts", "revues", 3),
            ("refresh_publisher_publication_counts", "éditeurs", 2),
        )
    ]


def _run(contexte, lots, *, build_metrics=None):
    purge = _FakePurgeQueries(lots)
    counts = _Counts()
    metrics = build_metrics or PhaseMetrics(new=12)
    metrics.details.setdefault("summary", {})
    with (
        patch.object(phase, "build_contributions", return_value=metrics),
        patch.object(phase, "purge_publications", side_effect=purge.purge_publications),
        ExitStack() as stack,
    ):
        for patcher in _patch_sql(counts):
            stack.enter_context(patcher)
        rendu = phase.ContributionsPhase().run(contexte())
    return rendu, purge, counts


def test_purge_par_lots_jusqu_a_epuisement(open_tx, contexte):
    rendu, purge, publication_counts = _run(contexte, [5000, 5000, 120])

    assert rendu.details["summary"]["publications_purged"] == 10120
    assert purge.limites == [5000] * 4  # trois lots pleins, puis l'appel qui rend zéro
    assert open_tx.conn.commits == 3  # un commit par lot supprimé, aucun pour le lot vide
    assert publication_counts.appels[-3:] == ["adresses", "revues", "éditeurs"]


def test_rien_a_purger(open_tx, contexte):
    rendu, purge, _ = _run(contexte, [])

    assert rendu.details["summary"]["publications_purged"] == 0
    assert open_tx.conn.commits == 0


def test_metriques_du_build_rendues_telles_quelles(contexte):
    rendu, _, _ = _run(contexte, [], build_metrics=PhaseMetrics(new=42))

    assert rendu.new == 42


def test_resume_absent_du_build_laisse_la_purge_sans_trace(contexte):
    """Le build rend un résumé qui n'est pas un dictionnaire : la purge tourne, sans rien y inscrire."""
    metrics = PhaseMetrics()
    metrics.details["summary"] = "rien à dire"

    rendu, purge, _ = _run(contexte, [7], build_metrics=metrics)

    assert rendu.details["summary"] == "rien à dire"
    assert purge.limites  # la purge a bien tourné


def test_chaque_tache_dans_sa_transaction(open_tx, contexte):
    _run(contexte, [10])

    # build, propagation, périmètre des publications, matviews, purge, puis un décompte par famille : adresses, revues, éditeurs
    assert open_tx.transactions == 8


def test_la_synchronisation_suit_le_build(contexte, caplog):
    with caplog.at_level(logging.INFO, logger="test"):
        rendu, _, _ = _run(contexte, [])
    assert rendu.details["summary"]["total_in_perimeter"] == 9
    lignes = [m for m in caplog.messages if m]
    debut = lignes.index("▶ Synchronisation des tables")
    assert [ligne.split(" : ")[0] for ligne in lignes[debut + 1 : debut + 4]] == [
        "  ├─ Attributs des liens",
        "  ├─ Périmètre des publications",
        "  └─ Structures des liens",
    ]


def test_referentiels_vides_supprimes_apres_la_purge(open_tx, contexte, caplog):
    """Monographies, revues puis éditeurs vides : chaque suppression écrit sa ligne et remonte ses compteurs."""
    appels: list[str] = []

    def suppression(nom: str, n: int):
        def run(_ctx) -> PhaseMetrics:
            appels.append(nom)
            m = PhaseMetrics()
            if n:
                m.add(journals_deleted=n)
                m.report = f"{n} supprimées"
            return m

        return run

    metrics = PhaseMetrics(new=1)
    metrics.details["summary"] = {}
    with (
        patch.object(phase, "build_contributions", return_value=metrics),
        patch.object(phase, "purge_publications", return_value=0),
        caplog.at_level(logging.INFO, logger="test"),
        ExitStack() as stack,
    ):
        for patcher in _patch_sql(_Counts()):
            stack.enter_context(patcher)
        rendu = phase.ContributionsPhase(
            empty_containers=(
                ("Monographies vides", suppression("monographies", 0)),
                ("Revues vides", suppression("revues", 2)),
                ("Éditeurs vides", suppression("éditeurs", 0)),
            ),
        ).run(contexte())

    assert appels == ["monographies", "revues", "éditeurs"]
    assert rendu.extras["journals_deleted"] == 2
    assert "  ├─ Revues vides : 2 supprimées" in caplog.messages
    assert "  └─ Éditeurs vides : rien à faire" in caplog.messages
