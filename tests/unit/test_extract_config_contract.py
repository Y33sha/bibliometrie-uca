"""Contrat de configuration par orchestrateur d'extraction (couche application).

Chaque orchestrateur lève `ExtractionConfigError` quand la source n'est pas
extractible : périmètre d'interrogation absent (contrôle propre à l'extraction :
collections HAL, institution_ids, affiliations, PPN) ou credentials absents
(motif porté par `*ExtractConfig.credentials_missing`, renseigné par l'adapter via
le détecteur central `source_credentials_missing`). La règle de présence des
credentials elle-même est testée dans `test_source_credentials_missing`.
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
_MISSING = "credentials absents (motif)"


def _extractor(cls, config):
    """Instancie un orchestrateur avec un adapter dont `load_config` renvoie `config`."""
    adapter = SimpleNamespace(load_config=lambda conn: config)
    return cls(None, _LOG, adapter)


# ── OpenAlex ────────────────────────────────────────────────────────────────


def _openalex(*, institution_ids, credentials_missing):
    return _extractor(
        OpenalexExtractor,
        OpenalexExtractConfig(
            base_url="u", institution_ids=institution_ids, credentials_missing=credentials_missing
        ),
    )


def test_openalex_requires_institution_ids():
    with pytest.raises(ExtractionConfigError):
        _openalex(institution_ids=[], credentials_missing=None).load_config(None)


def test_openalex_raises_on_missing_credentials():
    with pytest.raises(ExtractionConfigError):
        _openalex(institution_ids=["I1"], credentials_missing=_MISSING).load_config(None)


def test_openalex_ok():
    config = _openalex(institution_ids=["I1"], credentials_missing=None).load_config(None)
    assert config.institution_ids == ["I1"]


# ── WoS ─────────────────────────────────────────────────────────────────────


def _wos(*, affiliations, credentials_missing):
    return _extractor(
        WosExtractor,
        WosExtractConfig(
            base_url="u", affiliations=affiliations, credentials_missing=credentials_missing
        ),
    )


def test_wos_requires_affiliations():
    with pytest.raises(ExtractionConfigError):
        _wos(affiliations=[], credentials_missing=None).load_config(None)


def test_wos_raises_on_missing_credentials():
    with pytest.raises(ExtractionConfigError):
        _wos(affiliations=["A"], credentials_missing=_MISSING).load_config(None)


def test_wos_ok():
    assert _wos(affiliations=["A"], credentials_missing=None).load_config(None).affiliations == [
        "A"
    ]


# ── ScanR ───────────────────────────────────────────────────────────────────


def _scanr(*, affiliation_ids, credentials_missing):
    return _extractor(
        ScanrExtractor,
        ScanrExtractConfig(
            base_url="u", affiliation_ids=affiliation_ids, credentials_missing=credentials_missing
        ),
    )


def test_scanr_requires_affiliation_ids():
    with pytest.raises(ExtractionConfigError):
        _scanr(affiliation_ids=[], credentials_missing=None).load_config(None)


def test_scanr_raises_on_missing_credentials():
    with pytest.raises(ExtractionConfigError):
        _scanr(affiliation_ids=["A"], credentials_missing=_MISSING).load_config(None)


def test_scanr_ok():
    config = _scanr(affiliation_ids=["A"], credentials_missing=None).load_config(None)
    assert config.affiliation_ids == ["A"]


# ── HAL (API publique : périmètre seul) ─────────────────────────────────────


def _hal(all_collections):
    return _extractor(
        HalExtractor,
        HalExtractConfig(
            base_url="u",
            all_collections=all_collections,
            n_collections=len(all_collections),
            n_extra=0,
        ),
    )


def test_hal_requires_collections():
    with pytest.raises(ExtractionConfigError):
        _hal({}).load_config(None)


def test_hal_ok_with_collections():
    assert _hal({"C": "lab"}).load_config(None).all_collections == {"C": "lab"}
