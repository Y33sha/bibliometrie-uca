"""Rafraîchissement du référentiel ROR : import seulement d'une version non importée, référentiel inchangé si le dump est inaccessible."""

import logging
from unittest.mock import MagicMock

from pipeline.ingestion.http.dump_download import DumpUnavailableError
from pipeline.transformation.structures.ror import run_refresh_ror

_LOG = logging.getLogger("test")


class _FakeSource:
    def __init__(self, latest="v2.14-2026-10-06-ror-data.zip", error=None, published=None):
        self.latest, self.error, self.published, self.read = latest, error, published, []
        self.zenodo_calls = 0

    def published_version(self):
        return self.published

    def latest_version(self):
        self.zenodo_calls += 1
        if self.error:
            raise self.error
        return self.latest

    def organizations(self, version):
        self.read.append(version)
        return iter([])


def _repo(last):
    repo = MagicMock()
    repo.last_imported_version.return_value = last
    return repo


def test_version_deja_importee_laissee_en_l_etat():
    source, repo = _FakeSource(), _repo("v2.14-2026-10-06-ror-data.zip")
    metrics = run_refresh_ror(MagicMock(), source=source, repo=repo, logger=_LOG)
    assert source.read == []
    repo.replace_all.assert_not_called()
    assert metrics.details["ror"]["imported"] is False


def test_version_publiee_deja_importee_sans_interroger_zenodo():
    source = _FakeSource(published="v2.14")
    repo = _repo("v2.14-2026-10-06-ror-data.zip")
    metrics = run_refresh_ror(MagicMock(), source=source, repo=repo, logger=_LOG)
    assert source.zenodo_calls == 0
    assert metrics.details["ror"] == {"version": "v2.14-2026-10-06-ror-data.zip", "imported": False}


def test_version_publiee_differente_interroge_zenodo():
    source = _FakeSource(published="v2.15", latest="v2.15-2026-11-03-ror-data.zip")
    repo = _repo("v2.14-2026-10-06-ror-data.zip")
    run_refresh_ror(MagicMock(), source=source, repo=repo, logger=_LOG)
    assert source.zenodo_calls == 1
    assert source.read == ["v2.15-2026-11-03-ror-data.zip"]


def test_version_plus_recente_importee():
    source, repo = _FakeSource(), _repo("v2.13-2026-09-01-ror-data.zip")
    metrics = run_refresh_ror(MagicMock(), source=source, repo=repo, logger=_LOG)
    assert source.read == ["v2.14-2026-10-06-ror-data.zip"]
    repo.replace_all.assert_called_once()
    assert repo.replace_all.call_args.kwargs["version"] == "v2.14-2026-10-06-ror-data.zip"
    assert metrics.details["ror"] == {"version": "v2.14-2026-10-06-ror-data.zip", "imported": True}


def test_dump_inaccessible_laisse_le_referentiel_inchange():
    conn = MagicMock()
    source, repo = _FakeSource(error=DumpUnavailableError("HTTP 502")), _repo(None)
    metrics = run_refresh_ror(conn, source=source, repo=repo, logger=_LOG)
    repo.replace_all.assert_not_called()
    conn.rollback.assert_called_once()
    assert metrics.details["ror"] == {"imported": False, "error": "HTTP 502"}
