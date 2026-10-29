"""Lecture de `doi_targets` : un DOI, remplacé par sa cible quand c'est le DOI d'une forme secondaire."""

from collections.abc import Iterable

from sqlalchemy import Connection, text

from domain.source_records.identifiers import SourceIdentifier, SourceIdentifierType


def doi_or_target_sql(doi: str) -> str:
    """Expression SQL : cible dans `doi_targets` du DOI que renvoie l'expression `doi`, sinon ce DOI."""
    return f"COALESCE((SELECT t.target_doi FROM doi_targets t WHERE t.doi = {doi}), {doi})"  # noqa: S608


def fetch_doi_targets(conn: Connection, identifiers: Iterable[SourceIdentifier]) -> dict[str, str]:
    """Cible de chaque DOI de `identifiers` qui en a une dans `doi_targets`."""
    dois = sorted({i.value for i in identifiers if i.id_type is SourceIdentifierType.DOI})
    if not dois:
        return {}
    rows = conn.execute(
        text("SELECT doi, target_doi FROM doi_targets WHERE doi = ANY(:dois)"), {"dois": dois}
    )
    return {r.doi: r.target_doi for r in rows}
