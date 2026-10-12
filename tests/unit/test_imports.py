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
    "pipeline.persons.arbitrate_identifiers",
    "pipeline.persons.cascade",
    "pipeline.persons.purge",
    "pipeline.persons.persons",
    "pipeline.publications.build_authorships",
    "pipeline.structures.affiliations",
    "pipeline.persons.populate_person_name_forms",
    "pipeline.structures.detect_by_country_name",
    "pipeline.structures.detect_by_place_name",
    "pipeline.structures.suggest_countries",
    "pipeline.publications.refresh",
    "pipeline.containers.find_or_create",
    "pipeline.containers.journal_merge",
    "pipeline.public",
    "application.services.persons.core",
    "application.services.authorships",
    "application.services.journals.core",
    "domain.source_publications.doc_types",
    "domain.sources",
    "pipeline.config",
]


@pytest.mark.parametrize("module", MODULES)
def test_import(module):
    """Chaque module doit s'importer sans erreur."""
    importlib.import_module(module)
