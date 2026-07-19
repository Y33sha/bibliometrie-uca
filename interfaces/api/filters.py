"""Lecture des paramètres de requête portant plusieurs valeurs séparées par des virgules.

Les constructeurs de filtres SQL vivent dans `infrastructure/queries/filters.py`, la construction de SQL étant l'affaire de l'infrastructure.
"""

from collections.abc import Collection

from fastapi import HTTPException


def parse_int_csv(s: str) -> list[int]:
    """Parse une chaîne CSV d'entiers (ex: '1,2,3')."""
    return [int(v) for v in s.split(",") if v.strip()] if s else []


def parse_str_csv(s: str) -> list[str]:
    """Parse une chaîne CSV de strings."""
    return [v.strip() for v in s.split(",") if v.strip()] if s else []


def parse_vocabulary_csv(s: str, *, allowed: Collection[str], param: str) -> list[str]:
    """Découpe une liste de valeurs prises dans un vocabulaire fermé, et refuse les intruses.

    Le découpage par virgules garde les URL lisibles, mais soustrait la liste à la validation
    de FastAPI : sans ce contrôle, une valeur hors vocabulaire traverse jusqu'au SQL, qui
    l'ignore, et la liste rendue n'est pas celle qu'on croit. Le refus prend le même code que
    la validation native, la requête étant malformée de la même façon.
    """
    values = parse_str_csv(s)
    unknown = sorted({v for v in values if v not in allowed})
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Valeurs inconnues pour `{param}` : {', '.join(unknown)}. "
                f"Attendu parmi : {', '.join(sorted(allowed))}."
            ),
        )
    return values
