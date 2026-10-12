"""Tests de l'enchaînement de la phase `publishers_journals`."""

import logging

from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import signal_source_unconfigured
from pipeline.transformation.publishing.publishers_journals import PublishersJournalsPhase

_CHAMPS = (
    "resolve_crossref_publishers",
    "resolve_datacite_publishers",
    "enrich_journals_from_openalex",
    "check_journals_in_sudoc",
    "merge_duplicate_journals",
    "type_proceedings_journals",
    "learn_journal_doi_namespaces",
    "enrich_journals_from_doaj",
    "merge_duplicate_monographs",
    "link_monographs_to_collections",
    "type_proceedings_volumes",
)


def _run(contexte, appels: list[str] | None = None, **metrics: PhaseMetrics) -> PhaseMetrics:
    appels = [] if appels is None else appels

    def runner(champ: str):
        def run() -> PhaseMetrics:
            appels.append(champ)
            return metrics.get(champ, PhaseMetrics())

        return run

    return PublishersJournalsPhase(**{champ: runner(champ) for champ in _CHAMPS}).run(contexte())


def test_les_sous_etapes_s_enchainent_par_groupe(contexte):
    appels: list[str] = []
    _run(contexte, appels)
    assert appels == list(_CHAMPS)


def test_chaque_sous_etape_ecrit_sa_ligne_sous_son_groupe(contexte, caplog):
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
    assert "  ├─ Fusion des revues en double : 2 revues fusionnées" in lignes
    assert lignes[-1] == "  └─ Nature des monographies : rien à faire"


def test_les_compteurs_des_sous_etapes_remontent_a_la_phase(contexte):
    worked = PhaseMetrics()
    worked.add(total=3)
    metrics = _run(contexte, resolve_crossref_publishers=worked)
    assert metrics.total == 3


def test_acces_non_configure_saute_la_sous_etape(contexte, caplog):
    """L'accès à la source rend un signal `source_unconfigured` : la ligne de la sous-étape dit qu'elle est sautée."""
    non_configuree = PhaseMetrics()
    signal_source_unconfigured(
        non_configuree, "openalex", "clé absente", logger=logging.getLogger("test"), phase="test"
    )
    with caplog.at_level(logging.INFO, logger="test"):
        metrics = _run(contexte, enrich_journals_from_openalex=non_configuree)
    assert "Type des revues sur OpenAlex : sautée, accès non configuré" in caplog.text
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]
