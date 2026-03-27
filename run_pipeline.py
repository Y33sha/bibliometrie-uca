#!/usr/bin/env python3
"""
Orchestrateur du pipeline bibliométrique UCA.

Usage:
    python3 run_pipeline.py                    # Pipeline complet
    python3 run_pipeline.py --from normalize   # Reprendre depuis la normalisation
    python3 run_pipeline.py --only extract     # Exécuter une seule phase
    python3 run_pipeline.py --list             # Lister les phases
    python3 run_pipeline.py --dry-run          # Afficher sans exécuter
    python3 run_pipeline.py --mode weekly      # Import incrémental (6 derniers mois)
    python3 run_pipeline.py --mode monthly     # Repasse complète + cross-imports

Phases:
    extract       Extraction des 3 sources (staging)
    normalize     Normalisation HAL, OpenAlex, WoS
    merge_pubs    Fusion HAL/OpenAlex + cross-imports
    addresses     Adresses: extraction, résolution, pays
    uca_flags     Flags UCA sur authorships sources
    persons       Création/mapping personnes + formes de noms
    authorships   Reconstruction authorships (vérité) + re-propagation UCA
    countries     Recalcul des pays des publications
    enrich        Enrichissements optionnels (Unpaywall, idRef, etc.)
"""

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pipeline")

BASE = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Définition des phases
# ---------------------------------------------------------------------------

def phase_extract(mode="full", **kw):
    """Phase 1 : Extraction des sources vers staging."""
    if mode == "weekly":
        log.info("Mode hebdomadaire : extraction des 6 derniers mois")
    run_python("extraction/openalex/extract_openalex.py")
    run_python("extraction/hal/extract_hal.py")
    # WoS : API instable, scraper si besoin
    log.info("WoS : lancer manuellement scrape_wos.py ou cross_import_wos.py si besoin")


def phase_normalize(**kw):
    """Phase 2 : Normalisation staging → tables sources."""
    run_python("processing/normalize_openalex.py")
    run_python("processing/normalize_hal.py")
    run_python("processing/normalize_wos.py")
    run_python("processing/backfill_wos_addresses.py")


def phase_merge_pubs(mode="full", **kw):
    """Phase 3 : Fusion HAL/OpenAlex + cross-imports."""
    run_python("processing/merge_hal_openalex_pubs.py")
    if mode in ("full", "monthly"):
        log.info("Cross-imports (mode %s)", mode)
        run_python("processing/fetch_missing_hal.py")
        run_python("extraction/openalex/cross_import_openalex.py")
        # Relancer les normalisations pour les nouveaux records
        run_python("processing/normalize_openalex.py")
        run_python("processing/normalize_hal.py")
    else:
        log.info("Cross-imports ignorés en mode hebdomadaire")


def phase_addresses(**kw):
    """Phase 4 : Adresses — extraction, résolution structures, pays."""
    run_python("processing/populate_addresses.py", "--source", "openalex")
    run_python("processing/populate_addresses.py", "--source", "wos")
    run_python("processing/resolve_addresses.py")


def phase_uca_flags(**kw):
    """Phase 5 : Flags UCA sur authorships sources (étapes 1-3b)."""
    run_sql("db/populate_uca_flags.sql")


def phase_persons(**kw):
    """Phase 6 : Création/mapping personnes + formes de noms."""
    run_python("processing/create_persons_from_authorships.py")
    run_python("processing/populate_person_name_forms.py")


def phase_authorships(**kw):
    """Phase 7 : Reconstruction authorships (vérité) + re-propagation UCA."""
    run_python("processing/rebuild_authorships.py")
    # Re-propagation UCA pour les authorships nouvellement créés
    run_sql("db/populate_uca_flags.sql")


def phase_countries(**kw):
    """Phase 8 : Recalcul des pays des publications."""
    run_sql("db/refresh_publication_countries.sql")


def phase_enrich(mode="full", **kw):
    """Phase 9 : Enrichissements optionnels."""
    if mode in ("full", "monthly"):
        run_python("processing/enrich_oa_unpaywall.py")
        run_python("processing/harvest_hal_idrefs.py")
        run_python("processing/harvest_hal_orcids.py")
    else:
        log.info("Enrichissements ignorés en mode hebdomadaire")


# Registre des phases, dans l'ordre
PHASES = [
    ("extract", phase_extract),
    ("normalize", phase_normalize),
    ("merge_pubs", phase_merge_pubs),
    ("addresses", phase_addresses),
    ("uca_flags", phase_uca_flags),
    ("persons", phase_persons),
    ("authorships", phase_authorships),
    ("countries", phase_countries),
    ("enrich", phase_enrich),
]

