"""Tests du client Sudoc : composition des requêtes `issn2ppn`, lecture des réponses et des notices MARCXML."""

import httpx2
import pytest

from domain.journals.issns import IssnSupport
from infrastructure.sources.sudoc import client

_BASE = "https://www.sudoc.fr"

_NOTICE = """<?xml version="1.0" encoding="UTF-8"?>
<record>
  <controlfield tag="001">068267983</controlfield>
  <datafield tag="011" ind1="#" ind2="#">
    <subfield code="a">1476-4687</subfield>
    <subfield code="f">0028-0836</subfield>
  </datafield>
  <datafield tag="182" ind1="#" ind2="#"><subfield code="c">c</subfield></datafield>
  <datafield tag="183" ind1="#" ind2="#"><subfield code="a">ceb</subfield></datafield>
  <datafield tag="200" ind1="1" ind2="#"><subfield code="a">Nature</subfield></datafield>
</record>
"""


def _not_found(url: str) -> httpx2.HTTPStatusError:
    return httpx2.HTTPStatusError(
        "404", request=httpx2.Request("GET", url), response=httpx2.Response(404)
    )


def _answer(value):
    async def fake(*args, **kwargs):
        return value(*args) if callable(value) else value

    return fake


class TestFetchPpns:
    @pytest.mark.asyncio
    async def test_reads_every_query_of_the_batch(self, monkeypatch):
        urls = []

        async def fake(http_client, method, url, **kwargs):
            urls.append(url)
            return {
                "sudoc": [
                    {"query": {"issn": "0028-0836", "result": {"ppn": "038758717"}}},
                    {"query": {"issn": "1476-4687", "result": [{"ppn": "068267983"}]}},
                ]
            }

        monkeypatch.setattr(client, "http_request_with_retry_async", fake)
        assert await client.fetch_ppns(None, ["0028-0836", "1476-4687"], base_url=_BASE) == {
            "0028-0836": ("038758717",),
            "1476-4687": ("068267983",),
        }
        # Le format de réponse se donne dans le chemin.
        assert urls == [f"{_BASE}/services/issn2ppn/0028-0836,1476-4687&format=text/json"]

    @pytest.mark.asyncio
    async def test_single_query_answer(self, monkeypatch):
        monkeypatch.setattr(
            client,
            "http_request_with_retry_async",
            _answer({"sudoc": {"query": {"issn": "0028-0836", "result": {"ppn": "038758717"}}}}),
        )
        assert await client.fetch_ppns(None, ["0028-0836"], base_url=_BASE) == {
            "0028-0836": ("038758717",)
        }

    @pytest.mark.asyncio
    async def test_batch_without_any_record(self, monkeypatch):
        async def fake(http_client, method, url, **kwargs):
            raise _not_found(url)

        monkeypatch.setattr(client, "http_request_with_retry_async", fake)
        assert await client.fetch_ppns(None, ["2710-1309"], base_url=_BASE) == {}

    @pytest.mark.asyncio
    async def test_splits_into_batches(self, monkeypatch):
        urls = []

        async def fake(http_client, method, url, **kwargs):
            urls.append(url)
            return {"sudoc": []}

        monkeypatch.setattr(client, "http_request_with_retry_async", fake)
        monkeypatch.setattr(client, "SUDOC_ISSN2PPN_BATCH", 2)
        await client.fetch_ppns(None, ["0028-0836", "1476-4687", "0036-8075"], base_url=_BASE)
        assert len(urls) == 2


class TestMarcFields:
    def test_reads_datafields_in_order(self):
        fields = client.marc_fields(_NOTICE)
        assert [f.tag for f in fields] == ["011", "182", "183", "200"]
        assert fields[0].subfields == (("a", "1476-4687"), ("f", "0028-0836"))

    def test_reads_namespaced_record(self):
        xml = _NOTICE.replace("<record>", '<record xmlns="http://www.loc.gov/MARC21/slim">')
        assert [f.tag for f in client.marc_fields(xml)] == ["011", "182", "183", "200"]


class TestFetchSerialRecord:
    @pytest.mark.asyncio
    async def test_parses_the_record(self, monkeypatch):
        monkeypatch.setattr(client, "http_get_text_with_retry_async", _answer(_NOTICE))
        record = await client.fetch_serial_record(None, "068267983", base_url=_BASE)
        assert record is not None
        assert record.issn == "1476-4687"
        assert record.issnl == "0028-0836"
        assert record.support is IssnSupport.ELECTRONIC

    @pytest.mark.asyncio
    async def test_unknown_ppn(self, monkeypatch):
        async def fake(http_client, url, **kwargs):
            raise _not_found(url)

        monkeypatch.setattr(client, "http_get_text_with_retry_async", fake)
        assert await client.fetch_serial_record(None, "000000000", base_url=_BASE) is None

    @pytest.mark.asyncio
    async def test_entity_declaration_is_refused(self, monkeypatch):
        """`defusedxml` refuse les déclarations d'entités : la notice est tenue pour illisible."""
        xml = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY e "x">]><record>&e;</record>'
        monkeypatch.setattr(client, "http_get_text_with_retry_async", _answer(xml))
        assert await client.fetch_serial_record(None, "1", base_url=_BASE) is None
