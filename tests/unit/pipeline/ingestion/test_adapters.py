"""Adaptateurs et lecteurs de document des sources : chaque adaptateur implémente exactement le profil de sa source, et ses fabriques construisent les implémentations de cette source. Chaque accès a sa concurrence."""

import logging
from unittest.mock import MagicMock

import pytest

from domain.sources.registry import DOI_ORG, PROFILES, Source
from pipeline.ingestion.adapters import adapter
from pipeline.ingestion.api_params import MAX_CONCURRENT
from pipeline.ingestion.payload_readers import payload_reader

_LOGGER = logging.getLogger("test")


@pytest.mark.parametrize("source", list(Source))
def test_l_adaptateur_et_le_lecteur_sont_ceux_de_la_source(source: Source):
    assert adapter(source).source == source
    assert payload_reader(source).source == source


@pytest.mark.parametrize("source", list(Source))
def test_les_capacites_de_l_adaptateur_sont_celles_du_profil(source: Source):
    implementations, profile = adapter(source), PROFILES[source]
    assert (implementations.harvester is not None) == profile.harvested
    assert (implementations.person_harvester is not None) == bool(profile.person_identifiers)
    assert (implementations.doi_search is not None) == profile.doi_searchable


@pytest.mark.parametrize("source", list(Source))
def test_les_fabriques_construisent_les_implementations_de_la_source(source: Source):
    implementations = adapter(source)
    assert implementations.normalizer.SOURCE == source
    for harvester in (implementations.harvester, implementations.person_harvester):
        if harvester is not None:
            assert getattr(harvester(MagicMock(), _LOGGER), "SOURCE", None) == source


def test_chaque_source_a_sa_concurrence():
    assert set(Source) | {DOI_ORG} <= set(MAX_CONCURRENT)
