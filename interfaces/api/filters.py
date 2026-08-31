"""Lecture des paramètres de requête portant plusieurs valeurs séparées par des virgules.

Les constructeurs de filtres SQL vivent dans `infrastructure/read_models/filters.py`, la construction de SQL étant l'affaire de l'infrastructure.
"""

from collections.abc import Collection

from fastapi import HTTPException


def parse_str_csv(s: str) -> list[str]:
    """Parse une chaîne CSV de strings."""
    return [v.strip() for v in s.split(",") if v.strip()] if s else []


def parse_ints(values: list[str], *, param: str) -> list[int]:
    """Convertit en entiers une liste de valeurs déjà découpée, et refuse ce qui n'en est pas un.

    Sert les paramètres qui mêlent des identifiants à une sentinelle (`lab_id=12,none`) : l'appelant écarte la sentinelle, cette fonction garde le reste.
    """
    entiers: list[int] = []
    intrus: list[str] = []
    for value in values:
        try:
            entiers.append(int(value))
        except ValueError:
            intrus.append(value)
    if intrus:
        raise HTTPException(
            status_code=422,
            detail=f"Valeurs non entières pour `{param}` : {', '.join(intrus)}.",
        )
    return entiers


def parse_int_csv(s: str, *, param: str) -> list[int]:
    """Découpe une liste d'entiers séparés par des virgules, et refuse ce qui n'en est pas un.

    Le découpage par virgules garde les URL lisibles, mais soustrait la liste à la validation de FastAPI : sans ce contrôle, une valeur non numérique remonte en `ValueError` jusqu'au filet qui traduit les erreurs non gérées, et une requête malformée se rend en 500. Le refus prend le code de la validation native, comme celui d'une valeur hors vocabulaire.
    """
    return parse_ints(parse_str_csv(s), param=param)


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
