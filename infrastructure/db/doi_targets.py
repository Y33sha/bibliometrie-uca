"""Lecture de `doi_targets` : un DOI, remplacé par sa cible quand c'est le DOI d'une forme secondaire."""


def doi_or_target_sql(doi: str) -> str:
    """Expression SQL : cible dans `doi_targets` du DOI que rend l'expression `doi`, sinon ce DOI."""
    return f"COALESCE((SELECT t.target_doi FROM doi_targets t WHERE t.doi = {doi}), {doi})"  # noqa: S608
