"""Rattachement des enregistrements sources à leur monographie, calculé sur tous les enregistrements sources qui décrivent un volume.

Les enregistrements sources qui partagent un ISBN forment un volume. Les ISBN d'une même monographie existante appartiennent au même volume. Un enregistrement source sans ISBN rejoint le seul volume à ISBN de son titre et d'éditeur compatible : un volume est compatible avec chacun des éditeurs de ses enregistrements sources et de ses monographies existantes, et avec tout éditeur s'il n'en a aucun. Les volumes du même éditeur passent avant ceux sans éditeur. Entre plusieurs, il reste sans monographie. Sans volume à ISBN de son titre, il forme un volume avec les enregistrements sources sans ISBN de même titre et d'éditeur compatible. Le résultat est indépendant de l'ordre des enregistrements sources.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

from domain.entity_resolution import connected_components, most_frequent
from domain.normalize import normalize_text
from domain.publications.identifiers import ISBN


class VolumeRecord(NamedTuple):
    """Enregistrement source qui décrit un volume (`biblio.monograph`)."""

    id: int
    title: str | None
    isbns: tuple[str, ...]
    eisbns: tuple[str, ...]
    proceedings: bool
    year: int | None
    publisher_id: int | None


class ExistingMonograph(NamedTuple):
    """Monographie présente en base."""

    id: int
    title_normalized: str
    isbn: str | None
    eisbn: str | None
    publisher_id: int | None


@dataclass(frozen=True)
class Volume:
    """Volume formé par des enregistrements sources, avec les monographies existantes qui le désignent."""

    record_ids: tuple[int, ...]
    monograph_ids: tuple[int, ...]
    """Monographies existantes du volume, par identifiant croissant : la première est gardée, les autres fusionnent dans elle."""
    title: str | None
    isbn: str | None
    eisbn: str | None
    proceedings: bool
    year: int | None
    publisher_id: int | None


def _compatible_publishers(first: int | None, second: int | None) -> bool:
    """Vrai si les deux éditeurs sont égaux ou l'un absent."""
    return first is None or second is None or first == second


def _valid_isbns(values: Iterable[str]) -> list[str]:
    """Renvoie les ISBN-13 valides de `values`, dans l'ordre, sans doublon."""
    found: list[str] = []
    for value in values:
        isbn = ISBN.try_parse(value)
        if isbn is not None and isbn.value not in found:
            found.append(isbn.value)
    return found


@dataclass
class _Group:
    """Enregistrements sources et monographies existantes d'un volume en construction."""

    records: list[VolumeRecord] = field(default_factory=list)
    paper: Counter[str] = field(default_factory=Counter)
    electronic: Counter[str] = field(default_factory=Counter)
    monograph_ids: set[int] = field(default_factory=set)
    titles: set[str] = field(default_factory=set)
    monograph_publishers: set[int] = field(default_factory=set)
    """Éditeurs des monographies existantes du volume."""

    def publishers(self) -> frozenset[int]:
        """Éditeurs compatibles avec le volume : ceux de ses enregistrements sources et de ses monographies existantes."""
        return frozenset(
            {r.publisher_id for r in self.records if r.publisher_id is not None}
            | self.monograph_publishers
        )

    def publisher_id(self) -> int | None:
        publishers = Counter(r.publisher_id for r in self.records if r.publisher_id is not None)
        return most_frequent(publishers) if publishers else None

    def volume(self) -> Volume:
        titles = Counter(r.title for r in self.records if r.title and normalize_text(r.title))
        years = Counter(r.year for r in self.records if r.year is not None)
        isbn = most_frequent(self.paper) if self.paper else None
        electronic = Counter({k: n for k, n in self.electronic.items() if k != isbn})
        return Volume(
            record_ids=tuple(sorted(r.id for r in self.records)),
            monograph_ids=tuple(sorted(self.monograph_ids)),
            title=most_frequent(titles) if titles else None,
            isbn=isbn,
            eisbn=most_frequent(electronic) if electronic else None,
            proceedings=any(r.proceedings for r in self.records),
            year=most_frequent(years) if years else None,
            publisher_id=self.publisher_id(),
        )


def group_volumes(
    records: Iterable[VolumeRecord], monographs: Iterable[ExistingMonograph]
) -> list[Volume]:
    """Renvoie les volumes formés par `records`, chacun avec ses monographies existantes. Un enregistrement source absent des volumes reste sans monographie."""
    monographs = list(monographs)
    with_isbn: list[tuple[VolumeRecord, list[str], list[str]]] = []
    without_isbn: list[VolumeRecord] = []
    for record in records:
        paper = _valid_isbns(record.isbns)
        electronic = [i for i in _valid_isbns(record.eisbns) if i not in paper]
        if paper or electronic:
            with_isbn.append((record, paper, electronic))
        else:
            without_isbn.append(record)

    isbn_groups = _isbn_groups(with_isbn, monographs)
    orphans_by_title = _attach_without_isbn(without_isbn, isbn_groups)
    volumes = [
        volume
        for volume in (g.volume() for g in isbn_groups)
        if volume.monograph_ids or volume.title
    ]
    volumes += _volumes_without_isbn(orphans_by_title, monographs)
    return sorted(volumes, key=lambda v: v.record_ids)


