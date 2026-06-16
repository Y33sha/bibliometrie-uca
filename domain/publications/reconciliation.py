"""Décision pure de réconciliation des composantes — assignation, merge et split unifiés.

À partir des `source_publications` d'un voisinage (les SP *dirty* et leurs voisins directs, cf. `application/pipeline/publications/reconcile_components.py`), calcule **où chaque SP doit aboutir** pour qu'il y ait exactement une publication par partition `(composante ∩ DOI)` — dans le respect du cannot-link DOI.

**Opération unique.** On assigne chaque SP au **pub-ancre** de sa partition. Une SP est soit **matérialisée** (`publication_id` posé), soit **orpheline** (`publication_id = None`) — la passe ne fait aucune différence, c'est le clustering qui décide. Les quatre cas du matcher en sont des facettes :

- **match** : une partition contient un orphelin et une pub existante (token partagé) → l'orphelin rejoint l'ancre.
- **create** : une partition n'est faite que d'orphelins, dont ≥1 in-périmètre → on crée une pub.
- **skip** : une partition d'orphelins sans aucun membre in-périmètre → on ne crée rien, ils restent orphelins.
- **merge / split** : partitions étalées sur plusieurs pubs / pub portant plusieurs partitions (cf. ci-dessous).

**Ancre = porteur du DOI.** Pour une partition de DOI `X`, l'ancre est le pub qui **porte déjà** `doi=X` (`publication_doi`), départage `min(publication_id)` si plusieurs le portent (doublons hérités), fallback `min(source_publication_id)` parmi les SP **matérialisées** de la partition. Si aucune SP n'a de pub (partition d'orphelins) : pas d'ancre existante → **create** (si in-périmètre) ou **skip**. La curation reste sur l'ancre (le pub qui incarne l'identité DOI). L'ancre est orthogonale au clustering (elle ne décide que *quel id survit*, pas *quelles SP sont ensemble*).

**Cannot-link DOI** (décision « DOI = identité ») : deux DOI non-nuls distincts ne fusionnent jamais. Dans une composante multi-DOI, chaque DOI est sa propre partition ; les SP **sans DOI** y sont **résiduelles** (laissées telles quelles, inertes).

Pourquoi le voisinage **1-hop** suffit (pas de fermeture transitive) : l'invariant *dirty* garantit que toute arête susceptible d'imposer une assignation/merge/split a une extrémité dirty, donc l'autre est son voisin direct. `connected_components` sur l'union des 1-hop voit toutes les arêtes neuves. Sur un full rerun (tout dirty), l'univers = tout le stock → la passe dégénère en cluster-then-materialize global.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from domain.entity_resolution import connected_components


@dataclass(frozen=True, slots=True)
class ReconcileMember:
    """Une `source_publication` du voisinage de réconciliation.

    `tokens` = clés de confirmation (cf. `ConfirmationKeys.tokens`) ; `effective_doi` = DOI de partition (colonne corrigée, `None` si absent) ; `publication_id` = publication courante de la SP, **`None` si orpheline** (pas encore matérialisée) ; `publication_doi` = DOI canonique de cette publication courante (`None` si orpheline) ; `in_perimeter` = la SP a ≥1 authorship in-périmètre ; `title_normalized` / `pub_year` = métadonnées minimales requises pour matérialiser une pub neuve.

    `in_perimeter`, `title_normalized` et `pub_year` n'ont de rôle que pour la **création** (partition d'orphelins) : ils décident create vs skip. Les SP matérialisées ne touchent jamais cette branche, d'où leurs défauts inoffensifs.
    """

    source_publication_id: int
    publication_id: int | None
    publication_doi: str | None
    effective_doi: str | None
    tokens: frozenset[tuple[str, str]]
    in_perimeter: bool = False
    title_normalized: str | None = None
    pub_year: int | None = None


@dataclass(frozen=True, slots=True)
class WorkGroup:
    """Une œuvre : toutes ses SP doivent aboutir sur une seule publication.

    `target_publication_id` = pub existant conservé (l'ancre) ; `None` => créer un nouveau pub (partition d'orphelins in-périmètre, ou partition perdante d'un split). `source_publication_ids` = les SP à y rattacher. Une partition d'orphelins **sans** membre in-périmètre n'émet pas de groupe (les SP restent orphelines).
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


# Revendication d'une partition : (pub préféré | None pour create, force, min_sp, sp_ids).
type _Claim = tuple[int | None, bool, int, tuple[int, ...]]


def _claim(part: list[ReconcileMember]) -> _Claim | None:
    """Revendication d'ancre d'une partition, ou `None` si **skip** (orphelins hors-périmètre).

    - Partition contenant ≥1 SP matérialisée → revendique un pub existant : porteur du DOI
      (revendication **forte**, départage `min`), sinon le pub du plus petit `source_publication_id`
      *parmi les SP matérialisées* (**faible**).
    - Partition d'orphelins (aucune SP matérialisée) → `preferred = None` (**create**) si ≥1 membre
      in-périmètre **et** ≥1 membre matérialisable (titre + année — gate `has_minimal_publication_metadata`,
      sinon `pub_year NOT NULL` ferait échouer la création) ; sinon `None` (**skip**, les SP restent orphelines).
    """
    sp_ids = tuple(sorted(m.source_publication_id for m in part))
    min_sp = min(m.source_publication_id for m in part)
    materialized = [m for m in part if m.publication_id is not None]
    if materialized:
        doi = next((m.effective_doi for m in part if m.effective_doi), None)
        carriers = sorted(
            {
                pid
                for m in materialized
                if doi and m.publication_doi == doi and (pid := m.publication_id) is not None
            }
        )
        if carriers:
            return carriers[0], True, min_sp, sp_ids
        anchor_pub = min(materialized, key=lambda m: m.source_publication_id).publication_id
        return anchor_pub, False, min_sp, sp_ids
    creatable = any(m.title_normalized and m.pub_year for m in part)
    if creatable and any(m.in_perimeter for m in part):
        return None, False, min_sp, sp_ids  # create
    return None  # skip


def plan_reconciliation(members: Iterable[ReconcileMember]) -> ReconcilePlan:
    """Calcule les assignations SP → publication sur le voisinage `members` (pur, sans I/O).

    Pour chaque partition, une revendication (`_claim`) : pub existant (match/merge), création
    (`target=None`, orphelins in-périmètre ou partition split perdante) ou skip (orphelins
    hors-périmètre, aucun groupe). Attribution gloutonne : un pub existant ne peut être l'ancre
    que d'**une** partition — la revendication forte (porteur du DOI) l'emporte, puis le plus petit
    `source_publication_id` ; les perdantes prennent un nouveau pub. Les pubs vidées de toutes leurs
    SP sont listées dans `dissolved` avec leur successeur.
    """
    members = list(members)
    claims = [c for part in _partitions(members) if (c := _claim(part)) is not None]

    # Attribution gloutonne : revendications de pub existant d'abord (forte, puis min_sp), puis
    # les créations (`preferred=None`). La première à revendiquer un pub le garde ; les suivantes,
    # comme les créations, prennent un nouveau pub (`target=None`).
    awarded: set[int] = set()
    groups: list[WorkGroup] = []
    target_of_sp: dict[int, int | None] = {}
    for preferred, _strong, _min_sp, sp_ids in sorted(
        claims, key=lambda c: (c[0] is None, not c[1], c[2])
    ):
        if preferred is not None and preferred not in awarded:
            awarded.add(preferred)
            target: int | None = preferred
        else:
            target = None  # création, ou pub existant déjà pris → nouveau pub
        groups.append(WorkGroup(target, sp_ids))
        for sp_id in sp_ids:
            target_of_sp[sp_id] = target

    # Pubs dissoutes : pub courant qui ne survit comme ancre d'aucun groupe et ne retient aucune
    # SP résiduelle. Successeur = l'ancre où la partition de son plus petit SP a abouti. (Les
    # orphelins n'ont pas de pub → ignorés ici.)
    assigned = {sp_id for _, _, _, sp_ids in claims for sp_id in sp_ids}
    universe_pub_ids = {m.publication_id for m in members if m.publication_id is not None}
    residual_pub_ids = {
        m.publication_id
        for m in members
        if m.source_publication_id not in assigned and m.publication_id is not None
    }
    dissolved: list[DissolvedPublication] = []
    for pub_id in sorted(universe_pub_ids - awarded - residual_pub_ids):
        anchor_sp = min(
            (m for m in members if m.publication_id == pub_id),
            key=lambda m: m.source_publication_id,
        ).source_publication_id
        successor = target_of_sp.get(anchor_sp)
        if successor is not None and successor != pub_id:
            dissolved.append(DissolvedPublication(pub_id, successor))

    return ReconcilePlan(groups=tuple(groups), dissolved=tuple(dissolved))
