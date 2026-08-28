"""Contraintes du téléchargement du dump DOAJ : destination de la redirection et volume accepté.

C'est la seule requête sortante du projet qui suive une redirection. Deux propriétés en découlent, qu'on veut tenues par des tests plutôt que par la confiance accordée à la source : la redirection ne mène qu'à des hôtes nommés, et le corps reçu est borné.
"""

import logging

import httpx
import pytest
import respx

from infrastructure.sources.doaj.client import (
    DOAJ_CSV_DUMP_URL,
    DoajDumpError,
    fetch_doaj_dump,
)

_S3 = "https://doaj-live-journal-csv.s3.amazonaws.com/dump.csv"
_CSV = b"Journal title,ISSN\nRevue,1234-5678\n"

log = logging.getLogger(__name__)


def _fetch(tmp_path, **kwargs):
    dest = tmp_path / "dump.csv"
    fetch_doaj_dump(str(dest), user_agent="test", logger=log, **kwargs)
    return dest


class TestCheminNominal:
    @respx.mock
    def test_suit_la_redirection_vers_le_stockage_objet(self, tmp_path):
        respx.get(DOAJ_CSV_DUMP_URL).mock(
            return_value=httpx.Response(302, headers={"location": _S3})
        )
        respx.get(_S3).mock(return_value=httpx.Response(200, content=_CSV))
        assert _fetch(tmp_path).read_bytes() == _CSV

    @respx.mock
    def test_accepte_une_reponse_directe(self, tmp_path):
        respx.get(DOAJ_CSV_DUMP_URL).mock(return_value=httpx.Response(200, content=_CSV))
        assert _fetch(tmp_path).read_bytes() == _CSV


class TestDestinationDeLaRedirection:
    @respx.mock
    def test_refuse_un_hote_non_prevu_sans_le_joindre(self, tmp_path):
        respx.get(DOAJ_CSV_DUMP_URL).mock(
            return_value=httpx.Response(302, headers={"location": "https://ailleurs.example/x"})
        )
        ailleurs = respx.get("https://ailleurs.example/x").mock(
            return_value=httpx.Response(200, content=b"charge")
        )
        with pytest.raises(DoajDumpError, match="ailleurs.example"):
            _fetch(tmp_path)
        # Le contrôle précède la requête : aucune connexion n'est ouverte vers cet hôte.
        assert not ailleurs.called

    @respx.mock
    def test_refuse_une_redirection_sans_destination(self, tmp_path):
        respx.get(DOAJ_CSV_DUMP_URL).mock(return_value=httpx.Response(302))
        with pytest.raises(DoajDumpError, match="sans destination"):
            _fetch(tmp_path)

    @respx.mock
    def test_refuse_une_redirection_circulaire(self, tmp_path):
        respx.get(DOAJ_CSV_DUMP_URL).mock(
            return_value=httpx.Response(302, headers={"location": DOAJ_CSV_DUMP_URL})
        )
        with pytest.raises(DoajDumpError, match="redirections"):
            _fetch(tmp_path)


class TestVolumeAccepte:
    @respx.mock
    def test_refuse_un_corps_qui_depasse_le_plafond(self, tmp_path):
        respx.get(DOAJ_CSV_DUMP_URL).mock(return_value=httpx.Response(200, content=b"x" * 5000))
        with pytest.raises(DoajDumpError, match="plafond"):
            _fetch(tmp_path, max_bytes=1024)

    @respx.mock
    def test_accepte_un_corps_au_plafond(self, tmp_path):
        respx.get(DOAJ_CSV_DUMP_URL).mock(return_value=httpx.Response(200, content=b"x" * 1024))
        assert len(_fetch(tmp_path, max_bytes=1024).read_bytes()) == 1024


class TestStatutDErreur:
    @respx.mock
    def test_un_statut_d_erreur_reste_une_erreur_http(self, tmp_path):
        respx.get(DOAJ_CSV_DUMP_URL).mock(return_value=httpx.Response(503))
        with pytest.raises(httpx.HTTPStatusError):
            _fetch(tmp_path)
