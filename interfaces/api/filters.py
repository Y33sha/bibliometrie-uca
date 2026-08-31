"""Lecture des paramètres de requête portant plusieurs valeurs séparées par des virgules.

Les constructeurs de filtres SQL vivent dans `infrastructure/read_models/filters.py`, la construction de SQL étant l'affaire de l'infrastructure.
"""

from collections.abc import Collection

from fastapi import HTTPException

from application.ports.read_models.publications_queries import (
    APC_ORIGINS,
    APC_ORIGINS_NEEDING_LAB,
)


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


TOGGLE_VALUES: frozenset[str] = frozenset({"yes", "no"})
"""Vocabulaire d'une facette à deux états, telle que la query string la porte.

Les deux valeurs se combinent en OU : les cocher toutes deux ne contraint rien, et n'en cocher aucune non plus. Convention de transport, partagée par les filtres qui répondent par oui ou par non — signature correspondante, présence dans le périmètre.
"""


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


def parse_apc_origins(s: str, *, lab_ids: list[int]) -> list[str]:
    """Origines du paiement des frais de publication demandées, prises dans leur vocabulaire.

    Deux d'entre elles situent le paiement par rapport aux laboratoires sélectionnés : sans sélection, elles ne désignent rien et la clause SQL les laisse tomber. Les refuser dit à l'appelant ce qui manque, là où les ignorer rendrait une liste plus large que celle qu'il croit avoir demandée.
    """
    values = parse_vocabulary_csv(s, allowed=APC_ORIGINS, param="has_apc")
    if lab_ids:
        return values
    orphelines = sorted(set(values) & APC_ORIGINS_NEEDING_LAB)
    if orphelines:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Valeurs de `has_apc` sans laboratoire sélectionné : {', '.join(orphelines)}. "
                "Elles situent le paiement par rapport aux laboratoires demandés ; renseigner "
                "`lab_id`, ou les retirer."
            ),
        )
    return values
