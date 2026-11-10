"""Recherche dans OPS par numéro de la phase `fetch_missing` : sélection des numéros, famille trouvée par numéro de publication ou de demande (`pipeline.ingestion.ops.fetch_missing`)."""

import json
from pathlib import Path

import httpx2
import pytest

from pipeline.http.lookup import NotFound, Unavailable
from pipeline.http.pace import Pace
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.ops import api as ops_api
from pipeline.ingestion.ops.fetch_missing import fetch_by_number, get_missing_numbers
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_record, secondary_identifiers
from tests.integration.helpers.staging import insert_failed_lookup, insert_staging

PUBLICATION_NUMBER, APPLICATION_NUMBER = "patent_publication_number", "patent_application_number"
_OPS = API_BASE_URLS["ops"]
_SEARCH = f"{_OPS}/rest-services/published-data/search/biblio"
_FAMILY_PATH = f"{_OPS}/rest-services/family/publication/epodoc"
_APPLICATION_PATH = f"{_OPS}/rest-services/family/application/docdb"
_FAMILY = json.loads(
    (Path(__file__).parents[2] / "unit/pipeline/ingestion/ops/family_FR1658141.json").read_text()
)


def _record(conn, source, source_id, identifiers, *, publication_id=None, in_perimeter=True) -> int:
    """Crée un enregistrement source `source` rattaché à une publication, avec sa ligne de staging. Renvoie la publication."""
    publication_id = publication_id or insert_publication(conn, in_perimeter=in_perimeter)
    staging_id = insert_staging(conn, source, source_id=source_id)
    insert_source_record(
        conn,
        publication_id,
        source=source,
        source_id=source_id,
        title="titre test",
        staging_id=staging_id,
        identifiers=secondary_identifiers(identifiers),
    )
    return publication_id


def _missing(conn) -> dict[str, frozenset[str]]:
    return get_missing_numbers(conn, retry_after_days=30)


class TestGetMissingNumbers:
    def test_numeros_avec_leurs_types(self, sa_sync_conn):
        """Un même numéro WO peut être cherché comme publication et comme demande."""
        _record(
            sa_sync_conn,
            "hal",
            "hal-1",
            {
                PUBLICATION_NUMBER: ["FR3053353", "WO2017050584"],
                APPLICATION_NUMBER: ["FR1851441", "WO2017050584"],
            },
        )
        assert _missing(sa_sync_conn) == {
            "FR1851441": {APPLICATION_NUMBER},
            "FR3053353": {PUBLICATION_NUMBER},
            "WO2017050584": {PUBLICATION_NUMBER, APPLICATION_NUMBER},
        }

    def test_publication_hors_perimetre_ignoree(self, sa_sync_conn):
        _record(
            sa_sync_conn, "hal", "hal-1", {PUBLICATION_NUMBER: ["FR3053353"]}, in_perimeter=False
        )
        assert _missing(sa_sync_conn) == {}

    def test_publication_avec_famille_ignoree(self, sa_sync_conn):
        publication_id = _record(sa_sync_conn, "hal", "hal-1", {APPLICATION_NUMBER: ["EP22306008"]})
        _record(sa_sync_conn, "ops", "EP22306008", {}, publication_id=publication_id)
        assert _missing(sa_sync_conn) == {}

    def test_numero_d_une_famille_en_base_ignore(self, sa_sync_conn):
        _record(sa_sync_conn, "hal", "hal-1", {PUBLICATION_NUMBER: ["FR3053353"]})
        _record(sa_sync_conn, "ops", "FR1656171", {PUBLICATION_NUMBER: ["FR3053353"]})
        assert _missing(sa_sync_conn) == {}

    def test_numero_cherche_en_vain_puis_de_nouveau_apres_le_delai(self, sa_sync_conn):
        _record(
            sa_sync_conn,
            "hal",
            "hal-1",
            {PUBLICATION_NUMBER: ["FR3053353"], APPLICATION_NUMBER: ["FR1851441"]},
        )
        insert_failed_lookup(sa_sync_conn, "ops", id_type=PUBLICATION_NUMBER, id_value="FR3053353")
        insert_failed_lookup(
            sa_sync_conn,
            "ops",
            id_type=APPLICATION_NUMBER,
            id_value="FR1851441",
            not_found_days_ago=60,
        )
        assert _missing(sa_sync_conn) == {"FR1851441": {APPLICATION_NUMBER}}


