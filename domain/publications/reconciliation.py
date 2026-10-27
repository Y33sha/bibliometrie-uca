"""Décision pure de réconciliation des composantes — assignation, merge et split unifiés.

À partir des `source_records` d'un voisinage (les enregistrements sources marqués pour la réconciliation et leurs voisins directs, cf. `pipeline/transformation/publications/reconciliation.py`), calcule **où chaque enregistrement source doit aboutir** pour qu'il y ait exactement une publication par partition `(composante ∩ DOI)` — dans le respect du cannot-link DOI.

**Opération unique.** Chaque enregistrement source est assigné à la **publication ancre** de sa partition. Un enregistrement source est soit **matérialisé** (`publication_id` posé), soit **orphelin** (`publication_id = None`) — la passe ne fait aucune différence, c'est le clustering qui décide. Les quatre cas du matcher en sont des facettes :

- **match** : une partition contient un orphelin et une publication existante (token partagé) → l'orphelin rejoint l'ancre.
- **create** : une partition n'est faite que d'orphelins, dont ≥1 in-périmètre → une publication est créée.
- **skip** : une partition d'orphelins sans aucun membre in-périmètre → rien n'est créé, ils restent orphelins.
- **merge / split** : partitions étalées sur plusieurs publications / publication qui contient plusieurs partitions (cf. ci-dessous).

**Ancre = porteur du DOI.** Pour une partition de DOI `X`, l'ancre est la publication qui **a déjà** `doi=X` (`publication_doi`), départage `min(publication_id)` si plusieurs l'ont (doublons hérités), fallback `min(source_record_id)` parmi les enregistrements sources **matérialisés** de la partition. Si aucun enregistrement source n'a de publication (partition d'orphelins) : pas d'ancre existante → **create** (si in-périmètre) ou **skip**. Les corrections à la main restent sur l'ancre (la publication qui a le DOI). L'ancre est orthogonale au clustering (elle ne décide que *quel id survit*, pas *quels enregistrements sources sont ensemble*).

**Cannot-link DOI** (décision « un DOI, une œuvre ») : deux DOI non-nuls distincts ne fusionnent jamais. Dans une composante multi-DOI, chaque DOI est sa propre partition ; les enregistrements sources **sans DOI** y sont **résiduels** (laissés tels quels, inertes).

Pourquoi le voisinage **1-hop** suffit (pas de fermeture transitive) : l'invariant du marquage garantit que toute arête susceptible d'imposer une assignation/merge/split a une extrémité marquée, donc l'autre est son voisin direct. `connected_components` sur l'union des 1-hop voit toutes les arêtes neuves. Une arête **retirée**, elle, ne laisse aucune trace dans les clés d'après : seule l'appartenance déjà matérialisée la conserve, d'où le marquage des enregistrements sources co-rattachés à une publication avec un enregistrement source marqué, en amont de la constitution du voisinage. Sur un full rerun (tout marqué), l'univers = tout le stock → la passe dégénère en cluster-then-materialize global.
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import NamedTuple

from domain.entity_resolution import connected_components
from domain.publications.metadata import has_minimal_publication_metadata
from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES

# Nom de clé des jetons de fusion manuelle, valeur de clé = identifiant de la fusion manuelle.
MANUAL_MERGE_KEY = "manual_merge"


def manual_merge_tokens(manual_merge_ids: Iterable[int]) -> frozenset[tuple[str, str]]:
    """Jetons des fusions manuelles d'un enregistrement source. Le clustering les traite comme des clés de confirmation."""
    return frozenset(
        (MANUAL_MERGE_KEY, str(manual_merge_id)) for manual_merge_id in manual_merge_ids
    )


@dataclass(frozen=True, slots=True)
class ReconcileMember:
    """Un enregistrement source du voisinage de réconciliation.

    `tokens` = clés de confirmation (cf. `ConfirmationKeys.tokens`) et jetons de fusion manuelle (`manual_merge_tokens`) ; `effective_doi` = DOI de partition (colonne corrigée, `None` si absent) ; `publication_id` = publication courante de l'enregistrement source, **`None` s'il est orphelin** (pas encore matérialisé) ; `publication_doi` = DOI de cette publication courante (`None` s'il est orphelin) ; `in_perimeter` = l'enregistrement source a ≥1 contribution source in-périmètre ; `title_normalized` / `publication_year` = métadonnées minimales requises pour matérialiser une publication neuve ; `doc_type` = type de l'enregistrement source.

    `in_perimeter`, `title_normalized`, `publication_year` et `doc_type` n'ont de rôle que pour la **création** : ils décident create vs skip pour une partition d'orphelins ; l'année décide create vs détachement pour une partition qui perd sa publication.
    """

    source_record_id: int
    publication_id: int | None
    publication_doi: str | None
    effective_doi: str | None
    tokens: frozenset[tuple[str, str]]
    in_perimeter: bool = False
    title_normalized: str | None = None
    publication_year: int | None = None
    doc_type: str | None = None

    @property
    def can_found_publication(self) -> bool:
        """L'enregistrement source est in-périmètre et d'un type du périmètre métier."""
        return self.in_perimeter and self.doc_type not in OUT_OF_SCOPE_DOC_TYPES

    @property
    def materializable(self) -> bool:
        """L'enregistrement source a les métadonnées minimales d'une publication (`has_minimal_publication_metadata`)."""
        return has_minimal_publication_metadata(self.title_normalized, self.publication_year)


