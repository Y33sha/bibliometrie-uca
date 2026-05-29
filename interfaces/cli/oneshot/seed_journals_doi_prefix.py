# STATUS: oneshot (2026-05-22)
"""Seed `journals.doi_prefix` via la LCP (longest common prefix) des DOIs des publis rattachées.

Pour chaque revue avec ≥`MIN_PUBS_PER_JOURNAL` publications avec DOI
distinct, on calcule la plus longue chaîne commune en tête de leurs DOIs,
on retire la queue variable (digits, ponctuation), et on écrit le résultat
dans `journals.doi_prefix` si ce résultat est suffisamment spécifique (au
moins `MIN_CHARS_AFTER_SLASH` caractères après le `/`).

Pré-filtrage outliers : on retire des DOIs d'entrée ceux qui correspondent
à des préfixes preprint server / aggregateur connus (`OUTLIER_DOI_PREFIXES`).
Sinon une publi avec un DOI bioRxiv `10.1101/...` posée sur Nature
Communications effondrerait la LCP au niveau `10.`. Ces DOIs outliers sont
précisément ce que la Phase 4a (cohérence DOI ↔ journal) doit flagger comme
incohérence — ils n'ont pas vocation à entrer dans la définition du
`doi_prefix` du journal.

À terme, un filtre publisher (DOIs dont le préfixe résout vers le publisher
du journal via `doi_prefixes`) serait plus robuste — pas implémenté car
`journals.publisher_id` (issu des sources HAL/OA/WoS) et
`doi_prefixes.publisher_id` (issu de Crossref) ne sont pas alignés tant que
le dédoublonnage publishers n'a pas été fait sur cette base.

Cas typiques bien gérés :
- PLOS ONE : `10.1371/journal.pone.0271233`, `.0135715`, ... → LCP `10.1371/journal.pone.0` → trim → `10.1371/journal.pone`
- JHEP : `10.1007/jhep04(2025)105`, `jhep05(2025)038`, ... → LCP `10.1007/jhep0` → trim → `10.1007/jhep`
- Sensors : `10.3390/s2*` (MDPI code 1-char) → trim → `10.3390/s`

Cas qui tombent en « ambigu » (écrits dans le CSV de sortie pour analyse manuelle) :
- LCP s'effondre à `10.PUBLISHER/` (publisher-only) ou `10.` (multi-publisher persistant).
- LCP avec moins de `MIN_CHARS_AFTER_SLASH` caractères après le `/`.
- LCP ISBN-like (`/978...` ou `/979...`) : DOIs Springer/CUP qui encodent
  l'ISBN-13 du livre — le fragment commun aux DOIs d'une série de livres
  n'est PAS spécifique à la série, juste à un imprint éditeur.
- Aucun DOI ne reste après filtrage outliers (journal qui *est* un serveur
  de preprints : bioRxiv, Research Square, Preprints.org, ...).

Stratégie C-stricte : on n'écrit pas de préfixe publisher-only (`10.1103/`,
`10.4000/`, ...). Pour les revues sans subprefix journal-spécifique (APS new
format, OpenEdition opaque IDs), `doi_prefix` reste NULL — la cohérence DOI
↔ journal en Phase 4a se fera via `doi_prefixes.publisher_id`.

Écrase systématiquement la valeur existante pour les journaux non-ambigus
de l'échantillon analysé. Ne touche pas les ambigus (ancienne valeur conservée).

Usage :
    python -m interfaces.cli.oneshot.seed_journals_doi_prefix
    python -m interfaces.cli.oneshot.seed_journals_doi_prefix --dry-run
    python -m interfaces.cli.oneshot.seed_journals_doi_prefix --min-pubs 3
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
# Préfixe ISBN-13 (978/979) : les DOIs de chapitres Springer/CUP encodent
# l'ISBN dans le chemin (`10.1007/978-3-030-XXXXX-X_n`). La LCP attrape
# alors un fragment d'ISBN qui n'est pas spécifique au journal/série.
_ISBN_PREFIX_RE = re.compile(r"^97[89]")

MIN_CHARS_AFTER_SLASH = 1
MIN_PUBS_PER_JOURNAL = 10

# Préfixes ou sous-préfixes des serveurs de preprints et aggregateurs publics.
# Un DOI commençant par l'un de ces motifs est retiré avant calcul de la LCP.
# Pour `10.5194`, on filtre uniquement le sous-préfixe `egusphere-` (preprints
# EGU) sans toucher aux journaux Copernicus légitimes (`acp-`, `bg-`, etc.).
OUTLIER_DOI_PREFIXES: tuple[str, ...] = (
    "10.1101/",  # bioRxiv / medRxiv (Cold Spring Harbor)
    "10.48550/arxiv",  # arXiv
    "10.2139/ssrn",  # SSRN
    "10.5281/zenodo",  # Zenodo
    "10.20944/preprints",  # MDPI Preprints
    "10.5194/egusphere-",  # EGU sphere preprints (Copernicus)
    "10.21203/rs.",  # Research Square
    "10.22541/au.",  # Authorea preprints
    "10.31223/",  # EarthArXiv
)


def is_outlier(doi: str) -> bool:
    """Préfixe preprint / aggregateur connu : à exclure du calcul LCP."""
    return any(doi.startswith(p) for p in OUTLIER_DOI_PREFIXES)


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
    - Préfixe ISBN-like (`/978...` ou `/979...`) : DOIs Springer/CUP/etc.
      qui embarquent l'ISBN-13 du livre dans le chemin. La LCP attrape un
      fragment d'ISBN qui n'est PAS spécifique au journal/série. → ambigu.
    """
    slash_idx = trimmed_lcp.find("/")
    if slash_idx == -1:
        return True
    after = trimmed_lcp[slash_idx + 1 :]
    if len(after) < MIN_CHARS_AFTER_SLASH:
        return True
    if _ISBN_PREFIX_RE.match(after):
        return True
    return False


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
    parser.add_argument(
        "--min-pubs",
        type=int,
        default=MIN_PUBS_PER_JOURNAL,
        help=f"Nombre min de DOIs distincts par journal pour être analysé (défaut : {MIN_PUBS_PER_JOURNAL}).",
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn, conn.begin():
        rows = conn.execute(
            text("""
                SELECT j.id, j.title,
                       array_agg(DISTINCT p.doi ORDER BY p.doi) AS dois
                FROM journals j
                JOIN publications p ON p.journal_id = j.id
                WHERE p.doi IS NOT NULL
                GROUP BY j.id, j.title
                HAVING COUNT(DISTINCT p.doi) >= :min_pubs
            """),
            {"min_pubs": args.min_pubs},
        ).all()
        log.info("Journaux à analyser (≥%d publis DOI) : %d", args.min_pubs, len(rows))

        update_stmt = text("UPDATE journals SET doi_prefix = :p WHERE id = :id")

        seeded = 0
        ambiguous: list[dict] = []
        empty_after_filter = 0
        for r in rows:
            filtered_dois = [doi for doi in r.dois if not is_outlier(doi)]

            if not filtered_dois:
                # Tous les DOIs du journal sont des outliers preprint/aggregator
                # — cas attendu pour bioRxiv, SSRN eux-mêmes, etc. On les
                # remonte en ambigu pour traçabilité.
                empty_after_filter += 1
                ambiguous.append(
                    {
                        "journal_id": r.id,
                        "title": r.title,
                        "n_dois": len(r.dois),
                        "n_filtered": 0,
                        "lcp_raw": "",
                        "lcp_trimmed": "",
                        "sample_dois": json.dumps(r.dois[:5]),
                    }
                )
                continue

            common = lcp(filtered_dois)
            trimmed = trim_trailing_variable(common)
            if is_ambiguous(trimmed):
                ambiguous.append(
                    {
                        "journal_id": r.id,
                        "title": r.title,
                        "n_dois": len(r.dois),
                        "n_filtered": len(filtered_dois),
                        "lcp_raw": common,
                        "lcp_trimmed": trimmed,
                        "sample_dois": json.dumps(filtered_dois[:5]),
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
                        "n_filtered",
                        "lcp_raw",
                        "lcp_trimmed",
                        "sample_dois",
                    ],
                )
                writer.writeheader()
                writer.writerows(ambiguous)

        log.info("─── Seed terminé ───")
        log.info("Total analysés                : %d", len(rows))
        log.info("Seedés                        : %d", seeded)
        log.info("Ambigus (→ CSV)               : %d", len(ambiguous))
        log.info("  dont 100%% outliers          : %d", empty_after_filter)
        if ambiguous:
            log.info("CSV ambigus                   : %s", args.csv_out)
        if args.dry_run:
            log.info("[DRY RUN] Aucune modification appliquée.")


if __name__ == "__main__":
    main()
