"""Règles d'entité Personne autour de la fusion / déduplication.

À étendre avec les règles de matching, de déduplication et de
création quand on rapatriera les items correspondants depuis le
pipeline (cf. inventaire ``regles-metier-inventaire.md``).
"""

from domain.errors import ConflictError


def check_can_merge_persons(has_distinct_rh: bool, target_id: int, source_id: int) -> None:
    """Valide qu'une fusion de personnes est autorisée.

    Invariant : refus si les deux personnes ont chacune une fiche RH
    distincte (risque de perdre de l'information RH).

    Lève `ConflictError` avec le message standardisé si l'invariant est
    violé. L'appelant reste responsable de fournir l'information
    `has_distinct_rh` (typiquement via le repository).
    """
    if has_distinct_rh:
        raise ConflictError(
            f"REFUS de fusion : les personnes #{target_id} et #{source_id} "
            f"ont chacune une fiche RH distincte."
        )