def _isbn_groups(
    with_isbn: Sequence[tuple[VolumeRecord, list[str], list[str]]],
    monographs: Sequence[ExistingMonograph],
) -> list[_Group]:
    """Renvoie les volumes à ISBN : enregistrements sources réunis par leurs ISBN (`connected_components`), avec les monographies existantes de ces ISBN."""
    isbn_monographs = [m for m in monographs if m.isbn or m.eisbn]
    # Enregistrements sources puis monographies, numérotés à la suite : leurs identifiants viennent de deux tables.
    keys = [
        *(frozenset(paper + electronic) for _, paper, electronic in with_isbn),
        *(frozenset(i for i in (m.isbn, m.eisbn) if i) for m in isbn_monographs),
    ]
    groups: list[_Group] = []
    for component in connected_components(
        (rank, frozenset(("isbn", isbn) for isbn in isbns)) for rank, isbns in enumerate(keys)
    ):
        group = _Group()
        for rank in component:
            if rank < len(with_isbn):
                record, paper, electronic = with_isbn[rank]
                group.records.append(record)
                group.paper.update(paper)
                group.electronic.update(electronic)
                if title := normalize_text(record.title or ""):
                    group.titles.add(title)
            else:
                monograph = isbn_monographs[rank - len(with_isbn)]
                group.monograph_ids.add(monograph.id)
                group.titles.add(monograph.title_normalized)
                if monograph.publisher_id is not None:
                    group.monograph_publishers.add(monograph.publisher_id)
        if group.records:
            groups.append(group)
    return groups


def _attach_without_isbn(
    without_isbn: Sequence[VolumeRecord], isbn_groups: Sequence[_Group]
) -> dict[str, list[VolumeRecord]]:
    """Ajoute chaque enregistrement source sans ISBN au seul volume à ISBN compatible de son titre. Renvoie, par titre, ceux sans volume à ISBN compatible."""
    # Éditeurs de chaque volume à ISBN, figés avant l'arrivée des enregistrements sources sans ISBN.
    by_title: dict[str, list[tuple[_Group, frozenset[int]]]] = defaultdict(list)
    for group in isbn_groups:
        publishers = group.publishers()
        for title in group.titles:
            by_title[title].append((group, publishers))

    orphans_by_title: dict[str, list[VolumeRecord]] = defaultdict(list)
    for record in without_isbn:
        title = normalize_text(record.title or "")
        if not title:
            continue
        compatible = [
            (group, publishers)
            for group, publishers in by_title.get(title, [])
            if record.publisher_id is None or not publishers or record.publisher_id in publishers
        ]
        # Les volumes du même éditeur passent avant ceux sans éditeur.
        same = [g for g, publishers in compatible if record.publisher_id in publishers]
        candidates = same or [g for g, _ in compatible]
        if len(candidates) == 1:
            candidates[0].records.append(record)
        elif not candidates:
            orphans_by_title[title].append(record)
    return orphans_by_title


def _volumes_without_isbn(
    orphans_by_title: dict[str, list[VolumeRecord]], monographs: Sequence[ExistingMonograph]
) -> list[Volume]:
    """Renvoie les volumes sans ISBN : un par titre, ou un par éditeur quand plusieurs éditeurs partagent le titre. Un enregistrement source sans éditeur reste alors sans monographie."""
    existing: dict[str, list[ExistingMonograph]] = defaultdict(list)
    for monograph in monographs:
        if not (monograph.isbn or monograph.eisbn):
            existing[monograph.title_normalized].append(monograph)
    taken: set[int] = set()
    volumes: list[Volume] = []
    for title in sorted(orphans_by_title):
        records = orphans_by_title[title]
        publishers = sorted({r.publisher_id for r in records if r.publisher_id is not None})
        groups = (
            [records]
            if len(publishers) <= 1
            else [[r for r in records if r.publisher_id == p] for p in publishers]
        )
        for members in groups:
            group = _Group(records=members)
            publisher_id = group.publisher_id()
            # La monographie du même éditeur passe avant celle sans éditeur.
            match = min(
                (
                    m
                    for m in existing[title]
                    if m.id not in taken and _compatible_publishers(m.publisher_id, publisher_id)
                ),
                key=lambda m: (m.publisher_id != publisher_id, m.id),
                default=None,
            )
            if match is not None:
                taken.add(match.id)
                group.monograph_ids.add(match.id)
            volumes.append(group.volume())
    return volumes
