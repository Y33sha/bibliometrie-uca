"""Décision pure de réconciliation des composantes (merge-only, 3.2a).

À partir des `source_publications` d'un voisinage (les SP *dirty* et leurs voisins directs, cf. `application/pipeline/publications/reconcile_components.py`), calcule **quelles publications matérialisées fusionner** pour qu'il y ait une publication par composante connexe — dans le respect du cannot-link DOI.

Pourquoi le voisinage **1-hop** (voisins directs) suffit, sans fermeture transitive : l'invariant *dirty* garantit que toute mutation de clé marque la SP. Donc toute arête susceptible d'imposer une fusion est soit **neuve** (la clé partagée vient d'apparaître ⇒ au moins une extrémité est dirty ⇒ l'autre est son voisin direct ⇒ l'arête est dans le 1-hop), soit **vieille** (la clé était déjà partagée ⇒ les deux publications ont déjà fusionné au run passé où la clé est apparue). Une arête lointaine (P–Q–R où R ne touche aucune SP dirty) est donc soit déjà matérialisée (R fait déjà partie de la chaîne), soit captée par la SP dirty de sa propre extrémité dans le même batch. `connected_components` sur l'union des 1-hop de toutes les SP dirty voit donc toutes les arêtes neuves.

**Cannot-link DOI** (décision « DOI = identité ») : deux DOI non-nuls distincts ne fusionnent jamais. Dans une composante, on fusionne par **partition de DOI** ; un identifiant secondaire partagé par-dessus deux DOI distincts (conflation de source) n'est pas consommé comme fusion — il persiste comme signal-relation.

**Split différé** : une publication dont les SP de l'univers s'étalent sur plusieurs composantes signale qu'une clé a été retirée (split en attente). Merge-only ici : ces publications sont exclues de la planification et remontées dans `deferred_split_publication_ids` (le split et le re-pointage des dépendants sont un item ultérieur).
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from domain.publications.clustering import connected_components


@dataclass(frozen=True, slots=True)
class ReconcileMember:
    """Une `source_publication` du voisinage de réconciliation.

    `tokens` = clés de confirmation (cf. `ConfirmationKeys.tokens`) ; `effective_doi` = DOI de partition (colonne corrigée, `None` si absent) ; `publication_id` = publication courante de la SP.
    """

    source_publication_id: int
    publication_id: int
    effective_doi: str | None
    tokens: frozenset[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class MergeGroup:
    """Une fusion à appliquer : `absorbed_publication_ids` sont absorbées dans `anchor_publication_id`."""

    anchor_publication_id: int
    absorbed_publication_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ReconcilePlan:
    """Plan de réconciliation : fusions à appliquer + publications au split différé."""

    merges: tuple[MergeGroup, ...]
    deferred_split_publication_ids: tuple[int, ...]


def _merge_group(members: list[ReconcileMember]) -> MergeGroup | None:
    """Fusion d'un ensemble DOI-compatible : ancre = la publication de la SP au plus petit
    `source_publication_id`, les autres publications distinctes y sont absorbées. `None` si une
    seule publication est présente (rien à fusionner)."""
    publication_ids = {m.publication_id for m in members}
    if len(publication_ids) < 2:
        return None
    anchor = min(members, key=lambda m: m.source_publication_id).publication_id
    absorbed = tuple(sorted(publication_ids - {anchor}))
    return MergeGroup(anchor, absorbed)


def plan_merges(members: Iterable[ReconcileMember]) -> ReconcilePlan:
    """Calcule les fusions à appliquer sur le voisinage `members` (pur, sans I/O).

    Composantes connexes sur les tokens, puis par composante : si 0 ou 1 DOI distinct, toute la composante est une œuvre (fusion de ses publications) ; si ≥2 DOI distincts (conflation), fusion **conservatrice** des seules publications partageant le même DOI, le reste laissé intact (résidu / signal-relation). Les publications étalées sur plusieurs composantes (split en attente) sont exclues et remontées séparément.
    """
    members = list(members)
    by_id = {m.source_publication_id: m for m in members}
    components = connected_components([(m.source_publication_id, m.tokens) for m in members])

    # Publications dont les SP de l'univers s'étalent sur >1 composante : split en attente.
    component_of_publication: dict[int, set[int]] = defaultdict(set)
    for index, component in enumerate(components):
        for source_publication_id in component:
            component_of_publication[by_id[source_publication_id].publication_id].add(index)
    spanning = {pub for pub, indexes in component_of_publication.items() if len(indexes) > 1}

    merges: list[MergeGroup] = []
    for component in components:
        comp = [by_id[sp_id] for sp_id in component if by_id[sp_id].publication_id not in spanning]
        distinct_dois = {m.effective_doi for m in comp if m.effective_doi}
        if len(distinct_dois) <= 1:
            group = _merge_group(comp)
            if group is not None:
                merges.append(group)
        else:
            # Conflation : on ne fusionne que les publications d'un même DOI ; les SP sans DOI
            # et les ponts inter-DOI restent intacts (signal-relation, audit ultérieur).
            for doi in sorted(distinct_dois):
                group = _merge_group([m for m in comp if m.effective_doi == doi])
                if group is not None:
                    merges.append(group)

    return ReconcilePlan(
        merges=tuple(merges), deferred_split_publication_ids=tuple(sorted(spanning))
    )