@dataclass(frozen=True, slots=True)
class WorkGroup:
    """Une œuvre : tous ses enregistrements sources doivent aboutir sur une seule publication.

    `target_publication_id` = publication existante conservée (l'ancre) ; `None` => créer une publication (partition d'orphelins in-périmètre, ou partition perdante d'un split). `source_record_ids` = les enregistrements sources à y rattacher. Une partition d'orphelins **sans** membre in-périmètre n'émet pas de groupe (ses enregistrements sources restent orphelins).
    """

    target_publication_id: int | None
    source_record_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DissolvedPublication:
    """Publication vidée de tous ses enregistrements sources par la réconciliation (cas merge).

    Avant suppression, ses paiements APC (`apc_payments`) sont re-pointés vers `successor_publication_id` — la publication qui a absorbé le gros de ses enregistrements sources (porteuse du même DOI).
    """

    publication_id: int
    successor_publication_id: int


@dataclass(frozen=True, slots=True)
class ReconcilePlan:
    """Plan de réconciliation : groupes à matérialiser, publications dissoutes, `source_records` à détacher de leur publication.

    Une partition détachée a perdu la revendication de sa publication, et aucun de ses membres n'a d'année : elle ne peut pas fonder une publication neuve. Ses membres deviennent orphelins.
    """

    groups: tuple[WorkGroup, ...]
    dissolved: tuple[DissolvedPublication, ...]
    detached: tuple[int, ...] = ()


def _partitions(members: list[ReconcileMember]) -> list[list[ReconcileMember]]:
    """Découpe le voisinage en partitions `(composante ∩ DOI)`.

    Composante à 0 ou 1 DOI distinct → une seule partition (toute la composante, enregistrements sources sans DOI inclus). Composante multi-DOI → une partition par DOI ; les enregistrements sources sans DOI sont **résiduels** (exclus, laissés sur leur publication courante).
    """
    by_id = {m.source_record_id: m for m in members}
    components = connected_components([(m.source_record_id, m.tokens) for m in members])

    partitions: list[list[ReconcileMember]] = []
    for component in components:
        comp = [by_id[source_record_id] for source_record_id in component]
        distinct_dois = sorted({m.effective_doi for m in comp if m.effective_doi})
        if len(distinct_dois) <= 1:
            partitions.append(comp)
        else:
            # Les enregistrements sources sans DOI d'une composante multi-DOI restent résiduels,
            # non assignés.
            partitions.extend([m for m in comp if m.effective_doi == doi] for doi in distinct_dois)
    return partitions


class _Claim(NamedTuple):
    """Revendication d'une partition. `preferred` est la publication revendiquée, `None` pour une création ; `strong` vaut pour le porteur du DOI."""

    preferred: int | None
    strong: bool
    min_source_record: int
    source_record_ids: tuple[int, ...]


def _claim(
    part: list[ReconcileMember], existing_publication_by_doi: dict[str, int]
) -> _Claim | None:
    """Revendication d'ancre d'une partition, ou `None` si **skip** (orphelins dont aucun ne peut fonder une publication).

    - Partition qui contient ≥1 enregistrement source matérialisé → revendique une publication existante : porteuse du DOI
      (revendication **forte**, départage `min`), sinon la publication du plus petit `source_record_id`
      *parmi les enregistrements sources matérialisés* (**faible**).
    - Partition d'orphelins (aucun enregistrement source matérialisé) → `preferred = None` (**create**) si ≥1 membre
      peut fonder une publication (`ReconcileMember.can_found_publication`) **et** ≥1 membre est
      matérialisable (`ReconcileMember.materializable`) ; sinon `None` (**skip**, les enregistrements
      sources restent orphelins).

    Porteur du DOI **hors voisinage** (`existing_publication_by_doi`) : une publication existante a
    déjà le DOI de la partition sans qu'aucun enregistrement source du voisinage n'y soit rattaché (orpheline après
    un TRUNCATE + réimport, ou dérive du `publications.doi`). Elle reste l'ancre — sinon la création
    d'une publication neuve au même DOI heurterait la contrainte unique. Honore la doctrine « ancre = porteur
    du DOI » pour les porteurs qu'aucun membre ne représente.
    """
    source_record_ids = tuple(sorted(m.source_record_id for m in part))
    min_source_record = min(m.source_record_id for m in part)
    doi = next((m.effective_doi for m in part if m.effective_doi), None)
    external_carrier = existing_publication_by_doi.get(doi) if doi else None
    materialized = [m for m in part if m.publication_id is not None]
    if materialized:
        carriers = sorted(
            {
                pid
                for m in materialized
                if doi and m.publication_doi == doi and (pid := m.publication_id) is not None
            }
        )
        if carriers:
            return _Claim(carriers[0], True, min_source_record, source_record_ids)
        if external_carrier is not None:
            return _Claim(external_carrier, True, min_source_record, source_record_ids)
        anchor_publication = min(materialized, key=lambda m: m.source_record_id).publication_id
        return _Claim(anchor_publication, False, min_source_record, source_record_ids)
    if external_carrier is not None:
        return _Claim(external_carrier, True, min_source_record, source_record_ids)
    if any(m.materializable for m in part) and any(m.can_found_publication for m in part):
        return _Claim(None, False, min_source_record, source_record_ids)  # create
    return None  # skip


