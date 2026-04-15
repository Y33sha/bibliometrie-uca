"""Constantes liées aux sources bibliographiques.

Source unique de vérité côté Python pour la liste des sources.
Les valeurs correspondent à l'enum PostgreSQL `source_type`.

Si une source est ajoutée ou supprimée, modifier ce fichier ET
l'enum source_type en base (via une migration).
Le test test_normalize.py::TestSourcesEnum vérifie la cohérence.
"""

# Toutes les sources, dans l'ordre conventionnel
ALL_SOURCES = ("hal", "openalex", "wos", "scanr", "theses")

# Sources comme set (pour les tests d'appartenance et les valeurs par défaut)
ALL_SOURCES_SET = frozenset(ALL_SOURCES)

# Sources bibliographiques (hors theses.fr, qui a un traitement spécifique)
BIBLIO_SOURCES = ("hal", "openalex", "wos", "scanr")
BIBLIO_SOURCES_SET = frozenset(BIBLIO_SOURCES)

def _to_sql(sources: tuple) -> str:
    """Construit une clause SQL IN à partir d'un tuple de sources."""
    return "(" + ", ".join(f"'{s}'" for s in sources) + ")"

# Sources avec des auteurs exploitables (noms, identifiants, affiliations)
AUTHOR_SOURCES = ALL_SOURCES
AUTHOR_SOURCES_SQL = _to_sql(AUTHOR_SOURCES)

# Sources où les noms d'auteurs sont structurés dans source_authors (last_name, first_name).
# OpenAlex est exclu : les noms viennent de source_authorships.raw_author_name.
SOURCES_WITH_STRUCTURED_NAMES = tuple(s for s in ALL_SOURCES if s != "openalex")
SOURCES_WITH_STRUCTURED_NAMES_SQL = _to_sql(SOURCES_WITH_STRUCTURED_NAMES)
