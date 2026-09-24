"""Membres Crossref d'un éditeur.

Un membre Crossref est le compte sous lequel un éditeur dépose ses DOI. Il vaut identité déclarée par l'éditeur lui-même. Un éditeur en porte parfois plusieurs, quand ses préfixes DOI sont répartis sur plusieurs comptes.
"""

from collections.abc import Sequence


def crossref_member_conflict(first: Sequence[int], second: Sequence[int]) -> str | None:
    """Contradiction entre les membres Crossref de deux éditeurs, ou `None`.

    Deux éditeurs se contredisent quand chacun porte au moins un membre et qu'ils n'en partagent aucun : leurs identités sont distinctes.
    """
    a, b = set(first), set(second)
    if a and b and not a & b:
        return (
            f"membres Crossref différents : {', '.join(map(str, sorted(a)))}"
            f" / {', '.join(map(str, sorted(b)))}"
        )
    return None
