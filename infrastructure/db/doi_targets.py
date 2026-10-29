"""Lecture de `doi_targets` : DOI d'un enregistrement source, remplacé par sa cible quand c'est le DOI d'une forme secondaire."""


def doi_or_target_sql(source_record: str) -> str:
    """Expression SQL : cible du DOI de l'enregistrement source aliasé `source_record` dans `doi_targets`, sinon son DOI."""
    return (
        "COALESCE((SELECT t.target_doi FROM doi_targets t"  # noqa: S608
        f" WHERE t.doi = {source_record}.doi), {source_record}.doi)"
    )
