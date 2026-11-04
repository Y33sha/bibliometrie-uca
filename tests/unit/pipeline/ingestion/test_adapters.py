"""Adaptateurs des sources : chacun implémente exactement le profil de sa source, et ses fabriques construisent les implémentations de cette source. Chaque accès a sa concurrence."""

import logging
from unittest.mock import MagicMock

import pytest

from domain.sources.registry import DOI_ORG, PROFILES, Source
from pipeline.ingestion.adapters import ADAPTERS
from pipeline.ingestion.api_params import MAX_CONCURRENT

_LOGGER = logging.getLogger("test")


def test_chaque_source_a_son_adaptateur():
    assert set(ADAPTERS) == set(Source)
    assert all(adapter.source == source for source, adapter in ADAPTERS.items())


@pytest.mark.parametrize("source", list(Source))
def test_les_capacites_de_l_adaptateur_sont_celles_du_profil(source: Source):
    adapter, profile = ADAPTERS[source], PROFILES[source]
    assert (adapter.harvester is not None) == profile.harvested
    assert (adapter.person_harvester is not None) == bool(profile.person_identifiers)
    assert (adapter.doi_search is not None) == profile.doi_searchable


@pytest.mark.parametrize("source", list(Source))
def test_les_fabriques_construisent_les_implementations_de_la_source(source: Source):
    adapter = ADAPTERS[source]
    assert adapter.normalizer().SOURCE == source
    if adapter.doi_search is not None:
        assert adapter.doi_search().batch_size >= 1
    for harvester in (adapter.harvester, adapter.person_harvester):
        if harvester is not None:
            assert getattr(harvester(MagicMock(), _LOGGER), "SOURCE", None) == source


def test_chaque_source_a_sa_concurrence():
    assert set(Source) | {DOI_ORG} <= set(MAX_CONCURRENT)
