# STATUS: oneshot (2026-05-22)
"""Seed `journals.doi_prefix` via la LCP (longest common prefix) des DOIs des publis rattachées.

Pour chaque revue avec ≥10 publications avec DOI distinct, on calcule la
plus longue chaîne commune en tête de leurs DOIs, on retire la queue
variable (digits, ponctuation), et on écrit le résultat dans
`journals.doi_prefix` si ce résultat est suffisamment spécifique
(au moins 3 caractères après le `/`).

Cas typiques bien gérés :
- PLOS ONE : `10.1371/journal.pone.0271233`, `.0135715`, ... → LCP `10.1371/journal.pone.0` → trim → `10.1371/journal.pone`
- JHEP : `10.1007/jhep04(2025)105`, `jhep05(2025)038`, ... → LCP `10.1007/jhep0` → trim → `10.1007/jhep`
- Physics Letters B : `10.1016/j.physletb.<id>`, ... → trim → `10.1016/j.physletb`

Cas qui tombent en « ambigu » (écrits dans le CSV de sortie pour analyse manuelle) :
- LCP s'effondre à `10.PUBLISHER/` ou `10.` parce qu'un outlier brise la chaîne commune.
- LCP avec moins de 3 caractères après le `/` (préfixe trop court pour discriminer).

Stratégie stricte (Phase A) : 1 outlier suffit à passer en ambigu. C'est
intentionnel — on observe ce que ça donne, on ajustera (drop 5% outliers
ou autre) si le ratio ambigu/seedé est trop défavorable.

Écrase systématiquement la valeur existante (très peu de données manuelles
en base pour ce champ ; le script fait autorité pour son scope).

Usage :
    python -m interfaces.cli.oneshot.seed_journals_doi_prefix
    python -m interfaces.cli.oneshot.seed_journals_doi_prefix --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("seed_journals_doi_prefix", os.path.dirname(__file__))

# Trim en 2 passes pour éviter qu'un code journal numérique (Taylor & Francis
# `10408398`) ou un segment alphanumérique (Springer Nature `s41597`) soit
# englouti à cause d'un seul tenant de digits/dots :
# 1. Retire UNIQUEMENT les digits en queue (numéro d'article, fragment d'année).
# 2. Retire le séparateur de bord (`.`, `-`, `_`) restant.
# Ne pas inclure `.` dans la pass 1 : sinon `10.1080/10408398.20` (Taylor &
# Francis avec préfixe journal numérique) → strip glouton de `10408398.20` →
# perte du code journal.
_TRIM_DIGITS_RE = re.compile(r"[0-9]+$")
_TRIM_SEPARATORS_RE = re.compile(r"[.\-_]+$")

MIN_CHARS_AFTER_SLASH = 3
MIN_PUBS_PER_JOURNAL = 10


def lcp(strings: list[str]) -> str:
    """Plus long préfixe commun à toutes les chaînes. Empty si vide ou aucun caractère commun.

    Trick lexicographique : la LCP de l'ensemble = LCP(min, max) en tri lexico.
    """
    if not strings:
        return ""
    s1, s2 = min(strings), max(strings)
    for i, c in enumerate(s1):
        if i >= len(s2) or c != s2[i]:
            return s1[:i]
    return s1


def trim_trailing_variable(s: str) -> str:
    """Retire les caractères variables typiques en fin de LCP."""
    s = _TRIM_DIGITS_RE.sub("", s)
    s = _TRIM_SEPARATORS_RE.sub("", s)
    return s


def is_ambiguous(trimmed_lcp: str) -> bool:
    """Une LCP est ambiguë si rien de spécifique au journal après le `/`.

    Cas :
    - Pas de `/` (LCP collapsée à `10.` ou avant) → ambigu.
    - Moins de `MIN_CHARS_AFTER_SLASH` chars après le `/` → ambigu
      (préfixe publisher seul, ou journal-code de 1-2 lettres pas assez
      discriminant ; cf. note utilisatrice).
    """
    slash_idx = trimmed_lcp.find("/")
    if slash_idx == -1:
        return True
    after = trimmed_lcp[slash_idx + 1 :]
    return len(after) < MIN_CHARS_AFTER_SLASH


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed journals.doi_prefix via LCP des DOIs des publis."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ne pas écrire en base, juste afficher les stats et le CSV des ambigus.",
    )
    parser.add_argument(
        "--csv-out",
        default="data/doi_prefix_seed_ambiguous.csv",
        help="Chemin du CSV pour les cas ambigus (relatif à la racine du repo).",
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn, conn.begin():
        rows = conn.execute(
            text(f"""
                SELECT j.id, j.title,
                       array_agg(DISTINCT p.doi ORDER BY p.doi) AS dois
                FROM journals j
                JOIN publications p ON p.journal_id = j.id
                WHERE p.doi IS NOT NULL
                GROUP BY j.id, j.title
                HAVING COUNT(DISTINCT p.doi) >= {MIN_PUBS_PER_JOURNAL}
            """)
        ).all()
        log.info("Journaux à analyser (≥%d publis DOI) : %d", MIN_PUBS_PER_JOURNAL, len(rows))

        update_stmt = text("UPDATE journals SET doi_prefix = :p WHERE id = :id")

        seeded = 0
        ambiguous: list[dict] = []
        for r in rows:
            common = lcp(r.dois)
            trimmed = trim_trailing_variable(common)
            if is_ambiguous(trimmed):
                ambiguous.append(
                    {
                        "journal_id": r.id,
                        "title": r.title,
                        "n_dois": len(r.dois),
                        "lcp_raw": common,
                        "lcp_trimmed": trimmed,
                        "sample_dois": json.dumps(r.dois[:5]),
                    }
                )
                continue
            if not args.dry_run:
                conn.execute(update_stmt, {"p": trimmed, "id": r.id})
            seeded += 1

        if ambiguous:
            os.makedirs(os.path.dirname(args.csv_out), exist_ok=True)
            with open(args.csv_out, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "journal_id",
                        "title",
                        "n_dois",
                        "lcp_raw",
                        "lcp_trimmed",
                        "sample_dois",
                    ],
                )
                writer.writeheader()
                writer.writerows(ambiguous)

        log.info("─── Seed terminé ───")
        log.info("Total analysés       : %d", len(rows))
        log.info("Seedés               : %d", seeded)
        log.info("Ambigus (→ CSV)      : %d", len(ambiguous))
        if ambiguous:
            log.info("CSV ambigus          : %s", args.csv_out)
        if args.dry_run:
            log.info("[DRY RUN] Aucune modification appliquée.")


if __name__ == "__main__":
    main()
