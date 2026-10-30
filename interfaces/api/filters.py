"""Lecture des paramètres de requête à plusieurs valeurs séparées par des virgules.

Les constructeurs de filtres SQL sont dans `infrastructure/read_models/filters.py`.
"""

from collections.abc import Collection

from fastapi import HTTPException

from domain.structures.identifiers import RorId


def parse_str_csv(s: str) -> list[str]:
    """Découpe une liste de chaînes séparées par des virgules."""
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

    Le découpage par virgules garde les URL lisibles, mais soustrait la liste à la validation de FastAPI : sans ce contrôle, une valeur non numérique finirait en erreur 500. Le refus prend le code de la validation native, comme celui d'une valeur hors vocabulaire.
    """
    return parse_ints(parse_str_csv(s), param=param)


def parse_ror_csv(s: str, *, param: str) -> list[str]:
    """Découpe une liste de ROR séparés par des virgules, sous leur forme courte, et refuse ce qui n'en est pas un."""
    rors: list[str] = []
    intrus: list[str] = []
    for value in parse_str_csv(s):
        if (ror := RorId.try_parse(value)) is None:
            intrus.append(value)
        else:
            rors.append(str(ror))
    if intrus:
        raise HTTPException(
            status_code=422, detail=f"ROR invalides pour `{param}` : {', '.join(intrus)}."
        )
    return rors


def parse_ids_with_none(s: str, *, param: str) -> tuple[list[int], bool]:
    """Découpe une liste d'identifiants mêlée de la sentinelle `none`, en identifiants et en drapeau `none`."""
    parts = parse_str_csv(s)
    return parse_ints([v for v in parts if v != "none"], param=param), "none" in parts


def parse_lab_id(lab_id: str) -> tuple[list[int], bool]:
    """Découpe `lab_id` en identifiants de laboratoires et en drapeau « sans laboratoire ».

    `lab_id=12,none` retient les publications du laboratoire 12 et celles sans laboratoire.
    """
    return parse_ids_with_none(lab_id, param="lab_id")


TOGGLE_VALUES: frozenset[str] = frozenset({"yes", "no"})
"""Vocabulaire d'une facette à deux états, dans la query string.

Les deux valeurs se combinent en OU : en cocher deux ou aucune laisse tout passer. Convention de transport, partagée par les filtres qui répondent par oui ou par non — contribution source correspondante, présence dans le périmètre.
"""


def parse_vocabulary_csv(s: str, *, allowed: Collection[str], param: str) -> list[str]:
    """Découpe une liste de valeurs prises dans un vocabulaire fermé, et refuse les intruses.

    Le découpage par virgules garde les URL lisibles, mais soustrait la liste à la validation de FastAPI : sans ce contrôle, une valeur hors vocabulaire irait jusqu'au SQL, qui l'ignorerait, et la liste renvoyée serait trompeuse. Le refus prend le code de la validation native.
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
