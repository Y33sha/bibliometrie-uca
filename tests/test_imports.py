"""Vérifie que tous les scripts d'extraction et de processing s'importent sans erreur.

Détecte les NameError, ImportError et SyntaxError au niveau module
(variables non définies, imports cassés, etc.).
"""

import importlib
import pytest


MODULES = [
    "extraction.hal.extract_hal",
    "extraction.hal.cross_import_hal",
    "extraction.hal.fetch_missing_hal",
    "extraction.openalex.extract_openalex",
    "extraction.openalex.cross_import_openalex",
    "extraction.openalex.refetch_truncated",
    "extraction.wos.extract_wos",
    "extraction.wos.cross_import_wos",
    "extraction.scanr.extract_scanr",
    "extraction.scanr.cross_import_scanr",
    "extraction.theses.extract_theses",
    "processing.normalize_hal",
    "processing.normalize_openalex",
    "processing.normalize_wos",
    "processing.normalize_scanr",
    "processing.normalize_theses",
    "processing.create_publications",
    "processing.create_persons_from_source_authorships",
    "processing.build_authorships",
    "processing.populate_affiliations",
    "processing.populate_addresses",
    "processing.populate_person_name_forms",
    "services.publications",
    "services.persons",
    "services.authorships",
    "services.journals",
    "utils.doc_types",
    "utils.sources",
    "utils.app_config",
    "pipeline.metrics",
]


@pytest.mark.parametrize("module", MODULES)
def test_import(module):
    """Chaque module doit s'importer sans erreur."""
    importlib.import_module(module)
