"""Vérification des ISSN d'une revue par les notices Sudoc.

Les ISSN de la revue connus du Sudoc sont regroupés. Deux ISSN vont ensemble quand leurs notices ont le même ISSN-L, quand l'une désigne l'autre comme la même publication sur un autre support (`452`), ou quand l'un est papier, l'autre en ligne, et que les mots d'un titre sont tous dans l'autre. Le groupe principal est le plus nombreux, départagé par la proximité des titres, puis par la succession des titres : le titre suivant l'emporte. Ses ISSN restent à la revue.

Les ISSN rejetés sont soit fautifs, soit périmés, soit d'une autre publication. La vérification range parmi eux les ISSN hors du groupe principal, les autres supports que le papier et l'en ligne (CD-ROM), les ISSN annulés et les titres précédents ou suivants. Un titre précédent ou suivant sur l'autre support, de même titre ou de même ISSN-L, marque un changement de support : il reste à la revue. La vérification corrige les ISSN fautifs à une faute de frappe près. Chaque ISSN restant va dans la colonne de son support ; un ISSN sans colonne libre rejoint les ISSN rejetés.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from enum import StrEnum
from itertools import combinations
from typing import NamedTuple

from domain.normalize import normalize_text
from domain.publications.identifiers import ISSN, issn_typo_candidates
from domain.sources.sudoc import SudocSerialRecord, Support

# Similarité minimale entre le titre de la revue et celui de la notice pour retenir une correction.
TITLE_SIMILARITY_MIN = 0.85
# Écart de similarité des titres en deçà duquel deux groupes d'ISSN de même taille restent à égalité.
TITLE_TIE_MARGIN = 0.1


class SetAsideReason(StrEnum):
    """Motif pour lequel un ISSN rejoint les ISSN rejetés."""

    OTHER_PUBLICATION = "autre publication"
    OTHER_SUPPORT = "autre support"
    CANCELLED = "ISSN annulé"
    RELATED_TITLE = "titre précédent ou suivant"
    NO_FREE_COLUMN = "sans colonne libre"


@dataclass(frozen=True, slots=True)
class JournalIssns:
    """ISSN d'une revue tels qu'en base."""

    title: str
    issn: str | None
    eissn: str | None
    issnl: str | None
    rejected: tuple[str, ...]

    def own(self) -> tuple[str, ...]:
        """ISSN des trois colonnes de la revue, sans doublon, dans l'ordre des colonnes."""
        return tuple(dict.fromkeys(v for v in (self.issn, self.eissn, self.issnl) if v))


@dataclass(frozen=True, slots=True)
class SudocCheck:
    """Résultat de la vérification des ISSN d'une revue."""

    issn: str | None
    eissn: str | None
    issnl: str | None
    rejected: tuple[str, ...]
    found: bool
    """Au moins un ISSN de la revue, ou une correction, a une notice dans le Sudoc."""
    conflict: bool
    """Deux groupes d'ISSN de même taille et de titres aussi proches : rien n'est modifié."""
    set_aside: tuple[tuple[str, SetAsideReason], ...]
    """ISSN rangés parmi les ISSN rejetés, avec leur motif."""
    corrections: tuple[tuple[str, str], ...]
    """Couples (valeur rejetée, ISSN corrigé)."""
    ambiguous_support: Support | None
    """Support dont la revue garde plusieurs ISSN : les ISSN restent dans leurs colonnes."""


def correction_candidates(rejected: Sequence[str]) -> frozenset[str]:
    """ISSN à chercher dans le Sudoc pour corriger les valeurs rejetées fautives. Une valeur valide n'est pas corrigée."""
    return frozenset(
        c for raw in rejected if ISSN.try_parse(raw) is None for c in issn_typo_candidates(raw)
    )


def _title_ratio(title: str, other: str | None) -> float:
    if not other:
        return 0.0
    return SequenceMatcher(None, normalize_text(title), normalize_text(other)).ratio()


