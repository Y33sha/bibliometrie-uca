"""Recherche dans ScanR brevets par numéro de la phase `fetch_missing` : sélection des numéros, requête Elasticsearch (`pipeline.ingestion.scanr_patents.fetch_missing`)."""

import httpx2
import pytest

from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.scanr_patents.fetch_missing import get_missing_numbers, search_numbers
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_record, secondary_identifiers
from tests.integration.helpers.staging import insert_failed_lookup, insert_staging

PUB, APP = "patent_publication_number", "patent_application_number"


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
            {PUB: ["FR3053353", "WO2017050584"], APP: ["FR1851441", "WO2017050584"]},
        )
        assert _missing(sa_sync_conn) == {
            "FR1851441": {APP},
            "FR3053353": {PUB},
            "WO2017050584": {PUB, APP},
        }

    def test_publication_hors_perimetre_ignoree(self, sa_sync_conn):
        _record(sa_sync_conn, "hal", "hal-1", {PUB: ["FR3053353"]}, in_perimeter=False)
        assert _missing(sa_sync_conn) == {}

    def test_publication_avec_famille_ignoree(self, sa_sync_conn):
        """Le dépôt HAL cite une demande de priorité absente de la liste des demandes de sa famille."""
        publication_id = _record(sa_sync_conn, "hal", "hal-1", {APP: ["EP22306008"]})
        _record(sa_sync_conn, "scanr_patents", "1", {}, publication_id=publication_id)
        assert _missing(sa_sync_conn) == {}

    def test_numero_d_une_famille_en_base_ignore(self, sa_sync_conn):
        _record(sa_sync_conn, "hal", "hal-1", {PUB: ["FR3053353"]})
        _record(sa_sync_conn, "scanr_patents", "1", {PUB: ["FR3053353"]})
        assert _missing(sa_sync_conn) == {}

    def test_numero_cherche_en_vain_puis_de_nouveau_apres_le_delai(self, sa_sync_conn):
        _record(sa_sync_conn, "hal", "hal-1", {PUB: ["FR3053353"], APP: ["FR1851441"]})
        insert_failed_lookup(sa_sync_conn, "scanr_patents", id_type=PUB, id_value="FR3053353")
        insert_failed_lookup(
            sa_sync_conn, "scanr_patents", id_type=APP, id_value="FR1851441", not_found_days_ago=60
        )
        assert _missing(sa_sync_conn) == {"FR1851441": {APP}}


def _family(family_id: str, *applications: tuple[str, str, str]) -> dict:
    """Famille ScanR, une demande par triplet (office, numéro de demande, numéro de publication)."""
    patents = [
        {"office": office, "applicationNumber": filed, "publicationNumber": published}
        for office, filed, published in applications
    ]
    return {"_source": {"id": family_id, "patents": patents}}


class TestSearchNumbers:
    @pytest.mark.asyncio
    async def test_famille_gardee_si_elle_a_le_numero_cherche(self, http_mock):
        """Le préfixe `3053353` renvoie aussi une famille au numéro `30533531` : elle est écartée."""
        http_mock.post(API_BASE_URLS["scanr_patents"]).mock(
            return_value=httpx2.Response(
                200,
                json={
                    "hits": {
                        "hits": [
                            _family("1", ("FR", "1656001", "3053353A1")),
                            _family("2", ("FR", "9900001", "30533531A1")),
                        ]
                    }
                },
            )
        )
        async with httpx2.AsyncClient() as client:
            batch = await search_numbers(
                client, {"FR3053353": frozenset({PUB}), "WO2018002556": frozenset({PUB})}
            )
        assert [f["id"] for f in batch.records] == ["1"]
        assert batch.absent == ["WO2018002556"]

    @pytest.mark.asyncio
    async def test_numero_de_demande_sous_son_office(self, http_mock):
        """Un numéro de demande d'un autre office est écarté."""
        http_mock.post(API_BASE_URLS["scanr_patents"]).mock(
            return_value=httpx2.Response(
                200, json={"hits": {"hits": [_family("1", ("EP", "1851441", "3000000A1"))]}}
            )
        )
        async with httpx2.AsyncClient() as client:
            batch = await search_numbers(client, {"FR1851441": frozenset({APP})})
        assert batch.records == []
        assert batch.absent == ["FR1851441"]

    @pytest.mark.asyncio
    async def test_numeros_des_deux_types_dans_une_requete(self, http_mock):
        """Un numéro de publication et un numéro de demande trouvent chacun leur famille ; un numéro cherché sous un type est écarté sous l'autre."""
        route = http_mock.post(API_BASE_URLS["scanr_patents"]).mock(
            return_value=httpx2.Response(
                200,
                json={
                    "hits": {
                        "hits": [
                            _family("1", ("FR", "1656001", "3053353A1")),
                            _family("2", ("FR", "1851441", "3078190A1")),
                            _family("3", ("WO", "2017050584", "2017999999A1")),
                        ]
                    }
                },
            )
        )
        async with httpx2.AsyncClient() as client:
            batch = await search_numbers(
                client,
                {
                    "FR3053353": frozenset({PUB}),
                    "FR1851441": frozenset({APP}),
                    "WO2017050584": frozenset({PUB}),
                },
            )
        assert route.call_count == 1
        assert [f["id"] for f in batch.records] == ["1", "2"]
        assert batch.absent == ["WO2017050584"]
