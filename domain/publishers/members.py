"""Membres Crossref d'un éditeur.

Un membre Crossref est le compte sous lequel un éditeur dépose ses DOI. Il identifie l'éditeur, qui le déclare lui-même. Un éditeur en a parfois plusieurs, quand ses préfixes DOI sont répartis sur plusieurs comptes.
"""

from collections.abc import Sequence


def crossref_member_conflict(first: Sequence[int], second: Sequence[int]) -> str | None:
    """Renvoie la contradiction entre les membres Crossref de deux éditeurs, ou `None`.

    Deux éditeurs se contredisent quand chacun a au moins un membre et qu'ils n'en partagent aucun : ce sont deux éditeurs distincts.
    """
    a, b = set(first), set(second)
    if a and b and not a & b:
        return (
            f"membres Crossref différents : {', '.join(map(str, sorted(a)))}"
            f" / {', '.join(map(str, sorted(b)))}"
        )
    return None
