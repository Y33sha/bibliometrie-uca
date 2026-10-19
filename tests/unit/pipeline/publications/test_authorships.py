"""Orchestrateur de la phase `authorships` : build, synchronisation, purge des orphelines, référentiels vides, refresh des compteurs.

Le propos testé ici est l'enchaînement des nœuds et la boucle de purge : celle-ci supprime par lots jusqu'à épuisement, en committant chaque lot, et rapporte son total dans le résumé du build. Le build lui-même a ses propres tests.
"""

import logging
from unittest.mock import patch

from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publications.authorships import authorships as phase


class _FakeBuildQueries:
    """Requêtes des trois nœuds de synchronisation."""

    def __init__(self) -> None:
        self.appels: list[str] = []

    def propagate_authorship_attributes(self, conn) -> int:
        self.appels.append("propagate")
        return 0

    def count_authorships_in_perimeter(self, conn) -> int:
        return 9

    def refresh_publications_perimeter_evidence(self, conn) -> None:
        self.appels.append("publications_in_perimeter")

    def refresh_authorship_structures(self, conn) -> None:
        self.appels.append("authorship_structures")

    def refresh_publication_structures(self, conn) -> None:
        self.appels.append("publication_structures")


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

    def refresh_journal_pub_counts(self, conn) -> int:
        self.appels += 1
        return 3

    def refresh_publisher_pub_counts(self, conn) -> int:
        self.appels += 1
        return 2


class _FakeAddressPubCountQueries:
    def __init__(self) -> None:
        self.appels = 0

    def recompute_pub_count(self, conn) -> int:
        self.appels += 1
        return 7


def _run(contexte, lots, *, build_metrics=None):
    purge = _FakePurgeQueries(lots)
    pub_counts = _FakePubCountsQueries()
    adresses = _FakeAddressPubCountQueries()
    metrics = build_metrics or PhaseMetrics(new=12)
    metrics.details.setdefault("summary", {})
    with patch.object(
        phase,
        "build_authorships",
        return_value=metrics,
    ):
        rendu = phase.AuthorshipsPhase(_FakeBuildQueries(), purge, pub_counts, adresses).run(
            contexte()
        )
    return rendu, purge, pub_counts


def test_purge_par_lots_jusqu_a_epuisement(open_tx, contexte):
    rendu, purge, pub_counts = _run(contexte, [5000, 5000, 120])

    assert rendu.details["summary"]["publications_purged"] == 10120
    assert purge.limites == [5000] * 4  # trois lots pleins, puis l'appel qui rend zéro
    assert open_tx.conn.commits == 3  # un commit par lot supprimé, aucun pour le lot vide
    assert pub_counts.appels == 2  # revues puis éditeurs


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


def test_chaque_noeud_dans_sa_transaction(open_tx, contexte):
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
        def run() -> PhaseMetrics:
            appels.append(nom)
            m = PhaseMetrics()
            if n:
                m.add(journals_deleted=n)
                m.resume = f"{n} supprimées"
            return m

        return run

    metrics = PhaseMetrics(new=1)
    metrics.details["summary"] = {}
    with (
        patch.object(phase, "build_authorships", return_value=metrics),
        caplog.at_level(logging.INFO, logger="test"),
    ):
        rendu = phase.AuthorshipsPhase(
            _FakeBuildQueries(),
            _FakePurgeQueries([]),
            _FakePubCountsQueries(),
            _FakeAddressPubCountQueries(),
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
