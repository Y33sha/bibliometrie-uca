"""Import du dump CSV DOAJ dans `serials.doaj_payload` (DOAJ = source de vérité), et typage en revue des entrées présentes dans le DOAJ.

Bulk, set-based : indexe les `serials` par leurs ISSN en O(1), remet `is_in_doaj = FALSE` partout, puis pour chaque row du dump matchée par ISSN écrit `doaj_payload` (dict CSV mis à plat) + `doaj_imported_at` + `is_in_doaj = TRUE`.

Découplé de la source des rows : la CLI `import_doaj_csv` lit un fichier local, le pipeline télécharge le dump quand le dernier import date de plus que le délai de rafraîchissement (`run_enrich_serials_from_doaj`). Les deux passent un itérable de dicts `{colonne CSV: valeur}`.
"""

import logging
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import Connection, func, select, update

from domain.dates import date_to_french
from domain.normalize import sanitize_optional_text
from domain.publications.identifiers import ISSN
from domain.serials.issns import IssnStatus
from domain.serials.serial import SerialType
from domain.types import JsonValue
from infrastructure.db.scalars import scalar_datetime_or_none
from infrastructure.db.tables import serial_issns, serials
from pipeline.http.dump_download import DumpUnavailableError
from pipeline.runtime.observability.log_format import BRANCH, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import waiting
from pipeline.runtime.observability.signals import signal_source_unavailable
from pipeline.transformation.publishing.serials.store import TYPE_NOT_MANUAL

LABEL = "Import du DOAJ"
"""Libellé de la sous-étape dans le journal de la phase."""

# Colonnes ISSN du dump CSV DOAJ.
ISSN_KEYS = (
    "Journal ISSN (print version)",
    "Journal EISSN (online version)",
)

COMMIT_EVERY = 1000

DownloadDump = Callable[[], AbstractContextManager[Iterable[dict[str, str]]]]
"""Télécharge le dump DOAJ et rend ses rows, le temps du bloc."""


@dataclass
class DoajImportStats:
    total_rows: int = 0
    no_issn_rows: int = 0  # rows du dump sans aucun ISSN valide
    orphan_rows: int = 0  # rows du dump dont l'ISSN est inconnu côté UCA
    matched: int = 0  # journaux UCA mis à is_in_doaj = TRUE


class SerialIssnRow(NamedTuple):
    """Un ISSN valide d'une revue, pour l'index par ISSN."""

    serial_id: int
    issn: str


def find_serial_issn_index(conn: Connection) -> list[SerialIssnRow]:
    """Les ISSN valides des revues, quel que soit leur statut : matière de l'index ISSN → revue à l'import du dump DOAJ."""
    return [
        SerialIssnRow(r.serial_id, r.issn)
        for r in conn.execute(
            select(serial_issns.c.serial_id, serial_issns.c.issn)
            .where(
                serial_issns.c.serial_id.is_not(None),
                serial_issns.c.status != IssnStatus.MALFORMED,
            )
            .order_by(serial_issns.c.id)
        ).all()
    ]


def update_serial_doaj(
    conn: Connection,
    serial_id: int,
    *,
    payload: Mapping[str, JsonValue] | None,
    imported_at: datetime,
    is_in_doaj: bool,
) -> None:
    """Pose `doaj_payload`, `doaj_imported_at` et `is_in_doaj` d'une revue présente dans le dump."""
    conn.execute(
        update(serials)
        .where(serials.c.id == serial_id)
        .values(doaj_payload=payload, doaj_imported_at=imported_at, is_in_doaj=is_in_doaj)
    )


def reset_is_in_doaj(conn: Connection) -> int:
    """Efface le drapeau `is_in_doaj` de toutes les revues où il est posé, le dump DOAJ faisant autorité — l'import le re-pose ensuite sur les revues matchées. Retourne le nombre de drapeaux effacés."""
    return conn.execute(
        update(serials).where(serials.c.is_in_doaj).values(is_in_doaj=False)
    ).rowcount


def type_doaj_serials_as_journals(conn: Connection) -> int:
    """Type en revue les entrées de type inconnu présentes dans le DOAJ, qui répertorie seulement des revues. Un type saisi à la main reste en l'état. Retourne le nombre d'entrées typées."""
    return conn.execute(
        update(serials)
        .where(serials.c.is_in_doaj, serials.c.serial_type == SerialType.UNKNOWN, TYPE_NOT_MANUAL)
        .values(serial_type=SerialType.JOURNAL)
    ).rowcount


def doaj_last_import_at(conn: Connection) -> datetime | None:
    """Date du dernier import DOAJ (`max(doaj_imported_at)`), `None` si jamais importé. Commande la staleness du téléchargement du dump."""
    return scalar_datetime_or_none(conn.execute(select(func.max(serials.c.doaj_imported_at))))


def clean_doaj_row(row: dict[str, str]) -> dict[str, str]:
    """Met les valeurs à plat et retire les clés vides — réduit le bruit JSONB.

    Le payload alimente l'affichage d'une fiche de revue et les requêtes qui le lisent par clé : ses valeurs reçoivent la même mise à plat que les champs moissonnés (balises, entités HTML et caractères invisibles retirés).
    """
    out: dict[str, str] = {}
    for k, v in row.items():
        cleaned = sanitize_optional_text(v)
        if cleaned:
            out[k] = cleaned
    return out


