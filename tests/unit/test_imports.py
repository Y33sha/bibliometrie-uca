"""Vérifie que tous les scripts d'extraction et de processing s'importent sans erreur.

Détecte les NameError, ImportError et SyntaxError au niveau module
(variables non définies, imports cassés, etc.).
"""

import importlib

import pytest

MODULES = [
    "pipeline.ingestion.hal.harvest",
    "pipeline.ingestion.hal.fetch_missing",
    "pipeline.ingestion.openalex.harvest",
    "pipeline.ingestion.openalex.fetch_missing",
    "pipeline.ingestion.openalex.fetch_truncated",
    "pipeline.ingestion.wos.harvest",
    "pipeline.ingestion.wos.fetch_missing",
    "pipeline.ingestion.scanr.harvest",
    "pipeline.ingestion.scanr.fetch_missing",
    "pipeline.ingestion.theses.harvest",
    "pipeline.ingestion.datacite.harvest",
    "pipeline.ingestion.fetch_missing",
    "pipeline.ingestion.hal.normalize",
    "pipeline.ingestion.openalex.normalize",
    "pipeline.ingestion.wos.normalize",
    "pipeline.ingestion.scanr.normalize",
    "pipeline.ingestion.theses.normalize",
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
    "pipeline.publishing.find_or_create",
    "pipeline.publishing.journal_merge",
    "pipeline.public",
    "application.services.persons.core",
    "application.services.authorships",
    "application.services.journals.core",
    "domain.source_publications.doc_types",
    "domain.sources",
    "pipeline.runtime.config",
]


@pytest.mark.parametrize("module", MODULES)
def test_import(module):
    """Chaque module doit s'importer sans erreur."""
    importlib.import_module(module)
