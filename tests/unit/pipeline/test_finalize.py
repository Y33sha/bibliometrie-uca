"""Orchestrateur de la phase `finalize` : purge des publications, synchronisation, référentiels vides, rafraîchissement des compteurs.

Les tests vérifient l'enchaînement des tâches et la boucle de purge. Celle-ci supprime par lots jusqu'à épuisement, commite chaque lot et rapporte son total dans le résumé de la phase.
"""

import dataclasses
import logging
from contextlib import ExitStack
from unittest.mock import patch

from pipeline.graph import Phase, in_transaction
from pipeline.phases import PHASES
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import run_phase
from pipeline.transformation import finalize as phase

_FINALIZE = next(p for p in PHASES if p.name == "finalize")
_SUPPRESSIONS = {
    "delete_empty_monographs": "monographs",
    "delete_empty_serials": "serials",
    "delete_empty_publishers": "publishers",
}


class _FakePurgeQueries:
    """Faux accès SQL de purge renvoyant les tailles de lots successives, puis zéro, qui arrête la boucle."""

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


def _suppression(appels: list[str], nom: str, n: int = 0):
    """Renvoie une suppression de référentiels vides qui retient son appel et supprime `n` lignes."""

    def run(_conn, _log) -> PhaseMetrics:
        appels.append(nom)
        m = PhaseMetrics()
        if n:
            m.add(serials_deleted=n)
            m.report = f"{n} supprimées"
        return m

    return run


def _finalize(appels: list[str], suppressions: dict[str, int] | None = None) -> Phase:
    """Renvoie la phase `finalize`, ses suppressions de référentiels vides remplacées par des enregistreurs."""
    suppressions = suppressions or {}

    def run(nom: str):
        return in_transaction(_suppression(appels, nom, suppressions.get(nom, 0)))

    return dataclasses.replace(
        _FINALIZE,
        tasks=tuple(
            dataclasses.replace(t, run=run(_SUPPRESSIONS[t.name])) if t.name in _SUPPRESSIONS else t
            for t in _FINALIZE.tasks
        ),
    )


def _patch_sql(counts: _Counts) -> list:
    """Simule les requêtes de synchronisation et les décomptes de la phase."""
    return [
        patch.object(phase, name, counts.counter(label, n))
        for name, label, n in (
            ("count_contributions_in_perimeter", "périmètre des contributions", 9),
            ("refresh_publications_perimeter_evidence", "périmètre des publications", 0),
            ("refresh_contribution_structures", "structures des groupes", None),
            ("refresh_publication_structures", "structures des publications", None),
            ("refresh_publication_rors", "ROR des publications", None),
            ("refresh_serial_publishers", "éditeur des revues", 4),
            ("recompute_address_publication_count", "adresses", 7),
            ("refresh_serial_publication_counts", "revues", 3),
            ("refresh_publisher_publication_counts", "éditeurs", 2),
        )
    ]


def _run(contexte, lots, suppressions: dict[str, int] | None = None):
    purge = _FakePurgeQueries(lots)
    counts = _Counts()
    with (
        patch.object(phase, "purge_publications", side_effect=purge.purge_publications),
        ExitStack() as stack,
    ):
        for patcher in _patch_sql(counts):
            stack.enter_context(patcher)
        rendu = run_phase(_finalize(counts.appels, suppressions), contexte())
    return rendu, purge, counts


def test_purge_par_lots_jusqu_a_epuisement(open_tx, contexte):
    rendu, purge, publication_counts = _run(contexte, [5000, 5000, 120])

    assert rendu.details["summary"]["publications_purged"] == 10120
    assert purge.limites == [5000] * 4  # trois lots pleins, puis l'appel qui renvoie zéro
    assert open_tx.conn.commits == 3  # un commit par lot supprimé, aucun pour le lot vide
    assert publication_counts.appels[-3:] == ["adresses", "revues", "éditeurs"]


def test_rien_a_purger(open_tx, contexte):
    rendu, purge, _ = _run(contexte, [])

    assert rendu.details["summary"]["publications_purged"] == 0
    assert open_tx.conn.commits == 0


def test_chaque_tache_dans_sa_transaction(open_tx, contexte):
    _run(contexte, [10])

    # purge, périmètre des publications, vues matérialisées, éditeur des revues, une suppression par référentiel vide, puis un décompte par famille : adresses, revues, éditeurs
    assert open_tx.transactions == 10


def test_la_synchronisation_ecrit_une_ligne_par_tache(contexte, caplog):
    with caplog.at_level(logging.INFO, logger="test"):
        rendu, _, _ = _run(contexte, [3])
    assert rendu.details["summary"]["total_in_perimeter"] == 9
    lignes = [m for m in caplog.messages if m]
    debut = lignes.index("▶ Synchronisation des tables")
    assert lignes[debut + 1] == "  ├─ Purge des publications : 3 publications supprimées"
    assert [ligne.split(" : ")[0] for ligne in lignes[debut + 2 : debut + 5]] == [
        "  ├─ Périmètre des publications",
        "  ├─ Structures des liens",
        "  └─ Éditeur des revues",
    ]


def test_referentiels_vides_supprimes_apres_la_purge(open_tx, contexte, caplog):
    """Monographies, revues puis éditeurs vides : chaque suppression écrit sa ligne et remonte ses compteurs."""
    with caplog.at_level(logging.INFO, logger="test"):
        rendu, _, counts = _run(contexte, [], {"serials": 2})

    suppressions = [a for a in counts.appels if a in ("monographs", "serials", "publishers")]
    assert suppressions == ["monographs", "serials", "publishers"]
    assert rendu.extras["serials_deleted"] == 2
    lignes = [m for m in caplog.messages if m]
    debut = lignes.index("▶ Référentiels vides")
    assert lignes[debut + 1 : debut + 4] == [
        "  ├─ Monographies vides : rien à faire",
        "  ├─ Publications en série vides : 2 supprimées",
        "  └─ Éditeurs vides : rien à faire",
    ]
