"""Construction des ISSN d'une revue de test à partir de champs papier, électronique, ISSN-L et valeurs mises de côté."""

from collections.abc import Iterable, Mapping

from domain.publications.identifiers import ISSN
from domain.serials.issns import IssnStatus, IssnSupport, SerialIssn


def issns_from_columns(
    issn: str | None,
    eissn: str | None,
    issnl: str | None,
    rejected: Iterable[str] = (),
    *,
    statuses: Mapping[str, IssnStatus] | None = None,
    supports: Mapping[str, IssnSupport] | None = None,
) -> list[SerialIssn]:
    """Construit les ISSN d'une revue décrite par ses champs `issn` (papier), `eissn` (en ligne), `issnl` (ISSN-L, actif) et ses valeurs mises de côté.

    Une valeur mise de côté a le statut `malformed` si elle est invalide, `unverified` sinon, sauf statut donné par `statuses` ; son support est donné par `supports`.
    """
    statuses = statuses or {}
    supports = supports or {}
    rows: dict[str, SerialIssn] = {}
    for value, support in ((issn, IssnSupport.PRINT), (eissn, IssnSupport.ELECTRONIC)):
        if value and value not in rows:
            rows[value] = SerialIssn(issn=value, support=support)
    for value in rejected:
        if value in rows:
            continue
        default = IssnStatus.UNVERIFIED if ISSN.try_parse(value) else IssnStatus.MALFORMED
        rows[value] = SerialIssn(
            issn=value,
            support=supports.get(value),
            status=statuses.get(value, default),
        )
    if issnl:
        row = rows.get(issnl) or SerialIssn(issn=issnl, support=supports.get(issnl))
        rows[issnl] = SerialIssn(
            issn=row.issn,
            support=row.support,
            linking=True,
            status=IssnStatus.ACTIVE,
        )
    return list(rows.values())
