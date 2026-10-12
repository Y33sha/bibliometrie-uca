"""Import du dump CSV DOAJ dans `journals.doaj_payload` (DOAJ = source de vérité).

Bulk, set-based : indexe les `journals` par leurs ISSN en O(1), remet `is_in_doaj = FALSE` partout, puis pour chaque row du dump matchée par ISSN écrit `doaj_payload` (dict CSV mis à plat) + `doaj_imported_at` + `is_in_doaj = TRUE`.

Découplé de la source des rows : la CLI `import_doaj_csv` lit un fichier local, le pipeline télécharge le dump quand le dernier import date de plus que le délai de rafraîchissement (`run_enrich_journals_from_doaj`). Les deux passent un itérable de dicts `{colonne CSV: valeur}`.
"""

import logging
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection

from domain.dates import date_to_french
from domain.normalize import sanitize_optional_text
from domain.publications.identifiers import ISSN
from pipeline.ingestion.http.dump_download import DumpUnavailableError
from pipeline.publishing.journals.journals import JournalGatewayQueries
from pipeline.runtime.libelles import BRANCHE, accord
from pipeline.runtime.metrics import PhaseMetrics
from pipeline.runtime.progression import attente
from pipeline.runtime.signals import signal_source_unavailable

LIBELLE = "Import du DOAJ"
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
    journal_repo: JournalGatewayQueries,
    rows: Iterable[dict[str, str]],
    dry_run: bool = False,
    commit: bool = True,
) -> DoajImportStats:
    """Importe les rows du dump DOAJ. L'orchestrateur gère la transaction
    (commits par batch) sauf si `commit=False` (tests sous transaction
    rollbackée). Retourne les stats.

    Un dump où aucune revue n'est reconnue laisse les revues en l'état : il signale un format de dump changé plutôt qu'un DOAJ vidé.
    """
    # Index ISSN normalisé → journal_id (premier gagnant) pour matcher en O(1).
    issn_to_journal_id: dict[str, int] = {}
    for indexed_journal_id, issn in journal_repo.find_journal_issn_index():
        issn_to_journal_id.setdefault(issn, indexed_journal_id)

    stats = DoajImportStats()
    matches: list[tuple[int, dict[str, str]]] = []
    seen: set[int] = set()
    for row in rows:
        stats.total_rows += 1
        issns = _extract_issns(row)
        if not issns:
            stats.no_issn_rows += 1
            continue
        journal_id = next((issn_to_journal_id[i] for i in issns if i in issn_to_journal_id), None)
        if journal_id is None:
            stats.orphan_rows += 1
            continue
        if journal_id in seen:
            # 2 rows DOAJ pour le même journal local : la 1re l'emporte.
            continue
        seen.add(journal_id)
        stats.matched += 1
        matches.append((journal_id, row))

    if dry_run or not matches:
        return stats
    # Le dump fait autorité : reset global avant de re-poser les TRUE.
    journal_repo.reset_is_in_doaj()
    now = datetime.now(UTC)
    for written, (journal_id, row) in enumerate(matches, 1):
        journal_repo.update_journal_doaj(
            journal_id, payload=clean_doaj_row(row), imported_at=now, is_in_doaj=True
        )
        if commit and written % COMMIT_EVERY == 0:
            conn.commit()
    if commit:
        conn.commit()
    return stats


def run_enrich_journals_from_doaj(
    conn: Connection,
    logger: logging.Logger,
    *,
    journal_repo: JournalGatewayQueries,
    refresh_after_days: int,
    download_dump: DownloadDump,
) -> PhaseMetrics:
    """Télécharge et importe le dump DOAJ quand le dernier import date de plus de `refresh_after_days` jours.

    Un dump inaccessible laisse le référentiel inchangé et signale la source indisponible : la phase continue, l'import est repris au run suivant.
    """
    last = journal_repo.doaj_last_import_at()
    delai = timedelta(days=refresh_after_days)
    if last is not None and last > datetime.now(UTC) - delai:
        metrics = PhaseMetrics(extras={"skipped": 1})
        metrics.resume = (
            f"importé le {date_to_french(last.date())}, "
            f"prochain import le {date_to_french((last + delai).date())}"
        )
        return metrics

    try:
        with attente(f"{BRANCHE}{LIBELLE}", logger) as ligne:
            ligne.efface()
            with download_dump() as rows:
                stats = run_import_doaj_dump(conn, logger, journal_repo=journal_repo, rows=rows)
    except DumpUnavailableError as e:
        # Le téléchargement précède toute écriture : le référentiel reste celui du dernier import.
        metrics = PhaseMetrics()
        logger.warning("Dump DOAJ inaccessible, référentiel inchangé : %s", e)
        signal_source_unavailable(metrics, "DOAJ", logger=logger, phase="publishers_journals")
        metrics.resume = "dump inaccessible, import repris au prochain run"
        return metrics
    metrics = PhaseMetrics(extras={"matched": stats.matched})
    if stats.matched == 0:
        message = f"DOAJ : aucune revue reconnue parmi {stats.total_rows} lignes de l'export, revues inchangées"
        logger.warning(message)
        metrics.signals.append(
            {"level": "warning", "code": "dump_unrecognized", "message": message}
        )
        metrics.resume = "aucune revue reconnue, revues inchangées"
        return metrics
    metrics.resume = accord(stats.matched, "revue mise à jour", "revues mises à jour")
    return metrics
