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
    python3 run_pipeline.py --sources hal,openalex  # Extraction HAL + OA seulement (sans WoS)

Phases:
    extract       Extraction des 3 sources (staging) + refetch truncated
    cross_imports Cross-imports entre sources (DOIs manquants, refs HAL)
    normalize     Normalisation staging → tables sources + merge inter-sources
    addresses     Adresses: extraction, résolution, pays
    uca_flags     Flags UCA sur authorships sources
    identifiers   Moissonnage identifiants HAL (ORCID, IdRef)
    persons       Création/mapping personnes + formes de noms
    authorships   Reconstruction authorships (vérité) + propagation UCA
    countries     Recalcul des pays des publications
    enrich        Enrichissements optionnels (Unpaywall, APC)
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

def phase_extract(mode="full", sources=None, **kw):
    """Phase 1 : Extraction des sources vers staging + refetch truncated.

    Les années sont déterminées par la config DB (pipeline_years_full/weekly).
    Les scripts d'extraction lisent la config directement.
    En mode weekly, WoS est exclu pour économiser le crédit API.
    """
    sources = sources or {"hal", "openalex", "wos"}
    if mode == "weekly":
        log.info("Mode hebdomadaire (WoS exclu)")
        if "openalex" in sources:
            run_python("extraction/openalex/extract_openalex.py", "--mode", "weekly")
        if "hal" in sources:
            run_python("extraction/hal/extract_hal.py", "--mode", "weekly")
    else:
        if "openalex" in sources:
            run_python("extraction/openalex/extract_openalex.py", "--mode", mode)
        if "hal" in sources:
            run_python("extraction/hal/extract_hal.py", "--mode", mode)
        if "wos" in sources:
            run_python("extraction/wos/extract_wos.py", "--mode", mode)
    # Re-fetch des publications OA tronquées à 100 auteurs (lit le staging, pas les tables normalisées)
    if "openalex" in (sources or {"openalex"}):
        run_python("extraction/openalex/refetch_truncated.py")


def phase_cross_imports(mode="full", **kw):
    """Phase 2 : Cross-imports entre sources (lit le staging uniquement)."""
    if mode in ("full", "monthly"):
        run_python("processing/fetch_missing_hal.py")
        run_python("extraction/openalex/cross_import_openalex.py")
        run_python("extraction/hal/cross_import_hal.py")
    else:
        log.info("Cross-imports ignorés en mode hebdomadaire")


def phase_normalize(**kw):
    """Phase 3 : Normalisation staging → tables sources + merge inter-sources."""
    run_python("processing/normalize_openalex.py")
    run_python("processing/normalize_hal.py")
    run_python("processing/normalize_wos.py")
    run_python("processing/enrich_hal_structures.py")
    run_python("processing/merge_hal_openalex_pubs.py")


def phase_addresses(**kw):
    """Phase 4 : Adresses — extraction, résolution structures, pays."""
    run_python("processing/populate_addresses.py", "--source", "openalex")
    run_python("processing/populate_addresses.py", "--source", "wos")
    run_python("processing/resolve_addresses.py")


def phase_uca_flags(**kw):
    """Phase 5 : Flags UCA sur authorships sources (étapes 1-3b)."""
    run_python("processing/populate_uca_flags.py")


def phase_identifiers(mode="full", **kw):
    """Phase 5b : Moissonnage identifiants HAL (ORCID, IdRef)."""
    if mode in ("full", "monthly"):
        run_python("processing/harvest_hal_identifiers.py")
    else:
        log.info("Moissonnage identifiants ignoré en mode hebdomadaire")


def phase_persons(**kw):
    """Phase 6 : Création/mapping personnes + formes de noms."""
    run_python("processing/create_persons_from_source_authorships.py")
    run_python("processing/populate_person_name_forms.py")


def phase_authorships(**kw):
    """Phase 7 : Construction authorships (vérité) + propagation UCA."""
    run_python("processing/build_authorships.py")


def phase_countries(**kw):
    """Phase 8 : Recalcul des pays des publications."""
    run_python("processing/refresh_publication_countries.py")


def phase_enrich(mode="full", **kw):
    """Phase 9 : Enrichissements optionnels."""
    if mode in ("full", "monthly"):
        run_python("processing/enrich_oa_unpaywall.py")
        run_python("processing/enrich_journal_apc.py")
    else:
        log.info("Enrichissements ignorés en mode hebdomadaire")


# Registre des phases, dans l'ordre
PHASES = [
    ("extract", phase_extract),
    ("cross_imports", phase_cross_imports),
    ("normalize", phase_normalize),
    ("addresses", phase_addresses),
    ("uca_flags", phase_uca_flags),
    ("identifiers", phase_identifiers),
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


    # run_sql supprimé — tous les scripts SQL ont été convertis en Python


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
    parser.add_argument("--sources", default="hal,openalex,wos",
                        help="Sources à extraire, séparées par des virgules (défaut: hal,openalex,wos)")
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

    sources = set(s.strip() for s in args.sources.split(",") if s.strip())
    log.info("Sources : %s", ", ".join(sorted(sources)))

    t0_total = time.time()
    for name, fn in phases_to_run:
        log.info("─" * 40)
        log.info("PHASE : %s", name)
        log.info("─" * 40)
        try:
            fn(mode=args.mode, sources=sources)
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
