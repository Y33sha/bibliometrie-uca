"""Lecture de `doi_targets` : un DOI, remplacé par sa cible quand c'est le DOI d'une forme secondaire. Forme sans version d'un DOI en SQL."""

from collections.abc import Iterable

from sqlalchemy import Connection, text

from domain.publications.identifiers import DOI_VERSION_SUFFIX_PATTERN
from domain.source_records.identifiers import SourceIdentifier, SourceIdentifierType


def doi_or_target_sql(doi: str) -> str:
    """Renvoie l'expression SQL de la cible du DOI `doi` dans `doi_targets`, à défaut ce DOI.

    Args:
        doi: expression SQL du DOI.
    """
    return f"COALESCE((SELECT t.target_doi FROM doi_targets t WHERE t.doi = {doi}), {doi})"  # noqa: S608


def unversioned_doi_sql(doi: str) -> str:
    """Renvoie l'expression SQL de la forme sans version du DOI `doi` (`doi_version`), NULL sans suffixe de version.

    Args:
        doi: expression SQL du DOI.
    """
    pattern = DOI_VERSION_SUFFIX_PATTERN
    return f"CASE WHEN {doi} ~ '{pattern}' THEN regexp_replace({doi}, '{pattern}', '') END"


def fetch_doi_targets(conn: Connection, identifiers: Iterable[SourceIdentifier]) -> dict[str, str]:
    """Renvoie la cible des DOI de `identifiers` présents dans `doi_targets`."""
    dois = sorted({i.value for i in identifiers if i.id_type is SourceIdentifierType.DOI})
    if not dois:
        return {}
    rows = conn.execute(
        text("SELECT doi, target_doi FROM doi_targets WHERE doi = ANY(:dois)"), {"dois": dois}
    )
    return {r.doi: r.target_doi for r in rows}
