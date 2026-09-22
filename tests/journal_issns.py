"""Construction des ISSN d'une revue de test à partir de champs papier, électronique, ISSN-L et valeurs mises de côté."""

from collections.abc import Iterable, Mapping

from domain.journals.issns import IssnStatus, IssnSupport, JournalIssn
from domain.publications.identifiers import ISSN


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
    """ISSN d'une revue décrite par ses champs `issn` (papier), `eissn` (en ligne), `issnl` (drapeau ISSN-L) et ses valeurs mises de côté : `malformed` si invalides, `unverified` sinon, sauf statut fourni par `statuses`."""
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