def _search_result(publication: str) -> dict:
    country, number = publication[:2], publication[2:]
    return {
        "ops:world-patent-data": {
            "ops:biblio-search": {
                "@total-result-count": "1",
                "ops:search-result": {
                    "exchange-documents": {
                        "exchange-document": {
                            "@family-id": "1",
                            "@country": country,
                            "@doc-number": number,
                        }
                    }
                },
            }
        }
    }


class TestFetchByNumber:
    @pytest.fixture(autouse=True)
    def _token_and_pace(self, http_mock, monkeypatch):
        http_mock.post(f"{_OPS}/auth/accesstoken").mock(
            return_value=httpx2.Response(200, json={"access_token": "t", "expires_in": "1199"})
        )
        monkeypatch.setattr(ops_api, "_SEARCH_PACE", Pace(1000))

    @pytest.mark.asyncio
    async def test_famille_d_un_numero_de_publication(self, http_mock):
        http_mock.get(f"{_FAMILY_PATH}/FR3055338/biblio").mock(
            return_value=httpx2.Response(200, json=_FAMILY)
        )
        async with httpx2.AsyncClient() as client:
            found = await fetch_by_number(client, "FR3055338", frozenset({PUBLICATION_NUMBER}))
        assert not isinstance(found, NotFound)
        assert found["id"] == "FR1658141"

    @pytest.mark.asyncio
    async def test_famille_d_un_numero_de_demande_sans_recherche(self, http_mock):
        http_mock.get(f"{_APPLICATION_PATH}/FR.1658141/biblio").mock(
            return_value=httpx2.Response(200, json=_FAMILY)
        )
        search = http_mock.get(_SEARCH)
        async with httpx2.AsyncClient() as client:
            found = await fetch_by_number(client, "FR1658141", frozenset({APPLICATION_NUMBER}))
        assert not isinstance(found, NotFound) and found["id"] == "FR1658141"
        assert search.call_count == 0

    @pytest.mark.asyncio
    async def test_priorite_jamais_publiee_trouvee_par_la_recherche(self, http_mock):
        """Une priorité jamais publiée est absente des demandes et trouvée parmi les priorités (`pr`)."""
        http_mock.get(f"{_APPLICATION_PATH}/FR.1658141/biblio").mock(
            return_value=httpx2.Response(404, text="SERVER.EntityNotFound")
        )
        search = http_mock.get(_SEARCH).mock(
            return_value=httpx2.Response(200, json=_search_result("WO2018041749"))
        )
        http_mock.get(f"{_FAMILY_PATH}/WO2018041749/biblio").mock(
            return_value=httpx2.Response(200, json=_FAMILY)
        )
        async with httpx2.AsyncClient() as client:
            found = await fetch_by_number(client, "FR1658141", frozenset({APPLICATION_NUMBER}))
        assert search.call_count == 1
        assert not isinstance(found, NotFound) and found["id"] == "FR1658141"

    @pytest.mark.asyncio
    async def test_famille_sans_le_numero_cherche_ecartee(self, http_mock):
        http_mock.get(f"{_APPLICATION_PATH}/FR.9999999/biblio").mock(
            return_value=httpx2.Response(404, text="SERVER.EntityNotFound")
        )
        http_mock.get(_SEARCH).mock(
            return_value=httpx2.Response(200, json=_search_result("WO2018041749"))
        )
        http_mock.get(f"{_FAMILY_PATH}/WO2018041749/biblio").mock(
            return_value=httpx2.Response(200, json=_FAMILY)
        )
        async with httpx2.AsyncClient() as client:
            found = await fetch_by_number(client, "FR9999999", frozenset({APPLICATION_NUMBER}))
        assert isinstance(found, NotFound)

    @pytest.mark.asyncio
    async def test_recherche_saturee_abandonnee_sans_attente(self, http_mock):
        """Feu noir sur la recherche : le numéro attend le run suivant, sans pause."""
        http_mock.get(f"{_APPLICATION_PATH}/FR.1658141/biblio").mock(
            return_value=httpx2.Response(404, text="SERVER.EntityNotFound")
        )
        search = http_mock.get(_SEARCH).mock(
            return_value=httpx2.Response(
                403,
                text="<code>CLIENT.RobotDetected</code>",
                headers={"X-Throttling-Control": "overloaded (search=black:0)"},
            )
        )
        async with httpx2.AsyncClient() as client:
            found = await fetch_by_number(client, "FR1658141", frozenset({APPLICATION_NUMBER}))
        assert isinstance(found, Unavailable)
        assert search.call_count == 1