def _extract_issns(row: dict[str, str]) -> list[str]:
    """ISSN papier et électronique valides de la row CSV, normalisés."""
    return [
        str(issn)
        for key in ISSN_KEYS
        if (issn := ISSN.try_parse(sanitize_optional_text(row.get(key))))
    ]


def run_import_doaj_dump(
    conn: Connection,
    logger: logging.Logger,
    *,
    rows: Iterable[dict[str, str]],
    dry_run: bool = False,
    commit: bool = True,
) -> DoajImportStats:
    """Importe les rows du dump DOAJ. L'orchestrateur gère la transaction
    (commits par batch) sauf si `commit=False` (tests sous transaction
    rollbackée). Retourne les stats.

    Un dump où aucune revue n'est reconnue laisse les revues en l'état : il signale un format de dump changé plutôt qu'un DOAJ vidé.
    """
    # Index ISSN normalisé → serial_id (premier gagnant) pour matcher en O(1).
    issn_to_serial_id: dict[str, int] = {}
    for indexed_serial_id, issn in find_serial_issn_index(conn):
        issn_to_serial_id.setdefault(issn, indexed_serial_id)

    stats = DoajImportStats()
    matches: list[tuple[int, dict[str, str]]] = []
    seen: set[int] = set()
    for row in rows:
        stats.total_rows += 1
        issns = _extract_issns(row)
        if not issns:
            stats.no_issn_rows += 1
            continue
        serial_id = next((issn_to_serial_id[i] for i in issns if i in issn_to_serial_id), None)
        if serial_id is None:
            stats.orphan_rows += 1
            continue
        if serial_id in seen:
            # 2 rows DOAJ pour le même journal local : la 1re l'emporte.
            continue
        seen.add(serial_id)
        stats.matched += 1
        matches.append((serial_id, row))

    if dry_run or not matches:
        return stats
    # Le dump fait autorité : reset global avant de re-poser les TRUE.
    reset_is_in_doaj(conn)
    now = datetime.now(UTC)
    for written, (serial_id, row) in enumerate(matches, 1):
        update_serial_doaj(
            conn, serial_id, payload=clean_doaj_row(row), imported_at=now, is_in_doaj=True
        )
        if commit and written % COMMIT_EVERY == 0:
            conn.commit()
    if commit:
        conn.commit()
    return stats


def run_enrich_serials_from_doaj(
    conn: Connection,
    logger: logging.Logger,
    *,
    refresh_after_days: int,
    download_dump: DownloadDump,
) -> PhaseMetrics:
    """Télécharge et importe le dump DOAJ quand le dernier import date de plus de `refresh_after_days` jours, puis type en revue les entrées présentes dans le DOAJ (`type_doaj_serials_as_journals`).

    Un dump inaccessible laisse le référentiel inchangé et signale la source indisponible : la phase continue, l'import est repris au run suivant.
    """
    metrics = _import_doaj(
        conn, logger, refresh_after_days=refresh_after_days, download_dump=download_dump
    )
    type_doaj_serials_as_journals(conn)
    return metrics


def _import_doaj(
    conn: Connection,
    logger: logging.Logger,
    *,
    refresh_after_days: int,
    download_dump: DownloadDump,
) -> PhaseMetrics:
    """Import du dump DOAJ de `run_enrich_serials_from_doaj`."""
    last = doaj_last_import_at(conn)
    refresh_delay = timedelta(days=refresh_after_days)
    if last is not None and last > datetime.now(UTC) - refresh_delay:
        metrics = PhaseMetrics(extras={"skipped": 1})
        metrics.report = (
            f"importé le {date_to_french(last.date())}, "
            f"prochain import le {date_to_french((last + refresh_delay).date())}"
        )
        return metrics

    try:
        with waiting(f"{BRANCH}{LABEL}", logger) as line:
            line.erase()
            with download_dump() as rows:
                stats = run_import_doaj_dump(conn, logger, rows=rows)
    except DumpUnavailableError as e:
        # Le téléchargement précède toute écriture : le référentiel reste celui du dernier import.
        metrics = PhaseMetrics()
        logger.warning("Dump DOAJ inaccessible, référentiel inchangé : %s", e)
        signal_source_unavailable(metrics, "DOAJ", logger=logger, phase="publishing")
        metrics.report = "dump inaccessible, import repris au prochain run"
        return metrics
    metrics = PhaseMetrics(extras={"matched": stats.matched})
    if stats.matched == 0:
        message = f"DOAJ : aucune revue reconnue parmi {stats.total_rows} lignes de l'export, revues inchangées"
        logger.warning(message)
        metrics.signals.append(
            {"level": "warning", "code": "dump_unrecognized", "message": message}
        )
        metrics.report = "aucune revue reconnue, revues inchangées"
        return metrics
    metrics.report = quantity(stats.matched, "revue mise à jour", "revues mises à jour")
    return metrics
