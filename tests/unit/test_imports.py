"""Vérifie que tous les scripts d'extraction et de processing s'importent sans erreur.

Détecte les NameError, ImportError et SyntaxError au niveau module
(variables non définies, imports cassés, etc.).
"""

import importlib

import pytest

MODULES = [
    "infrastructure.sources.hal.extract_hal",
    "application.pipeline.extract.extract_hal",
    "interfaces.cli.pipeline.extract_hal",
    "infrastructure.sources.hal.fetch_missing_hal",
    "infrastructure.sources.hal.fetch_missing_doi",
    "infrastructure.sources.openalex.extract_openalex",
    "infrastructure.sources.openalex.fetch_missing_doi",
    "infrastructure.sources.openalex.refetch_truncated",
    "infrastructure.sources.wos.extract_wos",
    "infrastructure.sources.wos.fetch_missing_doi",
    "infrastructure.sources.scanr.extract_scanr",
    "infrastructure.sources.scanr.fetch_missing_doi",
    "infrastructure.sources.theses.extract_theses",
    "application.pipeline.extract.fetch_missing_doi",
    "interfaces.cli.pipeline.fetch_missing_doi",
    "application.pipeline.normalize.normalize_hal",
    "application.pipeline.normalize.normalize_openalex",
    "application.pipeline.normalize.normalize_wos",
    "application.pipeline.normalize.normalize_scanr",
    "application.pipeline.normalize.normalize_theses",
    "application.pipeline.publications.reconcile_components",
    "application.pipeline.persons.reset",
    "application.pipeline.persons.cascade",
    "application.pipeline.persons.purge",
    "application.pipeline.persons.phase",
    "application.pipeline.authorships.build_authorships",
    "application.pipeline.affiliations.populate_affiliations",
    "application.pipeline.persons.populate_person_name_forms",
    "application.publications.core",
    "application.persons.core",
    "application.authorships",
    "application.journals.core",
    "domain.source_publications.doc_types",
    "domain.sources",
    "infrastructure.sources.config",
]


@pytest.mark.parametrize("module", MODULES)
def test_import(module):
    """Chaque module doit s'importer sans erreur."""
    importlib.import_module(module)
