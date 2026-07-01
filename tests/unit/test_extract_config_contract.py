"""Contrat de configuration par source d'extraction (couche application).

Chaque orchestrateur lève `ExtractionConfigError` quand la source n'est pas
configurée pour extraire : identifiants de structure absents, ou credentials
manquants (clé WoS, credentials ScanR, ni clé ni email pour OpenAlex, aucune
collection HAL). Pour OpenAlex, la clé API ou l'email polite pool suffit — l'un
des deux.
"""

import logging
from types import SimpleNamespace

import pytest

from application.pipeline.extract.base import ExtractionConfigError
from application.pipeline.extract.extract_hal import HalExtractor
from application.pipeline.extract.extract_openalex import OpenalexExtractor
from application.pipeline.extract.extract_scanr import ScanrExtractor
from application.pipeline.extract.extract_wos import WosExtractor
from application.ports.pipeline.extract.hal import HalExtractConfig
from application.ports.pipeline.extract.openalex import OpenalexExtractConfig
from application.ports.pipeline.extract.scanr import ScanrExtractConfig
from application.ports.pipeline.extract.wos import WosExtractConfig

_LOG = logging.getLogger("test.extract.contract")


def _extractor(cls, config):
    """Instancie un orchestrateur avec un adapter dont `load_config` renvoie `config`."""
    adapter = SimpleNamespace(load_config=lambda conn: config)
    return cls(None, _LOG, adapter)


def _openalex_config(*, institution_ids, has_api_key, has_polite_email):
    return OpenalexExtractConfig(
        base_url="u",
        institution_ids=institution_ids,
        has_api_key=has_api_key,
        has_polite_email=has_polite_email,
    )


@pytest.mark.parametrize(
    ("has_api_key", "has_polite_email"),
    [(True, False), (False, True), (True, True)],
)
def test_openalex_accepts_key_or_email(has_api_key, has_polite_email):
    extractor = _extractor(
        OpenalexExtractor,
        _openalex_config(
            institution_ids=["I1"], has_api_key=has_api_key, has_polite_email=has_polite_email
        ),
    )
    assert extractor.load_config(None).institution_ids == ["I1"]


def test_openalex_requires_auth():
    extractor = _extractor(
        OpenalexExtractor,
        _openalex_config(institution_ids=["I1"], has_api_key=False, has_polite_email=False),
    )
    with pytest.raises(ExtractionConfigError):
        extractor.load_config(None)


def test_openalex_requires_institution_ids():
    extractor = _extractor(
        OpenalexExtractor,
        _openalex_config(institution_ids=[], has_api_key=True, has_polite_email=True),
    )
    with pytest.raises(ExtractionConfigError):
        extractor.load_config(None)


def test_wos_requires_api_key():
    extractor = _extractor(
        WosExtractor, WosExtractConfig(base_url="u", affiliations=["A"], has_api_key=False)
    )
    with pytest.raises(ExtractionConfigError):
        extractor.load_config(None)


def test_wos_requires_affiliations():
    extractor = _extractor(
        WosExtractor, WosExtractConfig(base_url="u", affiliations=[], has_api_key=True)
    )
    with pytest.raises(ExtractionConfigError):
        extractor.load_config(None)


def test_wos_ok_with_key_and_affiliations():
    extractor = _extractor(
        WosExtractor, WosExtractConfig(base_url="u", affiliations=["A"], has_api_key=True)
    )
    assert extractor.load_config(None).affiliations == ["A"]


def test_scanr_requires_credentials():
    extractor = _extractor(
        ScanrExtractor,
        ScanrExtractConfig(base_url="u", affiliation_ids=["A"], has_credentials=False),
    )
    with pytest.raises(ExtractionConfigError):
        extractor.load_config(None)


def test_scanr_requires_affiliation_ids():
    extractor = _extractor(
        ScanrExtractor,
        ScanrExtractConfig(base_url="u", affiliation_ids=[], has_credentials=True),
    )
    with pytest.raises(ExtractionConfigError):
        extractor.load_config(None)


def test_scanr_ok_with_credentials_and_affiliations():
    extractor = _extractor(
        ScanrExtractor,
        ScanrExtractConfig(base_url="u", affiliation_ids=["A"], has_credentials=True),
    )
    assert extractor.load_config(None).affiliation_ids == ["A"]


def _hal_config(all_collections):
    return HalExtractConfig(
        base_url="u",
        all_collections=all_collections,
        n_collections=len(all_collections),
        n_extra=0,
    )


def test_hal_requires_collections():
    extractor = _extractor(HalExtractor, _hal_config({}))
    with pytest.raises(ExtractionConfigError):
        extractor.load_config(None)


def test_hal_ok_with_collections():
    extractor = _extractor(HalExtractor, _hal_config({"C": "lab"}))
    assert extractor.load_config(None).all_collections == {"C": "lab"}
