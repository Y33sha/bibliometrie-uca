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


def doc_type_grouped_sql(column: str = "p.doc_type") -> str:
    """Expression SQL `CASE` projetant `column` (enum `doc_type`) sur la clé de groupement du pivot :
    les types de la famille « publications » (article, communication, chapitre…) gardent leur grain
    fin, les autres familles restent agrégées sous leur clé de famille. Le détail là où il porte le
    plus d'information (les publications au sens strict, dont la répartition varie fortement d'un
    laboratoire à l'autre), le grossier ailleurs. Couvre exhaustivement l'enum ; les types non listés
    tombent dans `misc` (filet)."""
    expanded = DOC_TYPE_FAMILIES["publications"]
    whens = [f"WHEN {column}::text IN ({', '.join(f'{t!r}' for t in expanded)}) THEN {column}::text"]
    whens += [
        f"WHEN {column}::text IN ({', '.join(f'{t!r}' for t in types)}) THEN {family!r}"
        for family, types in DOC_TYPE_FAMILIES.items()
        if family != "publications"
    ]
    return f"CASE {' '.join(whens)} ELSE 'misc' END"
