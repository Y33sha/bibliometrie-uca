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
    "pipeline.ingestion.common.fetch_missing",
    "pipeline.ingestion.hal.normalize",
    "pipeline.ingestion.openalex.normalize",
    "pipeline.ingestion.wos.normalize",
    "pipeline.ingestion.scanr.normalize",
    "pipeline.ingestion.theses.normalize",
    "pipeline.transformation.publications.reconciliation",
    "pipeline.transformation.persons.identifier_arbitration",
    "pipeline.transformation.persons.groups",
    "pipeline.transformation.persons.purge",
    "pipeline.transformation.persons.persons",
    "pipeline.transformation.structures.affiliations",
    "pipeline.transformation.persons.populate_person_name_forms",
    "pipeline.transformation.countries.detect_by_country_name",
    "pipeline.transformation.countries.detect_by_place_name",
    "pipeline.transformation.publications.consolidation",
    "pipeline.transformation.publications.store",
    "pipeline.transformation.publishing.find_or_create",
    "pipeline.transformation.publishing.serials.serial_merge",
    "pipeline.public",
    "application.services.persons.core",
    "application.services.contributions",
    "application.services.serials.core",
    "domain.source_records.doc_types",
    "domain.sources",
    "pipeline.runtime.config",
]


@pytest.mark.parametrize("module", MODULES)
def test_import(module):
    """Chaque module doit s'importer sans erreur."""
    importlib.import_module(module)