PHASE_NAMES = [name for name, _ in PHASES]


# ---------------------------------------------------------------------------
# Helpers d'exécution
# ---------------------------------------------------------------------------

def run_python(script: str, *args):
    """Lance un script Python du projet."""
    path = BASE / script
    if not path.exists():
        log.warning("Script introuvable : %s — ignoré", script)
        return
    cmd = [sys.executable, str(path)] + list(args)
    log.info("▶ %s %s", script, " ".join(args) if args else "")
    t0 = time.time()
    result = subprocess.run(cmd, cwd=str(BASE))
    elapsed = time.time() - t0
    if result.returncode != 0:
        log.error("✗ %s a échoué (code %d) en %.1fs", script, result.returncode, elapsed)
        raise RuntimeError(f"{script} a échoué (code {result.returncode})")
    log.info("✓ %s terminé en %.1fs", script, elapsed)


def run_sql(script: str):
    """Lance un script SQL via psql."""
    path = BASE / script
    if not path.exists():
        log.warning("Script SQL introuvable : %s — ignoré", script)
        return
    cmd = ["psql", "-d", "publisher_stats", "-U", "lalecoz", "-f", str(path)]
    log.info("▶ %s", script)
    t0 = time.time()
    result = subprocess.run(cmd, cwd=str(BASE))
    elapsed = time.time() - t0
    if result.returncode != 0:
        log.error("✗ %s a échoué (code %d) en %.1fs", script, result.returncode, elapsed)
        raise RuntimeError(f"{script} a échoué (code {result.returncode})")
    log.info("✓ %s terminé en %.1fs", script, elapsed)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Orchestrateur pipeline bibliométrique UCA")
    parser.add_argument("--from", dest="from_phase", metavar="PHASE",
                        help="Reprendre depuis cette phase")
    parser.add_argument("--only", metavar="PHASE",
                        help="Exécuter uniquement cette phase")
    parser.add_argument("--list", action="store_true",
                        help="Lister les phases disponibles")
    parser.add_argument("--dry-run", action="store_true",
                        help="Afficher les étapes sans exécuter")
    parser.add_argument("--mode", choices=["full", "weekly", "monthly"], default="full",
                        help="Mode d'exécution (défaut: full)")
    args = parser.parse_args()

    if args.list:
        print("Phases disponibles :")
        for i, (name, fn) in enumerate(PHASES, 1):
            doc = fn.__doc__.strip().split("\n")[0] if fn.__doc__ else ""
            print(f"  {i}. {name:15s} — {doc}")
        return

    # Déterminer les phases à exécuter
    if args.only:
        if args.only not in PHASE_NAMES:
            print(f"Phase inconnue : {args.only}. Phases : {', '.join(PHASE_NAMES)}")
            sys.exit(1)
        phases_to_run = [(n, fn) for n, fn in PHASES if n == args.only]
    elif args.from_phase:
        if args.from_phase not in PHASE_NAMES:
            print(f"Phase inconnue : {args.from_phase}. Phases : {', '.join(PHASE_NAMES)}")
            sys.exit(1)
        idx = PHASE_NAMES.index(args.from_phase)
        phases_to_run = PHASES[idx:]
    else:
        phases_to_run = PHASES

    log.info("=" * 60)
    log.info("PIPELINE BIBLIOMÉTRIQUE UCA — mode %s", args.mode)
    log.info("Phases : %s", " → ".join(n for n, _ in phases_to_run))
    log.info("=" * 60)

    if args.dry_run:
        for name, fn in phases_to_run:
            doc = fn.__doc__.strip().split("\n")[0] if fn.__doc__ else ""
            print(f"  [{name}] {doc}")
        print("\n(dry-run : rien n'a été exécuté)")
        return

    t0_total = time.time()
    for name, fn in phases_to_run:
        log.info("─" * 40)
        log.info("PHASE : %s", name)
        log.info("─" * 40)
        try:
            fn(mode=args.mode)
        except RuntimeError as e:
            log.error("Pipeline interrompu à la phase '%s' : %s", name, e)
            log.error("Pour reprendre : python3 run_pipeline.py --from %s", name)
            sys.exit(1)

    elapsed_total = time.time() - t0_total
    log.info("=" * 60)
    log.info("PIPELINE TERMINÉ en %.0fs (%.1f min)", elapsed_total, elapsed_total / 60)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
