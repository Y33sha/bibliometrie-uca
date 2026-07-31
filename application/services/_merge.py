"""Garde-fous communs aux fusions d'agrégats.

Les quatre fusions (personnes, publications, revues, éditeurs) ouvrent sur les mêmes vérifications avant leur logique propre : refus de fusionner un objet avec lui-même, chargement de la cible et de la source, refus si l'une manque. Ce préambule est factorisé ici ; ce qui suit — conflit d'ISSN, requalification de type, fiche RH, garde « un DOI, une publication » — reste propre à chaque agrégat.
"""

from collections.abc import Callable

from domain.errors import NotFoundError, ValidationError


def load_merge_pair[T](
    target_id: int,
    source_id: int,
    find_by_id: Callable[[int], T | None],
    *,
    label: str,
) -> tuple[T, T]:
    """Charge et valide le couple (cible, source) d'une fusion.

    Refuse une cible et une source identiques (`ValidationError`), charge les deux entités par leur id, et refuse si l'une manque (`NotFoundError`). `label` nomme l'agrégat dans les messages (« Éditeur #12 introuvable »). Rend le couple `(cible, source)` chargé — les fusions qui n'en ont pas l'usage ignorent le retour.
    """
    if target_id == source_id:
        raise ValidationError(
            f"Fusion impossible : cible et source identiques ({label} #{target_id})"
        )
    target = find_by_id(target_id)
    source = find_by_id(source_id)
    if target is None:
        raise NotFoundError(f"{label} #{target_id} introuvable")
    if source is None:
        raise NotFoundError(f"{label} #{source_id} introuvable")
    return target, source
