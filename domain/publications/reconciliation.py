"""Décision pure de réconciliation des composantes — merge **et** split unifiés.

À partir des `source_publications` d'un voisinage (les SP *dirty* et leurs voisins directs, cf. `application/pipeline/publications/reconcile_components.py`), calcule **où chaque SP doit aboutir** pour qu'il y ait exactement une publication par partition `(composante ∩ DOI)` — dans le respect du cannot-link DOI.

**Opération unique.** On assigne chaque SP au **pub-ancre** de sa partition. Merge et split en sont deux faces : une partition étalée sur plusieurs pubs → tous ses SP rejoignent l'ancre (les autres pubs se vident) ; un pub portant plusieurs partitions → la partition ancrée garde le pub, les autres prennent un nouveau pub.

**Ancre = porteur du DOI.** Pour une partition de DOI `X`, l'ancre est le pub qui **porte déjà** `doi=X` (`publication_doi`), départage `min(publication_id)` si plusieurs le portent (doublons hérités), fallback `min(source_publication_id)` pour une partition **sans** DOI. Choix : la curation (`distinct_publications`, `rejected_authorships`, `apc_payments`) reste sur l'ancre, donc sur le pub qui incarne l'identité DOI — un APC lié à `doi=X` suit mécaniquement l'œuvre X. L'ancre est orthogonale au clustering (elle ne décide que *quel id existant survit*, pas *quelles SP sont ensemble*).

**Cannot-link DOI** (décision « DOI = identité ») : deux DOI non-nuls distincts ne fusionnent jamais. Dans une composante multi-DOI, chaque DOI est sa propre partition ; les SP **sans DOI** y sont **résiduelles** (laissées sur leur pub courant, inertes) — un identifiant secondaire pontant deux DOI n'est pas consommé comme fusion, il persiste comme signal-relation.

Pourquoi le voisinage **1-hop** suffit (pas de fermeture transitive) : l'invariant *dirty* garantit que toute arête susceptible d'imposer un merge/split a une extrémité dirty, donc l'autre est son voisin direct. `connected_components` sur l'union des 1-hop voit toutes les arêtes neuves.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from domain.publications.clustering import connected_components


@dataclass(frozen=True, slots=True)
class ReconcileMember:
    """Une `source_publication` du voisinage de réconciliation.

    `tokens` = clés de confirmation (cf. `ConfirmationKeys.tokens`) ; `effective_doi` = DOI de partition (colonne corrigée, `None` si absent) ; `publication_id` = publication courante de la SP ; `publication_doi` = DOI canonique de cette publication courante (sert à choisir l'ancre : le pub qui porte le DOI de la partition).
    """

    source_publication_id: int
    publication_id: int
    publication_doi: str | None
    effective_doi: str | None
    tokens: frozenset[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class WorkGroup:
    """Une œuvre : toutes ses SP doivent aboutir sur une seule publication.

    `target_publication_id` = pub existant conservé (l'ancre) ; `None` => créer un nouveau pub (cas split d'une partition dont aucun pub courant ne porte le DOI). `source_publication_ids` = les SP à y rattacher.
    """

    target_publication_id: int | None
    source_publication_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DissolvedPublication:
    """Publication vidée de toutes ses SP par la réconciliation (cas merge).

    Avant suppression, ses dépendants curatés/importés (`distinct_publications`, `apc_payments`) sont re-pointés vers `successor_publication_id` — la publication qui a absorbé le gros de ses SP (porteuse du même DOI).
    """

    publication_id: int
    successor_publication_id: int


@dataclass(frozen=True, slots=True)
class ReconcilePlan:
    """Plan de réconciliation : groupes à matérialiser + publications dissoutes."""

    groups: tuple[WorkGroup, ...]
    dissolved: tuple[DissolvedPublication, ...]


def _partitions(members: list[ReconcileMember]) -> list[list[ReconcileMember]]:
    """Découpe le voisinage en partitions `(composante ∩ DOI)`.

    Composante à 0 ou 1 DOI distinct → une seule partition (toute la composante, SP sans DOI incluses). Composante multi-DOI → une partition par DOI ; les SP sans DOI sont **résiduelles** (exclues, laissées sur leur pub courant).
    """
    by_id = {m.source_publication_id: m for m in members}
    components = connected_components([(m.source_publication_id, m.tokens) for m in members])

    partitions: list[list[ReconcileMember]] = []
    for component in components:
        comp = [by_id[sp_id] for sp_id in component]
        distinct_dois = sorted({m.effective_doi for m in comp if m.effective_doi})
        if len(distinct_dois) <= 1:
            partitions.append(comp)
        else:
            for doi in distinct_dois:
                partitions.append([m for m in comp if m.effective_doi == doi])
            # SP sans DOI d'une composante multi-DOI : résiduelles, non assignées.
    return partitions


def _anchor(part: list[ReconcileMember]) -> tuple[int, bool]:
    """Pub-ancre préféré d'une partition + sa force. Porteur du DOI de la partition
    (revendication **forte**, départage `min`), sinon pub du `min(source_publication_id)`
    (**faible**)."""
    doi = next((m.effective_doi for m in part if m.effective_doi), None)
    carriers = sorted({m.publication_id for m in part if doi and m.publication_doi == doi})
    if carriers:
        return carriers[0], True
    return min(part, key=lambda m: m.source_publication_id).publication_id, False


def plan_reconciliation(members: Iterable[ReconcileMember]) -> ReconcilePlan:
    """Calcule les assignations SP → publication sur le voisinage `members` (pur, sans I/O).

    Pour chaque partition, choisit l'ancre (`_anchor`), puis résout les conflits : un pub ne peut être l'ancre que d'**une** partition — la revendication forte (porteur du DOI) l'emporte sur le fallback ; à force égale, `min(source_publication_id)`. Les partitions perdantes prennent un nouveau pub (`target=None`). Les pubs vidées de toutes leurs SP sont listées dans `dissolved` avec leur successeur (l'ancre qui a absorbé la partition de leur plus petit SP).
    """
    members = list(members)
    partitions = _partitions(members)

    # (préféré, force, min_sp, sp_ids) par partition.
    claims = [
        (
            *_anchor(part),
            min(m.source_publication_id for m in part),
            tuple(sorted(m.source_publication_id for m in part)),
        )
        for part in partitions
    ]

    # Attribution gloutonne : forte d'abord, puis plus petit min_sp. La première à
    # revendiquer un pub le garde ; les suivantes prennent un nouveau pub.
    awarded: set[int] = set()
    groups: list[WorkGroup] = []
    target_of_sp: dict[int, int | None] = {}
    for preferred, _strong, _min_sp, sp_ids in sorted(claims, key=lambda c: (not c[1], c[2])):
        target = preferred if preferred not in awarded else None
        if target is not None:
            awarded.add(target)
        groups.append(WorkGroup(target, sp_ids))
        for sp_id in sp_ids:
            target_of_sp[sp_id] = target

    # Pubs dissoutes : pub courant qui ne survit comme ancre d'aucun groupe et ne retient
    # aucune SP résiduelle. Successeur = l'ancre où la partition de son plus petit SP a abouti.
    assigned = {sp_id for _, _, _, sp_ids in claims for sp_id in sp_ids}
    residual_pub_ids = {
        m.publication_id for m in members if m.source_publication_id not in assigned
    }
    dissolved: list[DissolvedPublication] = []
    for pub_id in sorted({m.publication_id for m in members} - awarded - residual_pub_ids):
        anchor_sp = min(
            (m for m in members if m.publication_id == pub_id),
            key=lambda m: m.source_publication_id,
        ).source_publication_id
        successor = target_of_sp.get(anchor_sp)
        if successor is not None and successor != pub_id:
            dissolved.append(DissolvedPublication(pub_id, successor))

    return ReconcilePlan(groups=tuple(groups), dissolved=tuple(dissolved))
