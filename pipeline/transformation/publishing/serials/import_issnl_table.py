"""Import de la table ISSN-L de l'ISSN International Centre, qui fait autorité sur `serial_issns.issnl`.

Chaque ISSN de `serial_issns` reçoit son ISSN-L d'après la table, `NULL` s'il en est absent, et la date de l'import (`issnl_checked_at`). Un ISSN ajouté après l'import attend le suivant. Le pipeline télécharge la table quand le dernier import date de plus de `issnl_table_refresh_after_days` jours.
"""

import json
import logging
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, text

from domain.dates import date_to_french
from domain.documents.identifiers import ISSN
from domain.pipeline_runs import PhaseStatus
from pipeline.http.dump_download import DumpUnavailableError
from pipeline.runtime.observability.log_format import BRANCH, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import waiting
from pipeline.runtime.observability.signals import signal_source_unavailable

LABEL = "Import de la table ISSN-L"
"""Libellé de la sous-étape dans le journal de la phase."""

DownloadTable = Callable[[], AbstractContextManager[Iterable[tuple[str, str]]]]
"""Télécharge la table ISSN-L et renvoie ses couples (ISSN, ISSN-L), le temps du bloc."""

_LAST_IMPORT = text("SELECT max(issnl_checked_at) FROM serial_issns")

_CURRENT = text("SELECT issn, issnl FROM serial_issns")

_RESET = text("""
    UPDATE serial_issns SET issnl = NULL, issnl_checked_at = :checked_at
    WHERE issn = ANY(:issns)
""")

_WRITE = text("""
    UPDATE serial_issns s SET issnl = t.issnl
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(issn text, issnl text)
    WHERE s.issn = t.issn
""")


def run_import_issnl_table(
    conn: Connection,
    logger: logging.Logger,
    *,
    refresh_after_days: int,
    download_table: DownloadTable,
) -> PhaseMetrics:
    """Télécharge et importe la table ISSN-L quand le dernier import date de plus de `refresh_after_days` jours.

    Une table inaccessible, ou sans aucun de nos ISSN, laisse les ISSN-L inchangés : la phase continue, l'import est repris au run suivant.
    """
    last = conn.execute(_LAST_IMPORT).scalar()
    refresh_delay = timedelta(days=refresh_after_days)
    if last is not None and last > datetime.now(UTC) - refresh_delay:
        metrics = PhaseMetrics(extras={"skipped": 1})
        metrics.report = (
            f"importée le {date_to_french(last.date())}, "
            f"prochain import le {date_to_french((last + refresh_delay).date())}"
        )
        return metrics

    current: dict[str, str | None] = {r.issn: r.issnl for r in conn.execute(_CURRENT)}
    try:
        with waiting(f"{BRANCH}{LABEL}", logger) as line:
            line.erase()
            with download_table() as pairs:
                found = {
                    issn: str(issnl)
                    for issn, raw_issnl in pairs
                    if issn in current and (issnl := ISSN.try_parse(raw_issnl))
                }
    except DumpUnavailableError as e:
        metrics = PhaseMetrics()
        signal_source_unavailable(
            metrics,
            "ISSN International Centre",
            logger=logger,
            reason=f"Table ISSN-L inaccessible, ISSN-L inchangés : {e}",
        )
        metrics.report = "table inaccessible, import repris au prochain run"
        return metrics
    if not found:
        message = "Table ISSN-L : aucun ISSN de la base reconnu, ISSN-L inchangés"
        logger.warning(message)
        metrics = PhaseMetrics()
        metrics.signals.append(
            {"level": PhaseStatus.WARNING, "code": "dump_unrecognized", "message": message}
        )
        metrics.report = "aucun ISSN reconnu, ISSN-L inchangés"
        return metrics

    conn.execute(_RESET, {"issns": list(current), "checked_at": datetime.now(UTC)})
    conn.execute(
        _WRITE,
        {"rows": json.dumps([{"issn": issn, "issnl": issnl} for issn, issnl in found.items()])},
    )
    changed = sum(1 for issn, issnl in current.items() if found.get(issn) != issnl)
    metrics = PhaseMetrics(extras={"matched": len(found), "changed": changed})
    metrics.report = (
        f"{quantity(len(found), 'ISSN trouvé', 'ISSN trouvés')} dans la table, "
        f"{quantity(changed, 'ISSN-L modifié', 'ISSN-L modifiés')}"
    )
    return metrics
