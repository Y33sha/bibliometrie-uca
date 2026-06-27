"""Familles de `doc_type` : un niveau grossier au-dessus du type fin.

Regroupe les valeurs de l'enum `doc_type` en quelques familles, pour ventiler et filtrer les
publications à une granularité lisible (distinguer les publications au sens strict des autres
objets). Couvre exhaustivement l'enum ; l'ordre est celui d'affichage. Source canonique côté
backend (le constructeur SQL du pivot en dérive un `CASE`) ; l'interface tient sa propre copie
pour les libellés (le frontend ne peut pas importer ce module).
"""

# Famille → types fins. Mémoires/thèses en cours filtrés ailleurs, mais classés ici pour
# l'exhaustivité de la couverture de l'enum.
DOC_TYPE_FAMILIES: dict[str, tuple[str, ...]] = {
    "publications": ("article", "conference_paper", "book", "book_chapter", "review", "data_paper"),
    "preprints": ("preprint",),
    "theses": ("thesis", "ongoing_thesis", "hdr", "memoir"),
    "data": ("dataset", "software", "patent"),
    "misc": (
        "other",
        "media",
        "poster",
        "report",
        "erratum",
        "retraction",
        "peer_review",
        "editorial",
        "letter",
        "book_review",
        "proceedings",
    ),
}


def doc_type_family_sql(column: str = "p.doc_type") -> str:
    """Expression SQL `CASE` projetant `column` (enum `doc_type`) sur sa clé de famille.

    Les types non listés tombent dans `misc` (filet ; l'enum est couvert)."""
    whens = " ".join(
        f"WHEN {column}::text IN ({', '.join(f'{t!r}' for t in types)}) THEN {family!r}"
        for family, types in DOC_TYPE_FAMILIES.items()
    )
    return f"CASE {whens} ELSE 'misc' END"
