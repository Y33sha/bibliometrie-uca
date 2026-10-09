"""Lecture et téléchargement du dump ROR."""

import csv
import io
import logging
import zipfile

import httpx2
import pytest

from domain.structures.identifiers import RorId
from domain.structures.ror import RorStatus, RorType
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.dump_download import DumpDownloadError
from infrastructure.sources.ror.dump import (
    fetch_ror_dump,
    find_latest_ror_dump,
    parse_ror_row,
    read_ror_dump,
)

log = logging.getLogger(__name__)

_ARCHIVE_URL = "https://zenodo.org/api/records/1/files/v2.14-2026-10-06-ror-data.zip/content"

_ROW = {
    "id": "https://ror.org/01bch8q67",
    "names.types.ror_display": "Observatoire de Physique du Globe de Clermont-Ferrand",
    "locations.geonames_details.country_code": "FR",
    "types": "education; facility",
    "status": "active",
    "relationships": (
        "child: https://ror.org/03gz4y884, https://ror.org/02vnq7240; "
        "parent: https://ror.org/04kdfz702"
    ),
}


def _zenodo_body(files):
    return {"hits": {"hits": [{"metadata": {"title": "ROR Data v2.14"}, "files": files}]}}


def _archive_file(url=_ARCHIVE_URL):
    return {"key": "v2.14-2026-10-06-ror-data.zip", "links": {"self": url}}


class TestParseRorRow:
    def test_lit_une_ligne_complete(self):
        org = parse_ror_row(_ROW)
        assert org.ror_id == RorId("01bch8q67")
        assert org.name == "Observatoire de Physique du Globe de Clermont-Ferrand"
        assert org.country_code == "fr"
        assert org.types == {RorType.EDUCATION, RorType.FACILITY}
        assert org.status is RorStatus.ACTIVE
        assert org.parent_ids == {RorId("04kdfz702")}
        assert org.child_ids == {RorId("03gz4y884"), RorId("02vnq7240")}

    def test_lit_une_ligne_sans_relation(self):
        org = parse_ror_row({**_ROW, "relationships": ""})
        assert org.parent_ids == frozenset()
        assert org.child_ids == frozenset()

    def test_refuse_un_type_inconnu(self):
        with pytest.raises(ValueError):
            parse_ror_row({**_ROW, "types": "laboratory"})


class TestReadRorDump:
    def test_lit_le_csv_de_l_archive(self, tmp_path):
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(_ROW))
        writer.writeheader()
        writer.writerow(_ROW)
        archive = tmp_path / "dump.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("v2.14-2026-10-06-ror-data.csv", buffer.getvalue())
            z.writestr("v2.14-2026-10-06-ror-data.json", "[]")
        assert [o.ror_id for o in read_ror_dump(str(archive))] == [RorId("01bch8q67")]


class TestFindLatestRorDump:
    def test_rend_l_archive_de_la_derniere_version(self, http_mock):
        http_mock.get(API_BASE_URLS["zenodo_ror"]).mock(
            return_value=httpx2.Response(200, json=_zenodo_body([_archive_file()]))
        )
        dump = find_latest_ror_dump(user_agent="test")
        assert dump.title == "ROR Data v2.14"
        assert dump.url == _ARCHIVE_URL

    def test_refuse_une_archive_hors_de_zenodo(self, http_mock):
        http_mock.get(API_BASE_URLS["zenodo_ror"]).mock(
            return_value=httpx2.Response(
                200, json=_zenodo_body([_archive_file("https://ailleurs.example/dump.zip")])
            )
        )
        with pytest.raises(DumpDownloadError, match="hors de zenodo.org"):
            find_latest_ror_dump(user_agent="test")

    def test_refuse_une_version_sans_archive(self, http_mock):
        http_mock.get(API_BASE_URLS["zenodo_ror"]).mock(
            return_value=httpx2.Response(200, json=_zenodo_body([]))
        )
        with pytest.raises(DumpDownloadError, match="Aucune archive"):
            find_latest_ror_dump(user_agent="test")


class TestFetchRorDump:
    def test_ecrit_l_archive(self, tmp_path, http_mock):
        http_mock.get(API_BASE_URLS["zenodo_ror"]).mock(
            return_value=httpx2.Response(200, json=_zenodo_body([_archive_file()]))
        )
        http_mock.get(_ARCHIVE_URL).mock(return_value=httpx2.Response(200, content=b"zip"))
        dest = tmp_path / "dump.zip"
        fetch_ror_dump(str(dest), user_agent="test", logger=log)
        assert dest.read_bytes() == b"zip"

    def test_refuse_une_redirection(self, tmp_path, http_mock):
        http_mock.get(API_BASE_URLS["zenodo_ror"]).mock(
            return_value=httpx2.Response(200, json=_zenodo_body([_archive_file()]))
        )
        http_mock.get(_ARCHIVE_URL).mock(
            return_value=httpx2.Response(302, headers={"location": "https://ailleurs.example/"})
        )
        with pytest.raises(httpx2.HTTPStatusError):
            fetch_ror_dump(str(tmp_path / "dump.zip"), user_agent="test", logger=log)