def plan_reconciliation(
    members: Iterable[ReconcileMember],
    *,
    existing_publication_by_doi: dict[str, int] | None = None,
    publication_sizes: Mapping[int, int] | None = None,
) -> ReconcilePlan:
    """Calcule les assignations enregistrement source → publication sur le voisinage `members` (pur, sans I/O).

    Pour chaque partition, une revendication (`_claim`) : publication existante (match/merge), création
    (`target=None`, orphelins in-périmètre ou partition split perdante) ou skip (orphelins
    hors-périmètre, aucun groupe). Attribution gloutonne : une publication existante ne peut être l'ancre
    que d'**une** partition — la revendication forte (porteur du DOI) l'emporte, puis le plus petit
    `source_record_id` ; les perdantes prennent une nouvelle publication. Les publications vidées de tous leurs
    enregistrements sources sont listées dans `dissolved` avec leur successeur.

    `existing_publication_by_doi` (map `lower(doi) → id`) sert d'ancre de repli pour une partition dont le
    DOI appartient à une publication existante qu'aucun membre du voisinage ne représente (publication
    orpheline, ou dérive). Vide par défaut (aucun porteur hors voisinage connu).

    `publication_sizes` (map `publication_id → nombre total d'enregistrements sources`) signale les publications qui gardent des enregistrements sources hors du voisinage : elles restent. Sans entrée, une publication a les seuls enregistrements sources du voisinage.
    """
    members = list(members)
    by_doi = existing_publication_by_doi or {}
    claims = [c for part in _partitions(members) if (c := _claim(part, by_doi)) is not None]

    # Attribution gloutonne : revendications de publication existante d'abord (forte, puis min_source_record), puis
    # les créations (`preferred=None`). La première à revendiquer une publication la garde ; les suivantes,
    # comme les créations, prennent une nouvelle publication (`target=None`).
    by_id = {m.source_record_id: m for m in members}
    awarded: set[int] = set()
    groups: list[WorkGroup] = []
    detached: list[int] = []
    target_of_source_record: dict[int, int | None] = {}
    for claim in sorted(
        claims, key=lambda c: (c.preferred is None, not c.strong, c.min_source_record)
    ):
        if claim.preferred is not None and claim.preferred not in awarded:
            awarded.add(claim.preferred)
            target: int | None = claim.preferred
        else:
            target = None  # création, ou publication existante déjà prise → nouvelle publication
            if not any(by_id[i].publication_year for i in claim.source_record_ids):
                detached.extend(claim.source_record_ids)
                continue
        groups.append(WorkGroup(target, claim.source_record_ids))
        for source_record_id in claim.source_record_ids:
            target_of_source_record[source_record_id] = target

    # Publications dissoutes : publication courante qui ne survit comme ancre d'aucun groupe et ne retient aucun
    # enregistrement source résiduel. Successeur = l'ancre où la partition de son plus petit enregistrement source a abouti.
    # Les orphelins, sans publication, sont ignorés ici.
    assigned = {i for claim in claims for i in claim.source_record_ids}
    universe_publication_ids = {m.publication_id for m in members if m.publication_id is not None}
    residual_publication_ids = {
        m.publication_id
        for m in members
        if m.source_record_id not in assigned and m.publication_id is not None
    }
    # Une publication qui garde des enregistrements sources hors du voisinage survit à ses enregistrements sources réassignés.
    members_per_publication = Counter(
        m.publication_id for m in members if m.publication_id is not None
    )
    sizes = publication_sizes or {}
    residual_publication_ids |= {
        p for p, n in members_per_publication.items() if sizes.get(p, n) > n
    }
    dissolved: list[DissolvedPublication] = []
    for publication_id in sorted(universe_publication_ids - awarded - residual_publication_ids):
        anchor_source_record = min(
            (m for m in members if m.publication_id == publication_id),
            key=lambda m: m.source_record_id,
        ).source_record_id
        successor = target_of_source_record.get(anchor_source_record)
        if successor is not None and successor != publication_id:
            dissolved.append(DissolvedPublication(publication_id, successor))

    return ReconcilePlan(groups=tuple(groups), dissolved=tuple(dissolved), detached=tuple(detached))
