"""Vérifie que tous les scripts d'extraction et de processing s'importent sans erreur.

Détecte les NameError, ImportError et SyntaxError au niveau module
(variables non définies, imports cassés, etc.).
"""

import importlib

import pytest

MODULES = [
    "infrastructure.sources.hal.extract_hal",
    "infrastructure.sources.hal.cross_import_hal",
    "infrastructure.sources.hal.fetch_missing_hal",
    "infrastructure.sources.openalex.extract_openalex",
    "infrastructure.sources.openalex.cross_import_openalex",
    "infrastructure.sources.openalex.refetch_truncated",
    "infrastructure.sources.wos.extract_wos",
    "infrastructure.sources.wos.cross_import_wos",
    "infrastructure.sources.scanr.extract_scanr",
    "infrastructure.sources.scanr.cross_import_scanr",
    "infrastructure.sources.theses.extract_theses",
    "processing.normalize_hal",
    "processing.normalize_openalex",
    "processing.normalize_wos",
    "processing.normalize_scanr",
    "processing.normalize_theses",
    "processing.create_publications",
    "processing.create_persons_from_source_authorships",
    "processing.build_authorships",
    "processing.populate_affiliations",
    "processing.populate_person_name_forms",
    "application.publications",
    "application.persons",
    "application.authorships",
    "application.journals",
    "domain.doc_types",
    "domain.sources",
    "infrastructure.app_config",
    "pipeline.metrics",
]


@pytest.mark.parametrize("module", MODULES)
def test_import(module):
    """Chaque module doit s'importer sans erreur."""
    importlib.import_module(module)
