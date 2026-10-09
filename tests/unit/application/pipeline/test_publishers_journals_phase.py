"""Tests de l'enchaînement de la phase `publishers_journals`."""

import logging

from application.pipeline.metrics import PhaseMetrics
from application.pipeline.publishers_journals.phase import PublishersJournalsPhase

_CHAMPS = (
    "resolve_publishers",
    "enrich_journals_from_openalex",
    "check_journals_in_sudoc",
    "merge_duplicate_journals",
    "type_proceedings_journals",
    "learn_journal_doi_namespaces",
    "enrich_journals_from_doaj",
    "merge_duplicate_monographs",
    "link_monographs_to_collections",
    "type_proceedings_volumes",
    "delete_empty_monographs",
    "delete_empty_journals",
    "delete_empty_publishers",
)


def _run(contexte, appels: list[str] | None = None, **metrics: PhaseMetrics) -> PhaseMetrics:
    appels = [] if appels is None else appels

    def runner(champ: str):
        def run() -> PhaseMetrics:
            appels.append(champ)
            return metrics.get(champ, PhaseMetrics())

        return run

    return PublishersJournalsPhase(
        **{champ: runner(champ) for champ in _CHAMPS},
        credentials_missing=lambda source: None,
    ).run(contexte())


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
    assert lignes[:2] == ["▶ Éditeurs", "  └─ Éditeurs des préfixes DOI : rien à faire"]
    assert "  ├─ Fusion des revues en double : 2 revues fusionnées" in lignes
    assert lignes[-1] == "  └─ Éditeurs vides : rien à faire"


def test_les_compteurs_des_sous_etapes_remontent_a_la_phase(contexte):
    worked = PhaseMetrics()
    worked.add(total=3)
    metrics = _run(contexte, resolve_publishers=worked)
    assert metrics.total == 3


def test_acces_non_configure_saute_la_sous_etape(contexte, caplog):
    appels: list[str] = []
    phase = PublishersJournalsPhase(
        **{champ: (lambda c=champ: appels.append(c) or PhaseMetrics()) for champ in _CHAMPS},
        credentials_missing=lambda source: "clé absente" if source == "openalex" else None,
    )
    with caplog.at_level(logging.INFO, logger="test"):
        metrics = phase.run(contexte())
    assert "enrich_journals_from_openalex" not in appels
    assert "Type des revues sur OpenAlex : sautée, accès non configuré" in caplog.text
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]
