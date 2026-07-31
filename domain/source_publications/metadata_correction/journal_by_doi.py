"""Rattachement d'une revue à un enregistrement via le préfixe de son DOI.

Une `source_publication` à DOI mais sans `journal_id` (sa source n'a fourni ni ISSN ni titre de conteneur rapprochable) est rattachée au journal dont le `doi_prefix` préfixe son DOI. Recherche inverse contre la table journals, à cible data-dépendante : hors du DSL des règles unaires (`rules`, à cibles constantes), traitée à part comme la correction du DOI de groupe (`shared_doi`).
"""

from collections.abc import Sequence

# Provenance inscrite dans `raw_metadata.journal_id.corrected_by`.
JOURNAL_BY_DOI_PREFIX = "JOURNAL_BY_DOI_PREFIX"


def resolve_journal_by_doi(doi: str, journal_prefixes: Sequence[tuple[str, int]]) -> int | None:
    """Rattache un DOI au journal dont le `doi_prefix` le préfixe, le plus spécifique.

    `journal_prefixes` = une suite de `(doi_prefix, journal_id)`, lue sans être modifiée. Renvoie le `journal_id` du préfixe le plus long qui préfixe `doi`, à condition qu'il désigne un **unique** journal à cette longueur (abstention si deux journaux portent ce même préfixe). `None` si aucun préfixe ne matche. Pur et déterministe. `doi` et les préfixes sont comparés tels quels (DOIs et `doi_prefix` stockés en minuscules). Les préfixes emboîtés (registrant nu `10.5194` et namespace `10.5194/acp`) sont départagés par le plus long.
    """
    matches = [
        (prefix, journal_id) for prefix, journal_id in journal_prefixes if doi.startswith(prefix)
    ]
    if not matches:
        return None
    max_len = max(len(prefix) for prefix, _ in matches)
    most_specific = {journal_id for prefix, journal_id in matches if len(prefix) == max_len}
    if len(most_specific) == 1:
        return next(iter(most_specific))
    return None
