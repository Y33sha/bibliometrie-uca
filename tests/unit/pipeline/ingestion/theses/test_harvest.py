"""Moissonnage theses.fr (`pipeline.ingestion.theses.harvest`) et champs des thèses.

Requête et champs : fonctions pures. Liste des thèses : une requête pour tous les établissements, pagination sur `totalHits`, filtre sur les années de la fenêtre par le préfixe du NNT. Pilotage : seul le détail des thèses absentes de `staging` est lu, puis le bilan. Pas de réseau ni de base : un faux client sert des pages scriptées, la configuration, les thèses présentes et la lecture du détail sont simulées.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from pipeline.ingestion.common.harvester import HarvestConfigError
from pipeline.ingestion.theses import harvest
from pipeline.ingestion.theses.fields import extract_doi, extract_id, is_ongoing, listed_id
from pipeline.ingestion.theses.harvest import ThesesHarvester, build_query, list_theses
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress
from tests.helpers.harvesters import arguments_du_run, moissonneur

_LOGGER = logging.getLogger("test")


class TestBuildQuery:
    def test_un_ppn(self):
        assert build_query(["196200032"]) == "etabSoutenancePpn:(196200032)"

    def test_plusieurs_ppn_en_une_requete(self):
        assert build_query(["196200032", "252404955"]) == (
            "etabSoutenancePpn:(196200032 OR 252404955)"
        )


class TestFields:
    def test_identifiant_dans_la_recherche(self):
        assert listed_id({"id": "2021UCFAC022", "nnt": "2021UCFAC022"}) == "2021UCFAC022"
        assert listed_id({}) == ""

    def test_identifiant_du_detail(self):
        assert extract_id({"nnt": "2021UCFAC022", "numSujet": None}) == "2021UCFAC022"
        assert extract_id({"nnt": None, "numSujet": "s367812"}) == "s367812"
        assert extract_id({}) == ""

    def test_is_ongoing(self):
        assert is_ongoing({"id": "s367812", "status": "enCours"}) is True
        assert is_ongoing({"id": "2021UCFAC022", "status": "soutenue"}) is False

    def test_extract_doi(self):
        assert extract_doi({"doi": "  10.1000/abc  "}) == "10.1000/abc"
        assert extract_doi({}) is None
        assert extract_doi({"doi": ""}) is None
        assert extract_doi({"doi": "   "}) is None
        assert extract_doi({"doi": 12345}) is None


def _these(identifiant: str, **champs) -> dict:
    return {"id": identifiant, **champs}


def _client(pages: list[list[dict]], *, total: int | None = None) -> MagicMock:
    """Faux client servant `pages` successivement, chacune portant le `totalHits` de la recherche."""
    client = MagicMock()
    total_hits = total if total is not None else sum(len(p) for p in pages)
    client.fetch_page.side_effect = [{"totalHits": total_hits, "theses": p} for p in pages or [[]]]
    return client


def _lister(client: MagicMock, *, progress: Progress | None = None, years=(2020,)):
    return list_theses(
        client, ["PPN1"], progress or Progress(None, "theses.fr", None), years=list(years)
    )


def test_pagination_jusqu_au_total():
    client = _client([[_these("2020AAA1"), _these("2020AAA2")], [_these("2020AAA3")]], total=3)
    assert _lister(client) == (3, ["2020AAA1", "2020AAA2", "2020AAA3"])
    assert [appel.kwargs["start"] for appel in client.fetch_page.call_args_list] == [0, 2]


def test_filtre_annee_sur_le_prefixe_du_nnt():
    progress = Progress(None, "theses.fr", None, count_kept=True)
    client = _client([[_these("2020AAA1"), _these("2021AAA1")]])
    assert _lister(client, progress=progress, years=[2021]) == (2, ["2021AAA1"])
    assert progress._kept == 1


def test_la_fenetre_retient_plusieurs_annees():
    client = _client([[_these("2019A"), _these("2020A"), _these("2021A")]])
    assert _lister(client, years=[2020, 2021])[1] == ["2020A", "2021A"]


def test_une_annee_retient_aussi_les_theses_en_cours():
    """Une thèse en cours n'a pas d'année dans son identifiant : elle est retenue quelle que soit la fenêtre."""
    client = _client([[_these("2020A"), _these("2021A"), _these("s367812", status="enCours")]])
    assert _lister(client, years=[2021])[1] == ["2021A", "s367812"]


def test_these_sans_identifiant_ignoree():
    assert _lister(_client([[_these(""), _these("2020AAA1")]]))[1] == ["2020AAA1"]


def test_page_vide_interrompt_la_boucle():
    """`totalHits` annonce plus que ce que la source sert : la boucle s'arrête sans tourner à vide."""
    assert _lister(_client([[]], total=10)) == (10, [])


@pytest.fixture
def details(monkeypatch):
    """Simule les thèses présentes dans `staging` (`presentes`) et la lecture du détail. Rend les identifiants dont le détail est lu, et `presentes`."""
    lus: list[str] = []
    presentes: set[str] = set()

    def _stage_details(conn, log, theses_ids):
        lus.extend(theses_ids)
        return PhaseMetrics(seen=len(theses_ids), new=len(theses_ids))

    monkeypatch.setattr(harvest, "staged_theses_ids", lambda conn: set(presentes))
    monkeypatch.setattr(harvest, "stage_details", _stage_details)
    return lus, presentes


def test_seul_le_detail_des_theses_absentes_est_lu(configuration, details):
    """Le détail d'une thèse présente dans `staging` reste à la relecture par `fetch_stale`."""
    configuration(harvest, annees=[2020])
    lus, presentes = details
    presentes.add("2020A")
    client = _client([[_these("2020A"), _these("2020B")]])
    metrics = moissonneur(ThesesHarvester, client).run(arguments_du_run())
    assert lus == ["2020B"]
    assert (metrics.new, metrics.unchanged) == (1, 1)


def test_run_interroge_tous_les_etablissements_d_un_coup(configuration, details):
    configuration(harvest, api_ids=["PPN1", "PPN2"], annees=[2020])
    client = _client([[_these("2020A"), _these("2020B")]])
    assert moissonneur(ThesesHarvester, client).run(arguments_du_run()).new == 2
    assert client.fetch_page.call_args.args[0] == build_query(["PPN1", "PPN2"])


def test_run_ecrit_le_bilan_au_feminin(configuration, details, caplog):
    configuration(harvest, annees=[2020])
    details[1].add("2020B")
    client = _client([[_these("2020A"), _these("2020B")]])
    with caplog.at_level(logging.INFO, logger=_LOGGER.name):
        moissonneur(ThesesHarvester, client).run(arguments_du_run())
    assert "2 thèses trouvées : 1 nouvelle, 0 mise à jour, 1 inchangée" in caplog.text


def test_run_avec_une_annee_fait_le_bilan_des_theses_retenues(configuration, details, caplog):
    configuration(harvest)
    client = _client([[_these("2020A"), _these("2021A")]])
    with caplog.at_level(logging.INFO, logger=_LOGGER.name):
        moissonneur(ThesesHarvester, client).run(arguments_du_run(year=2021))
    assert "1 thèse trouvée : 1 nouvelle, 0 mise à jour, 0 inchangée" in caplog.text


def test_run_sans_ppn_configure_refuse(configuration):
    configuration(harvest, api_ids=[])
    with pytest.raises(HarvestConfigError, match="aucun PPN"):
        moissonneur(ThesesHarvester, _client([])).run(arguments_du_run())