def _nested_titles(a: str | None, b: str | None) -> bool:
    """Les mots d'un titre sont tous dans l'autre : « European archives » et « European archives and head & neck », pas « Physical review C » et « Physical review D »."""
    if not a or not b:
        return False
    words_a, words_b = set(normalize_text(a).split()), set(normalize_text(b).split())
    return bool(words_a and words_b) and (words_a <= words_b or words_b <= words_a)


def _same_title(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return normalize_text(a) == normalize_text(b)


def _complementary(a: SudocSerialRecord, b: SudocSerialRecord) -> bool:
    """L'une des notices décrit le papier, l'autre l'en ligne."""
    return {a.support, b.support} == {Support.PRINT, Support.ELECTRONIC}


def _same_publication(a: SudocSerialRecord, b: SudocSerialRecord) -> bool:
    if a.issnl is not None and a.issnl == b.issnl:
        return True
    if (b.issn in a.other_support_issns) or (a.issn in b.other_support_issns):
        return True
    return _complementary(a, b) and _nested_titles(a.title, b.title)


def _support_change(linking: SudocSerialRecord, linked: SudocSerialRecord) -> bool:
    """`linked`, que `linking` désigne comme titre précédent ou suivant, est la même publication sur l'autre support : même titre ou même ISSN-L. Le Sudoc code ainsi l'arrêt du papier au profit de l'en ligne."""
    same_issnl = linking.issnl is not None and linking.issnl == linked.issnl
    return _complementary(linking, linked) and (
        same_issnl or _same_title(linking.title, linked.title)
    )


def _groups(known: Sequence[str], records: Mapping[str, SudocSerialRecord]) -> list[list[str]]:
    """ISSN regroupés par publication (`_same_publication`)."""
    parent = {i: i for i in known}

    def root(i: str) -> str:
        while parent[i] != i:
            i = parent[i]
        return i

    for a, b in combinations(known, 2):
        if _same_publication(records[a], records[b]):
            parent[root(b)] = root(a)
    groups: dict[str, list[str]] = {}
    for i in known:
        groups.setdefault(root(i), []).append(i)
    return list(groups.values())


def _succeeds(
    later: Sequence[str], earlier: Sequence[str], records: Mapping[str, SudocSerialRecord]
) -> bool:
    """Une notice de `later` désigne un ISSN de `earlier` comme titre précédent, ou une notice de `earlier` désigne un ISSN de `later` comme titre suivant."""
    return any(x in earlier for i in later for x in records[i].preceding_issns) or any(
        x in later for i in earlier for x in records[i].succeeding_issns
    )


def _main_group(
    groups: Sequence[list[str]], records: Mapping[str, SudocSerialRecord], title: str
) -> list[str] | None:
    """Groupe le plus nombreux, départagé par la proximité des titres puis par la succession des titres, ou `None` en cas d'égalité."""

    def score(group: list[str]) -> tuple[int, float]:
        return len(group), max(_title_ratio(title, records[i].title) for i in group)

    ranked = sorted(groups, key=score, reverse=True)
    size, ratio = score(ranked[0])
    tied = [g for g in ranked if score(g)[0] == size and ratio - score(g)[1] < TITLE_TIE_MARGIN]
    latest = [g for g in tied if not any(_succeeds(h, g, records) for h in tied if h is not g)]
    return latest[0] if len(latest) == 1 else None


def _reference_issnl(
    members: Sequence[str], records: Mapping[str, SudocSerialRecord]
) -> str | None:
    """ISSN-L des notices du groupe. Un ISSN-L qui est l'ISSN d'un membre l'emporte : une notice porte parfois l'ISSN-L d'un titre précédent."""
    issnls = [issnl for i in members if (issnl := records[i].issnl)]
    pool = [issnl for issnl in issnls if issnl in members] or issnls
    return Counter(pool).most_common(1)[0][0] if pool else None


def check_journal_issns(
    journal: JournalIssns, records: Mapping[str, SudocSerialRecord]
) -> SudocCheck:
    """Vérifie les ISSN d'une revue.

    `records` porte la notice Sudoc de chaque ISSN connu du Sudoc : ISSN de la revue, candidats à la correction de ses ISSN rejetés (`correction_candidates`) et ISSN d'autre support de ses notices.
    """
    if journal.issn is not None and journal.issn == journal.eissn:
        # La même valeur dans les deux colonnes garde seulement la colonne de son support.
        online = (r := records.get(journal.issn)) is not None and r.support is Support.ELECTRONIC
        journal = replace(
            journal,
            issn=None if online else journal.issn,
            eissn=journal.eissn if online else None,
        )
    own = journal.own()
    known = [i for i in own if i in records]
    main: list[str] = []
    if groups := _groups(known, records):
        chosen = _main_group(groups, records, journal.title)
        if chosen is None:
            return SudocCheck(
                journal.issn,
                journal.eissn,
                journal.issnl,
                journal.rejected,
                found=True,
                conflict=True,
                set_aside=(),
                corrections=(),
                ambiguous_support=None,
            )
        main = chosen

    main_records = [records[i] for i in main]

    def title_links(links: Callable[[SudocSerialRecord], tuple[str, ...]]) -> set[str]:
        """ISSN que les notices du groupe principal désignent comme titres précédents ou suivants, hors changements de support."""
        return {
            x
            for r in main_records
            for x in links(r)
            if (linked := records.get(x)) is None or not _support_change(r, linked)
        }

    preceding = title_links(lambda r: r.preceding_issns)
    if all(i in preceding for i in main):
        # Des notices qui se désignent mutuellement comme titre précédent ne décident de rien.
        preceding -= set(main)
    related = preceding | title_links(lambda r: r.succeeding_issns)
    cancelled = {x for r in main_records for x in r.cancelled_issns}
    hints = {x: support for r in main_records for x, support in r.other_support_hints}

    set_aside: list[tuple[str, SetAsideReason]] = []
    kept: list[str] = []
    for i in own:
        record = records.get(i)
        support = record.support if record is not None else hints.get(i)
        if i in cancelled:
            set_aside.append((i, SetAsideReason.CANCELLED))
        elif (i in main or record is None) and support is Support.OTHER:
            set_aside.append((i, SetAsideReason.OTHER_SUPPORT))
        elif i in preceding or (record is not None and i not in main and i in related):
            set_aside.append((i, SetAsideReason.RELATED_TITLE))
        elif record is not None and i not in main:
            set_aside.append((i, SetAsideReason.OTHER_PUBLICATION))
        else:
            kept.append(i)
    reference = _reference_issnl([i for i in main if i in kept] or main, records)

    corrections: list[tuple[str, str]] = []
    for raw in journal.rejected:
        if ISSN.try_parse(raw) is not None:
            continue  # valeur valide, déjà classée : conservée telle quelle
        matches = sorted(
            c
            for c in issn_typo_candidates(raw)
            if (r := records.get(c))
            and _title_ratio(journal.title, r.title) >= TITLE_SIMILARITY_MIN
            and (reference is None or r.issnl == reference)
        )
        if len(matches) == 1:
            corrections.append((raw, matches[0]))
            reference = reference or records[matches[0]].issnl
            if matches[0] not in kept:
                kept.append(matches[0])

    issnl = reference or (journal.issnl if journal.issnl in kept else None)
    excluded = {i for i, _ in set_aside} | related | cancelled
    placement = _place(journal, kept, excluded, records, hints, reference)
    others = placement.other_publications

    placed = {placement.issn, placement.eissn, issnl}
    set_aside += [(i, SetAsideReason.OTHER_PUBLICATION) for i in others]
    set_aside += [
        (i, SetAsideReason.NO_FREE_COLUMN) for i in kept if i not in placed and i not in others
    ]
    # Un ISSN mis de côté qui est l'ISSN-L garde sa place dans `issnl`.
    set_aside = [(i, reason) for i, reason in set_aside if i not in placed]
    corrected = {raw for raw, _ in corrections}
    rejected = tuple(
        dict.fromkeys(
            [r for r in journal.rejected if r not in corrected and r not in placed]
            + [i for i, _ in set_aside]
        )
    )
    return SudocCheck(
        placement.issn,
        placement.eissn,
        issnl,
        rejected,
        found=bool(known) or bool(corrections),
        conflict=False,
        set_aside=tuple(set_aside),
        corrections=tuple(corrections),
        ambiguous_support=placement.ambiguous_support,
    )


def _narrow(
    candidates: list[str], records: Mapping[str, SudocSerialRecord], reference: str | None
) -> tuple[list[str], list[str]]:
    """ISSN d'un même support : `(restants, autres publications)`. Ceux dont la notice porte un autre ISSN-L que la revue sont d'une autre publication, puis l'ISSN-L, déjà dans `issnl`, cède la colonne."""
    others: list[str] = []
    if len(candidates) > 1 and reference is not None:
        same = [
            i
            for i in candidates
            if i == reference or i not in records or records[i].issnl in (None, reference)
        ]
        if same:
            others = [i for i in candidates if i not in same]
            candidates = same
    if len(candidates) > 1 and reference in candidates:
        candidates = [i for i in candidates if i != reference]
    return candidates, others


class _Placement(NamedTuple):
    issn: str | None
    eissn: str | None
    ambiguous_support: Support | None
    other_publications: tuple[str, ...]
    """ISSN d'un support occupé dont la notice porte un autre ISSN-L que la revue."""


def _place(
    journal: JournalIssns,
    kept: Sequence[str],
    excluded: set[str],
    records: Mapping[str, SudocSerialRecord],
    hints: Mapping[str, Support],
    reference: str | None,
) -> _Placement:
    """Chaque ISSN va dans la colonne de son support.

    Le support d'un ISSN vient de sa notice, ou à défaut de la mention de support que lui donne une notice de la revue (`452$t`). Un support manquant se complète par un ISSN d'autre support d'une notice de la revue. Quand plusieurs ISSN ont le même support, ceux dont la notice porte un autre ISSN-L que la revue sont d'une autre publication, puis l'ISSN-L, déjà dans `issnl`, cède la colonne. S'il en reste plusieurs, les ISSN restent dans leurs colonnes. Un ISSN de support inconnu reste dans sa colonne si elle est libre.
    """

    def support_of(i: str) -> Support | None:
        return records[i].support if i in records else hints.get(i)

    prints = [i for i in kept if support_of(i) is Support.PRINT]
    electronics = [i for i in kept if support_of(i) is Support.ELECTRONIC]
    unknown = [i for i in kept if i not in prints and i not in electronics]
    for i in [x for x in (*prints, *electronics) if x in records]:
        for other in records[i].other_support_issns:
            if other in kept or other in excluded:
                continue
            if support_of(other) is Support.PRINT and not prints:
                prints.append(other)
            elif support_of(other) is Support.ELECTRONIC and not electronics:
                electronics.append(other)

    prints, print_others = _narrow(prints, records, reference)
    electronics, electronic_others = _narrow(electronics, records, reference)
    other_publications = print_others + electronic_others
    ambiguous = (
        Support.PRINT if len(prints) > 1 else Support.ELECTRONIC if len(electronics) > 1 else None
    )
    if ambiguous is not None:

        def in_place(value: str | None) -> str | None:
            return value if value in kept and value not in other_publications else None

        return _Placement(
            in_place(journal.issn), in_place(journal.eissn), ambiguous, tuple(other_publications)
        )
    issn = prints[0] if prints else None
    eissn = electronics[0] if electronics else None
    for value in unknown:
        if value == journal.issn and issn is None:
            issn = value
        elif value == journal.eissn and eissn is None:
            eissn = value
    return _Placement(issn, eissn, None, tuple(other_publications))
