# STATUS: recurring (imports)
"""Import du dump CSV public DOAJ dans `journals.doaj_payload`.

Le CSV est téléchargé manuellement depuis https://doaj.org/csv et
déposé dans `data/`. Le script :

1. Reset `is_in_doaj = FALSE` sur tous les journals (CSV = source de vérité,
   cf. décision Phase 3 du chantier publishers-journals).
2. Préfetch les `journals` (id, issn, eissn, issnl) dans un dict
   `{issn_normalisé → journal_id}` pour matcher en O(1).
3. Pour chaque row du CSV, extrait les ISSNs (print + electronic),
   trouve le `journal_id`, et UPDATE `doaj_payload`/`doaj_imported_at`/
   `is_in_doaj = TRUE`. Le payload est stocké tel quel (dict CSV strippé).
4. Stats en fin de run : journaux matchés, rows DOAJ orphelines (ISSN
   absent côté UCA), journaux locaux passés à `is_in_doaj=FALSE`.

Usage :
    python -m interfaces.cli.imports.import_doaj_csv data/doaj_journalcsv_20260507_2321_utf8.csv
    python -m interfaces.cli.imports.import_doaj_csv data/doaj_journalcsv_20260507_2321_utf8.csv --dry-run
"""

import argparse
import csv
import os
from datetime import UTC, datetime

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger(
    "import_doaj_csv", os.path.join(os.path.dirname(__file__), "../../processing/logs")
)


ISSN_KEYS = (
    "Journal ISSN (print version)",
    "Journal EISSN (online version)",
)


def _clean_row(row: dict[str, str]) -> dict[str, str]:
    """Strip toutes les valeurs et retire les clés vides — réduit le bruit JSONB."""
    out: dict[str, str] = {}
    for k, v in row.items():
        if not v:
            continue
        s = v.strip()
        if s:
            out[k] = s
    return out


def _extract_issns(row: dict[str, str]) -> list[str]:
    """Extrait ISSN print + electronic non-vides de la row CSV."""
    issns: list[str] = []
    for key in ISSN_KEYS:
        v = (row.get(key) or "").strip()
        if v:
            issns.append(v)
    return issns


def main() -> None:
    parser = argparse.ArgumentParser(description="Import dump CSV DOAJ → journals.doaj_payload")
    parser.add_argument("csv_file", help="Chemin vers le CSV DOAJ (data/doaj_journalcsv_*.csv)")
    parser.add_argument("--dry-run", action="store_true", help="Compter sans modifier la base")
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn, conn.begin():
        # Préfetch : indexer journals.id par tout ISSN connu (issn, eissn, issnl)
        # pour matcher en O(1) au lieu de N UPDATEs SQL ciblés par row.
        issn_to_journal_id: dict[str, int] = {}
        rows = conn.execute(
            text("""
                SELECT id, issn, eissn, issnl
                FROM journals
                WHERE issn IS NOT NULL OR eissn IS NOT NULL OR issnl IS NOT NULL
            """)
        )
        for r in rows:
            for issn in (r.issn, r.eissn, r.issnl):
                if issn:
                    issn_to_journal_id.setdefault(issn, r.id)
        log.info("%d ISSN indexés (sur journals.issn/eissn/issnl)", len(issn_to_journal_id))

        # Étape 1 : reset is_in_doaj (CSV = source de vérité).
        if not args.dry_run:
            result = conn.execute(text("UPDATE journals SET is_in_doaj = FALSE"))
            log.info("Reset is_in_doaj = FALSE sur %d journaux", result.rowcount)

        # Étape 2 : lecture CSV + bulk UPDATE par batch.
        update_stmt = text("""
            UPDATE journals
            SET doaj_payload = :payload,
                doaj_imported_at = :imported_at,
                is_in_doaj = TRUE
            WHERE id = :journal_id
        """).bindparams(bindparam("payload", type_=JSONB))

        now = datetime.now(UTC)
        total_rows = 0
        matched = 0
        orphan_rows = 0  # rows DOAJ sans ISSN match côté UCA
        no_issn_rows = 0  # rows DOAJ sans aucun ISSN renseigné
        seen_journal_ids: set[int] = set()

        with open(args.csv_file, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total_rows += 1
                issns = _extract_issns(row)
                if not issns:
                    no_issn_rows += 1
                    continue

                journal_id = next(
                    (issn_to_journal_id[i] for i in issns if i in issn_to_journal_id),
                    None,
                )
                if journal_id is None:
                    orphan_rows += 1
                    continue
                if journal_id in seen_journal_ids:
                    # 2 rows DOAJ pour le même journal (improbable mais possible
                    # si ISSN print + ISSN electronic pointent vers 2 entrées DOAJ).
                    # La 1re l'emporte, on garde le compteur cohérent.
                    continue
                seen_journal_ids.add(journal_id)
                matched += 1

                if not args.dry_run:
                    conn.execute(
                        update_stmt,
                        {
                            "payload": _clean_row(row),
                            "imported_at": now,
                            "journal_id": journal_id,
                        },
                    )

        log.info("─── Import DOAJ terminé ───")
        log.info("Rows CSV totales       : %d", total_rows)
        log.info("Rows sans ISSN         : %d", no_issn_rows)
        log.info("Rows orphelines (ISSN inconnu en local) : %d", orphan_rows)
        log.info("Journaux UCA matchés (is_in_doaj=TRUE)  : %d", matched)
        if args.dry_run:
            log.info("[DRY RUN] Aucune modification appliquée.")


if __name__ == "__main__":
    main()
