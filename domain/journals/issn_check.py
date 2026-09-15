"""Vérification des ISSN d'une revue par les notices Sudoc.

Les ISSN de la revue connus du Sudoc sont regroupés : deux ISSN vont ensemble quand leurs notices ont le même ISSN-L, ou quand l'une désigne l'autre comme la même publication sur un autre support (`452`). Le groupe principal est le plus nombreux, départagé par la proximité des titres. Un ISSN hors du groupe principal est retiré, sauf s'il désigne un titre précédent ou suivant de la revue.

Les ISSN rejetés sont soit fautifs, soit périmés : autre support que le papier et l'en ligne (CD-ROM), ISSN annulé, titre précédent ou suivant. La vérification range les ISSN périmés parmi eux et corrige les fautifs à une faute de frappe près. Chaque ISSN restant va dans la colonne de son support ; un ISSN sans colonne libre rejoint les ISSN rejetés.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
from itertools import combinations

from domain.normalize import normalize_text
from domain.publications.identifiers import ISSN, issn_typo_candidates
from domain.sources.sudoc import SudocSerialRecord, Support

# Similarité minimale entre le titre de la revue et celui de la notice pour retenir une correction.
TITLE_SIMILARITY_MIN = 0.85
# Écart de similarité des titres en deçà duquel deux groupes d'ISSN de même taille restent à égalité.
TITLE_TIE_MARGIN = 0.1


class SetAsideReason(StrEnum):
    """Motif pour lequel un ISSN rejoint les ISSN rejetés."""

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
    intruders: tuple[str, ...]
    """ISSN retirés : ils désignent une autre publication."""
    set_aside: tuple[tuple[str, SetAsideReason], ...]
    """ISSN rangés parmi les ISSN rejetés, avec leur motif."""
    corrections: tuple[tuple[str, str], ...]
    """Couples (valeur rejetée, ISSN corrigé)."""
    ambiguous_support: Support | None
    """Support dont la revue garde plusieurs ISSN : les ISSN restent dans leurs colonnes."""


def correction_candidates(rejected: Sequence[str]) -> frozenset[str]:
    """ISSN à chercher dans le Sudoc pour corriger les valeurs rejetées fautives. Une valeur valide, périmée, n'est pas corrigée."""
    return frozenset(
        c for raw in rejected if ISSN.try_parse(raw) is None for c in issn_typo_candidates(raw)
    )


def _title_ratio(title: str, other: str | None) -> float:
    if not other:
        return 0.0
    return SequenceMatcher(None, normalize_text(title), normalize_text(other)).ratio()


def _groups(known: Sequence[str], records: Mapping[str, SudocSerialRecord]) -> list[list[str]]:
    """ISSN regroupés par ISSN-L commun ou par lien d'autre support (`452`)."""
    parent = {i: i for i in known}

    def root(i: str) -> str:
        while parent[i] != i:
            i = parent[i]
        return i

    for a, b in combinations(known, 2):
        ra, rb = records[a], records[b]
        same_issnl = ra.issnl is not None and ra.issnl == rb.issnl
        if same_issnl or b in ra.other_support_issns or a in rb.other_support_issns:
            parent[root(b)] = root(a)
    groups: dict[str, list[str]] = {}
    for i in known:
        groups.setdefault(root(i), []).append(i)
    return list(groups.values())


