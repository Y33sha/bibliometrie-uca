"""ISSN d'une revue : support, ISSN-L et statut de chaque valeur."""

from collections.abc import Iterable, Mapping, Sequence
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


def issns_from_columns(
    issn: str | None,
    eissn: str | None,
    issnl: str | None,
    rejected: Iterable[str] = (),
    *,
    statuses: Mapping[str, IssnStatus] | None = None,
    supports: Mapping[str, IssnSupport] | None = None,
    replaced_by: Mapping[str, str] | None = None,
) -> list[JournalIssn]:
    """ISSN d'une revue décrite par ses champs `issn`, `eissn`, `issnl` et ses valeurs mises de côté.

    `issn` est l'ISSN papier actif, `eissn` l'ISSN électronique actif, `issnl` porte le drapeau ISSN-L. Une valeur mise de côté prend son statut dans `statuses` ; à défaut, `malformed` si elle est invalide, `unverified` sinon. `supports` et `replaced_by` complètent chaque valeur.
    """
    statuses = statuses or {}
    supports = supports or {}
    replaced_by = replaced_by or {}
    rows: dict[str, JournalIssn] = {}
    for value, support in ((issn, IssnSupport.PRINT), (eissn, IssnSupport.ELECTRONIC)):
        if value and value not in rows:
            rows[value] = JournalIssn(issn=value, support=support)
    for value in rejected:
        if value in rows:
            continue
        default = IssnStatus.UNVERIFIED if ISSN.try_parse(value) else IssnStatus.MALFORMED
        rows[value] = JournalIssn(
            issn=value,
            support=supports.get(value),
            status=statuses.get(value, default),
            replaced_by=replaced_by.get(value),
        )
    if issnl:
        row = rows.get(issnl) or JournalIssn(issn=issnl, support=supports.get(issnl))
        rows[issnl] = JournalIssn(
            issn=row.issn,
            support=row.support,
            linking=True,
            status=IssnStatus.ACTIVE,
            replaced_by=row.replaced_by,
        )
    return list(rows.values())


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
