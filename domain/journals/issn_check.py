"""Vérification des ISSN d'une revue par les notices Sudoc.

Les ISSN d'une même revue partagent un ISSN-L. La vérification retient l'ISSN-L majoritaire parmi les notices des ISSN de la revue et retire les ISSN d'un autre ISSN-L. Elle corrige les ISSN rejetés à une faute de frappe près, puis range chaque ISSN dans la colonne de son support.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from domain.normalize import normalize_text
from domain.publications.identifiers import issn_typo_candidates
from domain.sources.sudoc import SudocSerialRecord, Support

# Similarité minimale entre le titre de la revue et celui de la notice pour retenir une correction.
TITLE_SIMILARITY_MIN = 0.85


@dataclass(frozen=True, slots=True)
class JournalIssns:
    """ISSN d'une revue tels qu'en base."""

    title: str
    issn: str | None
    eissn: str | None
    issnl: str | None
    rejected: tuple[str, ...]

    def own(self) -> tuple[str, ...]:
        """ISSN valides de la revue, sans doublon, dans l'ordre des colonnes."""
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
    """Les ISSN de la revue se partagent à égalité entre plusieurs ISSN-L : rien n'est modifié."""
    intruders: tuple[str, ...]
    """ISSN retirés : leur ISSN-L diffère de celui de la revue."""
    corrections: tuple[tuple[str, str], ...]
    """Couples (valeur rejetée, ISSN corrigé)."""
    ambiguous_support: bool
    """Plusieurs ISSN d'un même support, ou un ISSN sans notice sans colonne libre : les ISSN restent dans leurs colonnes."""


def correction_candidates(rejected: Sequence[str]) -> frozenset[str]:
    """ISSN à chercher dans le Sudoc pour corriger des valeurs rejetées."""
    return frozenset(c for raw in rejected for c in issn_typo_candidates(raw))


def _same_title(title: str, other: str | None) -> bool:
    if not other:
        return False
    ratio = SequenceMatcher(None, normalize_text(title), normalize_text(other)).ratio()
    return ratio >= TITLE_SIMILARITY_MIN


def _reference_issnl(
    own: Sequence[str], records: Mapping[str, SudocSerialRecord]
) -> tuple[str | None, bool]:
    """ISSN-L majoritaire parmi les notices des ISSN de la revue, et drapeau d'égalité entre ISSN-L."""
    votes = Counter(record.issnl for i in own if (record := records.get(i)) and record.issnl)
    ranked = votes.most_common()
    if not ranked:
        return None, False
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None, True
    return ranked[0][0], False


def check_journal_issns(
    journal: JournalIssns, records: Mapping[str, SudocSerialRecord]
) -> SudocCheck:
    """Vérifie les ISSN d'une revue.

    `records` porte la notice Sudoc de chaque ISSN connu du Sudoc : ISSN de la revue et candidats à la correction de ses ISSN rejetés (`correction_candidates`).
    """
    own = journal.own()
    reference, conflict = _reference_issnl(own, records)
    if conflict:
        return SudocCheck(
            journal.issn,
            journal.eissn,
            journal.issnl,
            journal.rejected,
            found=True,
            conflict=True,
            intruders=(),
            corrections=(),
            ambiguous_support=False,
        )
    intruders = tuple(i for i in own if (r := records.get(i)) and r.issnl and r.issnl != reference)
    kept = [i for i in own if i not in intruders]

    corrections: list[tuple[str, str]] = []
    for raw in journal.rejected:
        matches = sorted(
            c
            for c in issn_typo_candidates(raw)
            if (r := records.get(c))
            and _same_title(journal.title, r.title)
            and (reference is None or r.issnl == reference)
        )
        if len(matches) == 1:
            corrections.append((raw, matches[0]))
            reference = reference or records[matches[0]].issnl
            if matches[0] not in kept:
                kept.append(matches[0])

    found = reference is not None or bool(intruders)
    issnl = reference or (journal.issnl if journal.issnl not in intruders else None)

    prints = [i for i in kept if (r := records.get(i)) and r.support is Support.PRINT]
    electronics = [i for i in kept if (r := records.get(i)) and r.support is Support.ELECTRONIC]
    unknown = [i for i in kept if i not in prints and i not in electronics]
    # L'ISSN de l'autre support (`452`) complète un support manquant.
    for i in (*prints, *electronics):
        record = records[i]
        for other in record.other_support_issns:
            if other in kept:
                continue
            if record.support is Support.PRINT and not electronics:
                electronics.append(other)
            elif record.support is Support.ELECTRONIC and not prints:
                prints.append(other)

    placed = _place(journal, issnl, prints, electronics, unknown)
    if placed is None:
        # Placement impossible sans perte : seuls les ISSN d'un autre ISSN-L sont retirés.
        return SudocCheck(
            journal.issn if journal.issn not in intruders else None,
            journal.eissn if journal.eissn not in intruders else None,
            issnl
            if journal.issnl in (None, issnl) or journal.issnl in intruders
            else journal.issnl,
            journal.rejected,
            found=found,
            conflict=False,
            intruders=intruders,
            corrections=(),
            ambiguous_support=True,
        )
    corrected = {raw for raw, _ in corrections}
    return SudocCheck(
        placed[0],
        placed[1],
        issnl,
        tuple(r for r in journal.rejected if r not in corrected),
        found=found,
        conflict=False,
        intruders=intruders,
        corrections=tuple(corrections),
        ambiguous_support=False,
    )


def _place(
    journal: JournalIssns,
    issnl: str | None,
    prints: Sequence[str],
    electronics: Sequence[str],
    unknown: Sequence[str],
) -> tuple[str | None, str | None] | None:
    """`(issn, eissn)` rangés par support, ou `None` si le rangement perdrait un ISSN.

    Un ISSN sans notice reste dans sa colonne si elle est libre après le rangement.
    """
    if len(prints) > 1 or len(electronics) > 1:
        return None
    issn = prints[0] if prints else None
    eissn = electronics[0] if electronics else None
    for value in unknown:
        if value == journal.issn and issn in (None, value):
            issn = value
        elif value == journal.eissn and eissn in (None, value):
            eissn = value
        elif value != issnl:
            return None
    return issn, eissn