def _main_group(
    groups: Sequence[list[str]], records: Mapping[str, SudocSerialRecord], title: str
) -> list[str] | None:
    """Groupe le plus nombreux, départagé par la proximité des titres, ou `None` en cas d'égalité."""

    def score(group: list[str]) -> tuple[int, float]:
        return len(group), max(_title_ratio(title, records[i].title) for i in group)

    ranked = sorted(groups, key=score, reverse=True)
    if len(ranked) > 1:
        (size, ratio), (next_size, next_ratio) = score(ranked[0]), score(ranked[1])
        if size == next_size and ratio - next_ratio < TITLE_TIE_MARGIN:
            return None
    return ranked[0]


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
                intruders=(),
                set_aside=(),
                corrections=(),
                ambiguous_support=None,
            )
        main = chosen
    reference = _reference_issnl(main, records)

    main_records = [records[i] for i in main]
    preceding = {x for r in main_records for x in r.preceding_issns}
    if all(i in preceding for i in main):
        # Des notices qui se désignent mutuellement comme titre précédent ne décident de rien.
        preceding -= set(main)
    related = preceding | {x for r in main_records for x in r.succeeding_issns}
    cancelled = {x for r in main_records for x in r.cancelled_issns}

    set_aside: list[tuple[str, SetAsideReason]] = []
    intruders: list[str] = []
    kept: list[str] = []
    for i in own:
        record = records.get(i)
        if i in cancelled:
            set_aside.append((i, SetAsideReason.CANCELLED))
        elif i in main and record is not None and record.support is Support.OTHER:
            set_aside.append((i, SetAsideReason.OTHER_SUPPORT))
        elif i in preceding or (record is not None and i not in main and i in related):
            set_aside.append((i, SetAsideReason.RELATED_TITLE))
        elif record is not None and i not in main:
            intruders.append(i)
        else:
            kept.append(i)

    corrections: list[tuple[str, str]] = []
    for raw in journal.rejected:
        if ISSN.try_parse(raw) is not None:
            continue  # valeur valide, périmée : conservée telle quelle
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
    issn, eissn, ambiguous = _place(journal, kept, intruders, records)

    placed = {issn, eissn, issnl}
    set_aside += [(i, SetAsideReason.NO_FREE_COLUMN) for i in kept if i not in placed]
    corrected = {raw for raw, _ in corrections}
    rejected = tuple(
        dict.fromkeys(
            [r for r in journal.rejected if r not in corrected]
            + [i for i, _ in set_aside if i not in placed]
        )
    )
    return SudocCheck(
        issn,
        eissn,
        issnl,
        rejected,
        found=bool(known) or bool(corrections),
        conflict=False,
        intruders=tuple(intruders),
        set_aside=tuple(set_aside),
        corrections=tuple(corrections),
        ambiguous_support=ambiguous,
    )


def _place(
    journal: JournalIssns,
    kept: Sequence[str],
    intruders: Sequence[str],
    records: Mapping[str, SudocSerialRecord],
) -> tuple[str | None, str | None, Support | None]:
    """`(issn, eissn, support ambigu)`. Chaque ISSN va dans la colonne de son support.

    Une notice complète le support manquant par l'ISSN d'autre support (`452`) dont la notice est connue. Un ISSN sans notice reste dans sa colonne si elle est libre. Plusieurs ISSN d'un même support laissent les ISSN dans leurs colonnes.
    """
    prints = [i for i in kept if (r := records.get(i)) and r.support is Support.PRINT]
    electronics = [i for i in kept if (r := records.get(i)) and r.support is Support.ELECTRONIC]
    unknown = [i for i in kept if i not in prints and i not in electronics]
    for i in (*prints, *electronics):
        for other in records[i].other_support_issns:
            if other in kept or other in intruders or other not in records:
                continue
            if records[other].support is Support.PRINT and not prints:
                prints.append(other)
            elif records[other].support is Support.ELECTRONIC and not electronics:
                electronics.append(other)

    ambiguous = (
        Support.PRINT if len(prints) > 1 else Support.ELECTRONIC if len(electronics) > 1 else None
    )
    if ambiguous is not None:
        return (
            journal.issn if journal.issn in kept else None,
            journal.eissn if journal.eissn in kept else None,
            ambiguous,
        )
    issn = prints[0] if prints else None
    eissn = electronics[0] if electronics else None
    for value in unknown:
        if value == journal.issn and issn is None:
            issn = value
        elif value == journal.eissn and eissn is None:
            eissn = value
    return issn, eissn, None
