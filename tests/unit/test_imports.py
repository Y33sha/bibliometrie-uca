"""Vérifie que tous les scripts d'extraction et de processing s'importent sans erreur.

Détecte les NameError, ImportError et SyntaxError au niveau module
(variables non définies, imports cassés, etc.).
"""

import importlib

import pytest

MODULES = [
    "pipeline.sources.hal.harvest",
    "pipeline.sources.hal.fetch_missing",
    "pipeline.sources.openalex.harvest",
    "pipeline.sources.openalex.fetch_missing",
    "pipeline.sources.openalex.fetch_truncated",
    "pipeline.sources.wos.harvest",
    "pipeline.sources.wos.fetch_missing",
    "pipeline.sources.scanr.harvest",
    "pipeline.sources.scanr.fetch_missing",
    "pipeline.sources.theses.harvest",
    "pipeline.sources.datacite.harvest",
    "pipeline.sources.fetch_missing",
    "pipeline.sources.hal.normalize",
    "pipeline.sources.openalex.normalize",
    "pipeline.sources.wos.normalize",
    "pipeline.sources.scanr.normalize",
    "pipeline.sources.theses.normalize",
    "pipeline.publications.reconcile_components",
    "application.pipeline.persons.arbitrate_identifiers",
    "application.pipeline.persons.cascade",
    "application.pipeline.persons.purge",
    "application.pipeline.persons.phase",
    "application.pipeline.authorships.build_authorships",
    "pipeline.structures.affiliations",
    "application.pipeline.persons.populate_person_name_forms",
    "application.pipeline.countries.detect_by_country_name",
    "application.pipeline.countries.detect_by_place_name",
    "application.pipeline.countries.suggest_countries",
    "application.services.publications.core",
    "application.services.persons.core",
    "application.services.authorships",
    "application.services.journals.core",
    "domain.source_publications.doc_types",
    "domain.sources",
    "infrastructure.sources.config",
]


@pytest.mark.parametrize("module", MODULES)
def test_import(module):
    """Chaque module doit s'importer sans erreur."""
    importlib.import_module(module)
