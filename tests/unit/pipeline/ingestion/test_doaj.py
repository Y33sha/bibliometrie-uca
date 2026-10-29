"""Contraintes du téléchargement du dump DOAJ : destination de la redirection et volume accepté.

C'est la seule requête sortante qui suive une redirection vers un autre hôte. La redirection mène seulement à des hôtes nommés, et la taille du corps reçu est bornée.
"""

import logging

import httpx2
import pytest

from pipeline.http.dump_download import DumpDownloadError, download_dump
from pipeline.ingestion.complements.doaj import (
    ALLOWED_DUMP_HOSTS,
    DOAJ_CSV_DUMP_URL,
    MAX_DUMP_BYTES,
)

_S3 = "https://doaj-live-journal-csv.s3.amazonaws.com/dump.csv"
_CSV = b"Journal title,ISSN\nRevue,1234-5678\n"

log = logging.getLogger(__name__)


def _fetch(tmp_path, *, max_bytes=MAX_DUMP_BYTES):
    dest = tmp_path / "dump.csv"
    download_dump(
        DOAJ_CSV_DUMP_URL,
        str(dest),
        label="DOAJ",
        user_agent="test",
        logger=log,
        max_bytes=max_bytes,
        allowed_redirect_hosts=ALLOWED_DUMP_HOSTS,
    )
    return dest


class TestCheminNominal:
    def test_suit_la_redirection_vers_le_stockage_objet(self, tmp_path, http_mock):
        http_mock.get(DOAJ_CSV_DUMP_URL).mock(
            return_value=httpx2.Response(302, headers={"location": _S3})
        )
        http_mock.get(_S3).mock(return_value=httpx2.Response(200, content=_CSV))
        assert _fetch(tmp_path).read_bytes() == _CSV

    def test_accepte_une_reponse_directe(self, tmp_path, http_mock):
        http_mock.get(DOAJ_CSV_DUMP_URL).mock(return_value=httpx2.Response(200, content=_CSV))
        assert _fetch(tmp_path).read_bytes() == _CSV


class TestDestinationDeLaRedirection:
    def test_refuse_un_hote_non_prevu_sans_le_joindre(self, tmp_path, http_mock):
        http_mock.get(DOAJ_CSV_DUMP_URL).mock(
            return_value=httpx2.Response(302, headers={"location": "https://ailleurs.example/x"})
        )
        ailleurs = http_mock.get("https://ailleurs.example/x").mock(
            return_value=httpx2.Response(200, content=b"charge")
        )
        with pytest.raises(DumpDownloadError, match="ailleurs.example"):
            _fetch(tmp_path)
        # Le contrôle précède la requête : aucune connexion n'est ouverte vers cet hôte.
        assert not ailleurs.called

    def test_refuse_une_redirection_sans_destination(self, tmp_path, http_mock):
        http_mock.get(DOAJ_CSV_DUMP_URL).mock(return_value=httpx2.Response(302))
        with pytest.raises(DumpDownloadError, match="sans destination"):
            _fetch(tmp_path)

    def test_refuse_une_redirection_circulaire(self, tmp_path, http_mock):
        http_mock.get(DOAJ_CSV_DUMP_URL).mock(
            return_value=httpx2.Response(302, headers={"location": DOAJ_CSV_DUMP_URL})
        )
        with pytest.raises(DumpDownloadError, match="redirections"):
            _fetch(tmp_path)


class TestVolumeAccepte:
    def test_refuse_un_corps_qui_depasse_le_plafond(self, tmp_path, http_mock):
        http_mock.get(DOAJ_CSV_DUMP_URL).mock(
            return_value=httpx2.Response(200, content=b"x" * 5000)
        )
        with pytest.raises(DumpDownloadError, match="plafond"):
            _fetch(tmp_path, max_bytes=1024)

    def test_accepte_un_corps_au_plafond(self, tmp_path, http_mock):
        http_mock.get(DOAJ_CSV_DUMP_URL).mock(
            return_value=httpx2.Response(200, content=b"x" * 1024)
        )
        assert len(_fetch(tmp_path, max_bytes=1024).read_bytes()) == 1024


class TestStatutDErreur:
    def test_un_statut_d_erreur_reste_une_erreur_http(self, tmp_path, http_mock):
        http_mock.get(DOAJ_CSV_DUMP_URL).mock(return_value=httpx2.Response(503))
        with pytest.raises(httpx2.HTTPStatusError):
            _fetch(tmp_path)
