"""ISSN d'une revue : support, ISSN-L et statut de chaque valeur."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from domain.errors import ValidationError
from domain.publications.identifiers import ISSN


class IssnSupport(StrEnum):
    """Support d'une publication en série."""

    PRINT = "print"
    ELECTRONIC = "electronic"
    """Ressource en ligne."""
    OTHER = "other"
    """Autre support : CD-ROM, microforme…"""


class IssnStatus(StrEnum):
    """Statut d'un ISSN dans sa revue."""

    ACTIVE = "active"
    MALFORMED = "malformed"
    """Forme ou clé de contrôle fausse : la valeur est gardée telle que reçue."""
    CANCELLED = "cancelled"
    RELATED_TITLE = "related_title"
    """ISSN d'un titre précédent ou suivant."""
    SUPPLEMENT = "supplement"
    UNVERIFIED = "unverified"
    """Valeur valide mise de côté, de motif inconnu : la vérification Sudoc le donne."""


ISSN_SUPPORTS = tuple(IssnSupport)
ISSN_STATUSES = tuple(IssnStatus)


@dataclass(frozen=True, slots=True, kw_only=True)
class JournalIssn:
    """Un ISSN d'une revue."""

    issn: str
    support: IssnSupport | None = None
    linking: bool = False
    status: IssnStatus = IssnStatus.ACTIVE
    replaced_by: str | None = None


def received_issns(issns: Iterable[JournalIssn]) -> tuple[JournalIssn, ...]:
    """ISSN reçus d'une source, normalisés, sans doublon.

    Une valeur invalide garde sa forme reçue, au statut `malformed`. Deux mentions d'une même valeur n'en font qu'une : le premier support connu, le drapeau ISSN-L de l'une ou l'autre.
    """
    rows: dict[str, JournalIssn] = {}
    for row in issns:
        raw = row.issn.strip()
        if not raw:
            continue
        issn = ISSN.try_parse(raw)
        value = str(issn) if issn else raw
        status = row.status if issn else IssnStatus.MALFORMED
        if value in rows:
            known = rows[value]
            rows[value] = JournalIssn(
                issn=value,
                support=known.support or row.support,
                linking=known.linking or row.linking,
                status=known.status,
                replaced_by=known.replaced_by,
            )
        else:
            rows[value] = JournalIssn(
                issn=value,
                support=row.support,
                linking=row.linking and issn is not None,
                status=status,
                replaced_by=row.replaced_by,
            )
    return tuple(rows.values())


def source_issns(
    *,
    print_issn: str | None = None,
    electronic_issn: str | None = None,
    unknown: Iterable[str | None] = (),
    linking: str | None = None,
) -> tuple[JournalIssn, ...]:
    """ISSN tels qu'une source les donne : papier, en ligne, ou de support inconnu. `linking` est l'ISSN-L."""
    return received_issns(
        [
            *(
                JournalIssn(issn=value, support=support)
                for value, support in (
                    (print_issn, IssnSupport.PRINT),
                    (electronic_issn, IssnSupport.ELECTRONIC),
                )
                if value
            ),
            *(JournalIssn(issn=value) for value in unknown if value),
            *([JournalIssn(issn=linking, linking=True)] if linking else []),
        ]
    )


def validate_journal_issns(issns: Iterable[JournalIssn]) -> list[JournalIssn]:
    """ISSN d'une revue saisis à la main, normalisés. Lève `ValidationError` sur une valeur invalide hors statut `malformed`, sur un ISSN en double et sur plusieurs ISSN-L."""
    rows: list[JournalIssn] = []
    for row in issns:
        value = row.issn.strip()
        if row.status is not IssnStatus.MALFORMED:
            value = str(ISSN(value))
        if any(r.issn == value for r in rows):
            raise ValidationError(f"ISSN en double : {value}")
        replaced_by = str(ISSN(row.replaced_by)) if row.replaced_by else None
        rows.append(
            JournalIssn(
                issn=value,
                support=row.support,
                linking=row.linking,
                status=row.status,
                replaced_by=replaced_by,
            )
        )
    if sum(r.linking for r in rows) > 1:
        raise ValidationError("Une revue a au plus un ISSN-L")
    return rows


def issn_conflict(first: Sequence[JournalIssn], second: Sequence[JournalIssn]) -> str | None:
    """Contradiction entre les ISSN de deux revues de même titre, ou `None`.

    Deux revues se contredisent quand elles ont chacune un ISSN actif d'un même support sans en partager aucun, ou deux ISSN-L différents.
    """

    def active(rows: Sequence[JournalIssn], support: IssnSupport) -> set[str]:
        return {r.issn for r in rows if r.status is IssnStatus.ACTIVE and r.support is support}

    for support, label in (
        (IssnSupport.PRINT, "ISSN papier"),
        (IssnSupport.ELECTRONIC, "ISSN en ligne"),
    ):
        a, b = active(first, support), active(second, support)
        if a and b and not a & b:
            return f"{label} différents : {', '.join(sorted(a))} / {', '.join(sorted(b))}"
    a_issnl = next((r.issn for r in first if r.linking), None)
    b_issnl = next((r.issn for r in second if r.linking), None)
    if a_issnl and b_issnl and a_issnl != b_issnl:
        return f"ISSN-L différents : {a_issnl} / {b_issnl}"
    return None
