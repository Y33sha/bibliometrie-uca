"""Import du dump CSV DOAJ dans `journals.doaj_payload` (DOAJ = source de vérité).

Bulk, set-based : indexe les `journals` par ISSN (issn / eissn / issnl) en O(1),
remet `is_in_doaj = FALSE` partout, puis pour chaque row du dump matchée par ISSN
écrit `doaj_payload` (dict CSV strippé) + `doaj_imported_at` + `is_in_doaj = TRUE`.

Découplé de la source des rows : la CLI `import_doaj_csv` lit un fichier local,
le pipeline télécharge le dump (cf. `infrastructure.sources.doaj.fetch_doaj_dump`)
— les deux passent un itérable de dicts `{colonne CSV: valeur}`.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Connection

from application.ports.pipeline.enrich import EnrichQueries
from application.ports.repositories.journal_repository import JournalRepository

# Colonnes ISSN du dump CSV DOAJ.
ISSN_KEYS = (
    "Journal ISSN (print version)",
    "Journal EISSN (online version)",
)

COMMIT_EVERY = 1000


@dataclass
class DoajImportStats:
    total_rows: int = 0
    no_issn_rows: int = 0  # rows du dump sans aucun ISSN
    orphan_rows: int = 0  # rows du dump dont l'ISSN est inconnu côté UCA
    matched: int = 0  # journaux UCA mis à is_in_doaj = TRUE


def _clean_row(row: dict[str, str]) -> dict[str, str]:
    """Strip les valeurs et retire les clés vides — réduit le bruit JSONB."""
    out: dict[str, str] = {}
    for k, v in row.items():
        if not v:
            continue
        s = v.strip()
        if s:
            out[k] = s
    return out


def _extract_issns(row: dict[str, str]) -> list[str]:
    """ISSN print + electronic non-vides de la row CSV."""
    issns: list[str] = []
    for key in ISSN_KEYS:
        v = (row.get(key) or "").strip()
        if v:
            issns.append(v)
    return issns


def run_import_doaj_dump(
    conn: Connection,
    queries: EnrichQueries,
    logger: logging.Logger,
    *,
    journal_repo: JournalRepository,
    rows: Iterable[dict[str, str]],
    dry_run: bool = False,
    commit: bool = True,
) -> DoajImportStats:
    """Importe les rows du dump DOAJ. L'orchestrateur gère la transaction
    (commits par batch) sauf si `commit=False` (tests sous transaction
    rollbackée). Retourne les stats."""
    # Index ISSN → journal_id (premier gagnant) pour matcher en O(1).
    issn_to_journal_id: dict[str, int] = {}
    for indexed_journal_id, issn, eissn, issnl in queries.fetch_journal_issn_index(conn):
        for issn_value in (issn, eissn, issnl):
            if issn_value:
                issn_to_journal_id.setdefault(issn_value, indexed_journal_id)
    logger.info("%d ISSN indexés (journals.issn/eissn/issnl)", len(issn_to_journal_id))

    # Le dump fait autorité : reset global avant de re-poser les TRUE.
    if not dry_run:
        n_reset = queries.reset_is_in_doaj(conn)
        logger.info("Reset is_in_doaj = FALSE sur %d journaux", n_reset)

    stats = DoajImportStats()
    now = datetime.now(UTC)
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
        if not dry_run:
            journal_repo.update_journal_doaj(
                journal_id, payload=_clean_row(row), imported_at=now, is_in_doaj=True
            )
            if commit and stats.matched % COMMIT_EVERY == 0:
                conn.commit()

    if commit and not dry_run:
        conn.commit()
    logger.info(
        "Import DOAJ : %d rows, %d sans ISSN, %d orphelines, %d journaux matchés",
        stats.total_rows,
        stats.no_issn_rows,
        stats.orphan_rows,
        stats.matched,
    )
    return stats
