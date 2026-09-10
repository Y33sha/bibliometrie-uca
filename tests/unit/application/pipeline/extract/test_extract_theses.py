"""Tests unitaires de l'orchestrateur d'extraction theses.fr.

Pas de réseau ni de base : un faux `ThesesExtractAdapter` sert des pages scriptées, et la connexion est un mock dont seul `commit` est appelé. Ce qui est éprouvé ici est le pilotage — une requête pour tous les établissements, pagination sur `totalHits`, filtre par année sur le préfixe du NNT, comptage du routage rendu par l'upsert, bilan, arrêt sur circuit-breaker.
"""

from __future__ import annotations

import argparse
import logging
from unittest.mock import MagicMock

import pytest

from application.pipeline.extract.base import ExtractionConfigError
from application.pipeline.extract.extract_theses import ThesesExtractor, extract_theses
from application.pipeline.progression import Progression
from application.ports.pipeline.extract._common import UpsertOutcome
from application.ports.pipeline.extract.theses import ThesesExtractConfig

_LOGGER = logging.getLogger("test")


def _adapter(pages: list[list[dict]], *, total: int | None = None) -> MagicMock:
    """Faux adapter servant `pages` successivement, chacune portant le `totalHits` de la recherche.

    Chaque thèse porte son identifiant en `id` et le sort que lui réserve l'upsert en `_route`.
    """
    a = MagicMock()
    a.build_query.return_value = "q"
    a.per_page.return_value = 100
    a.extract_id.side_effect = lambda these: these.get("id", "")
    a.upsert_these.side_effect = lambda conn, these: these["_route"]

    total_hits = total if total is not None else sum(len(p) for p in pages)
    a.fetch_page.side_effect = [{"totalHits": total_hits, "theses": p} for p in pages or [[]]]
    return a


def _these(identifiant: str, route: UpsertOutcome = UpsertOutcome.NEW) -> dict:
    return {"id": identifiant, "_route": route}


def _extraire(adapter: MagicMock, **kwargs) -> tuple[int, int, int, int]:
    return extract_theses(
        adapter, MagicMock(), ["PPN1"], _LOGGER, Progression(None, "theses.fr", None), **kwargs
    )


def test_pagination_jusqu_au_total():
    adapter = _adapter([[_these("2020AAA1"), _these("2020AAA2")], [_these("2020AAA3")]], total=3)
    assert _extraire(adapter) == (3, 3, 0, 0)
    assert [appel.kwargs["debut"] for appel in adapter.fetch_page.call_args_list] == [0, 2]


def test_routage_par_sort_de_l_upsert():
    adapter = _adapter(
        [
            [
                _these("2020A", UpsertOutcome.NEW),
                _these("2020B", UpsertOutcome.UPDATED),
                _these("2020C", UpsertOutcome.UNCHANGED),
            ]
        ]
    )
    assert _extraire(adapter) == (3, 1, 1, 1)


def test_filtre_annee_sur_le_prefixe_du_nnt():
    adapter = _adapter([[_these("2020AAA1"), _these("2021AAA1")]])
    avancement = Progression(None, "theses.fr", None, compte_retenus=True)
    total, nouveaux, _, _ = extract_theses(
        adapter, MagicMock(), ["PPN1"], _LOGGER, avancement, year=2021
    )
    assert (total, nouveaux) == (2, 1)
    assert avancement._retenus == 1


def test_these_sans_identifiant_ignoree():
    adapter = _adapter([[_these(""), _these("2020AAA1")]])
    assert _extraire(adapter)[1] == 1


def test_aucun_resultat():
    adapter = _adapter([], total=0)
    assert _extraire(adapter) == (0, 0, 0, 0)


def test_page_vide_interrompt_la_boucle():
    """`totalHits` annonce plus que ce que la source sert : la boucle s'arrête sans tourner à vide."""
    adapter = _adapter([[]], total=10)
    assert _extraire(adapter) == (10, 0, 0, 0)


def _extracteur(adapter: MagicMock, ppns: list[str]) -> ThesesExtractor:
    adapter.load_config.return_value = ThesesExtractConfig(base_url="https://example/", ppns=ppns)
    return ThesesExtractor(MagicMock(), _LOGGER, adapter)


def test_run_interroge_tous_les_etablissements_d_un_coup():
    adapter = _adapter([[_these("2020A"), _these("2020B")]])
    metrics = _extracteur(adapter, ["PPN1", "PPN2"]).run(argparse.Namespace(year=None))
    adapter.build_query.assert_called_once_with(["PPN1", "PPN2"])
    assert metrics.new == 2


def test_run_ecrit_le_bilan_au_feminin(caplog):
    adapter = _adapter([[_these("2020A"), _these("2020B", UpsertOutcome.UNCHANGED)]])
    with caplog.at_level(logging.INFO, logger=_LOGGER.name):
        _extracteur(adapter, ["PPN1"]).run(argparse.Namespace(year=None))
    assert "2 thèses trouvées : 1 nouvelle, 0 mise à jour, 1 inchangée" in caplog.text


def test_run_avec_une_annee_fait_le_bilan_des_theses_retenues(caplog):
    adapter = _adapter([[_these("2020A"), _these("2021A")]])
    with caplog.at_level(logging.INFO, logger=_LOGGER.name):
        _extracteur(adapter, ["PPN1"]).run(argparse.Namespace(year=2021))
    assert "1 thèse soutenue en 2021 : 1 nouvelle, 0 mise à jour, 0 inchangée" in caplog.text


def test_run_sans_ppn_configure_refuse():
    adapter = _adapter([], total=0)
    with pytest.raises(ExtractionConfigError, match="aucun PPN"):
        _extracteur(adapter, []).run(argparse.Namespace(year=None))


def test_run_s_arrete_quand_la_source_est_a_bout():
    """Le circuit-breaker tripé laisse les thèses au run suivant."""
    adapter = _adapter([[_these("2020A")]], total=1)
    breaker = MagicMock()
    breaker.tripped = True
    metrics = _extracteur(adapter, ["PPN1", "PPN2"]).run(
        argparse.Namespace(year=None), breaker=breaker
    )
    assert metrics.total == 0
    assert adapter.fetch_page.call_count == 0
