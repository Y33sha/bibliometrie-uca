"""Tests de l'enchaînement de la phase `publishers_journals`, exécutée nœud par nœud dans l'ordre du graphe."""

import dataclasses
import logging
from unittest.mock import patch

from pipeline.graph import NODES
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing import publishers_journals
from pipeline.transformation.publishing.publishers_journals import PublishersJournalsPhase

_CHAMPS = tuple(
    n.name.removeprefix("publishers_journals.") for n in NODES if n.group == "publishers_journals"
)


def _run(
    contexte,
    appels: list[str] | None = None,
    *,
    credentials_missing: str | None = None,
    **metrics: PhaseMetrics,
) -> PhaseMetrics:
    """Exécute la phase avec ses étapes réelles, leurs fonctions remplacées par des enregistreurs."""
    appels = [] if appels is None else appels

    def runner(champ: str):
        def run(_ctx, _breaker) -> PhaseMetrics:
            appels.append(champ)
            return metrics.get(champ, PhaseMetrics())

        return run

    steps = {
        name: dataclasses.replace(step, run=runner(name.removeprefix("publishers_journals.")))
        for name, step in publishers_journals.build().steps.items()
    }
    with patch(
        "pipeline.runtime.config.source_credentials_missing",
        return_value=credentials_missing,
    ):
        return PublishersJournalsPhase(steps).run(contexte())


def test_les_noeuds_s_enchainent_dans_l_ordre_du_graphe(contexte):
    appels: list[str] = []
    _run(contexte, appels)
    assert appels == list(_CHAMPS)


def test_chaque_noeud_ecrit_sa_ligne_sous_sa_section(contexte, caplog):
    fusion = PhaseMetrics()
    fusion.add(total=2, journals_merged=2)
    fusion.resume = "2 revues fusionnées"
    with caplog.at_level(logging.INFO, logger="test"):
        _run(contexte, merge_duplicate_journals=fusion)
    lignes = [r.getMessage() for r in caplog.records if r.getMessage()]
    assert lignes[:3] == [
        "▶ Éditeurs",
        "  ├─ Éditeurs des préfixes DOI Crossref : rien à faire",
        "  └─ Éditeurs des préfixes DOI DataCite : rien à faire",
    ]
    assert "▶ Revues" in lignes and "▶ Monographies" in lignes
    assert "  ├─ Fusion des revues en double : 2 revues fusionnées" in lignes
    assert lignes[-1] == "  └─ Nature des monographies : rien à faire"


def test_les_compteurs_des_noeuds_remontent_a_la_phase(contexte):
    worked = PhaseMetrics()
    worked.add(total=3)
    metrics = _run(contexte, resolve_crossref_publishers=worked)
    assert metrics.total == 3


def test_acces_non_configure_saute_les_noeuds_a_source(contexte, caplog):
    """Sans identifiants, l'accès à la source saute le nœud avant sa fonction, et sa ligne le dit."""
    appels: list[str] = []
    with caplog.at_level(logging.INFO, logger="test"):
        metrics = _run(contexte, appels, credentials_missing="clé absente")
    assert "enrich_journals_from_openalex" not in appels
    assert "merge_duplicate_journals" in appels  # nœud sans source
    assert "Type des revues sur OpenAlex : sautée, accès non configuré" in caplog.text
    assert {s["code"] for s in metrics.signals} == {"source_unconfigured"}
