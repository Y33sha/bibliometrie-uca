#!/usr/bin/env python3
"""
Orchestrateur du pipeline bibliométrique UCA.

Usage:
    python run_pipeline.py                    # Pipeline complet
    python run_pipeline.py --from normalize   # Reprendre depuis la normalisation
    python run_pipeline.py --only extract     # Exécuter une seule phase
    python run_pipeline.py --list             # Lister les phases
    python run_pipeline.py --dry-run          # Afficher sans exécuter
    python run_pipeline.py --mode daily       # Import quotidien (HAL + OpenAlex, depuis dernier run)
    python run_pipeline.py --mode weekly      # Import incrémental (6 derniers mois)
    python run_pipeline.py --mode monthly     # Repasse complète + cross-imports
    python run_pipeline.py --sources hal,openalex  # Extraction HAL + OA seulement
    python run_pipeline.py --only extract --sources scanr --year 2023  # ScanR 2023 seul
    python run_pipeline.py --only cross_imports --sources scanr --full-cross-import  # Cross-import ScanR complet

Phases (dans l'ordre d'execution):
    extract        Extraction des sources vers staging (HAL, OpenAlex, WoS, ScanR, theses.fr)
    cross_imports  Cross-imports entre sources (DOIs manquants, fetch HAL par hal-id/NNT)
    normalize      Normalisation staging -> tables sources (source_documents, source_authors,
                   source_authorships). Rattachement aux publications existantes par DOI/NNT/
                   HAL-ID, mais PAS de creation de publications. Inclut enrichissement
                   structures HAL et moissonnage identifiants HAL (ORCID, IdRef).
                   Vide le raw_data du staging apres traitement + VACUUM.
    addresses      Extraction des adresses depuis raw_affiliations, resolution structures, pays
    affiliations   Resolution affiliations sur source_authorships (in_perimeter, structure_ids)
    publications   Creation des publications pour les source_documents in-perimeter non
                   rattaches + merges inter-sources (HAL-ID, NNT)
    persons        Creation/mapping personnes + formes de noms
    authorships    Reconstruction authorships canoniques (table de verite) + propagation UCA
    countries      Detection pays des adresses + recalcul pays des publications
    enrich         Enrichissements optionnels (statut OA via Unpaywall, APC revues)
"""

import argparse
import logging
import subprocess
import sys

from utils.sources import ALL_SOURCES_SET, BIBLIO_SOURCES_SET
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

def phase_extract(mode="full", sources=None, year=None, **kw):
    """Phase 1 : Extraction des sources vers staging + refetch truncated.

    Les années sont déterminées par la config DB (pipeline_years_full/weekly).
    Les scripts d'extraction lisent la config directement.
    En mode daily, seules HAL et OpenAlex sont interrogées (filtre par date).
    En mode weekly, WoS est exclu pour économiser le crédit API.
    """
    sources = sources or set(ALL_SOURCES_SET)
    year_args = ["--year", str(year)] if year else []
    if mode == "daily":
        from pipeline.metrics import get_last_run_date
        since = str(get_last_run_date())
        log.info("Mode quotidien : HAL depuis %s", since)
        if "hal" in sources:
            run_python("extraction/hal/extract_hal.py", "--since", since)
        # OpenAlex : le filtre from_updated_date requiert un plan payant
        # (429 "Plan upgrade required"). Les changefiles couvrent tout OA
        # (plusieurs Go/jour), pas filtrable par institution.
        # OpenAlex est rattrapé par le mode weekly (année en cours + hash).
    elif mode == "weekly":
        log.info("Mode hebdomadaire (WoS exclu)")
        if "openalex" in sources:
            run_python("extraction/openalex/extract_openalex.py", "--mode", "weekly", *year_args)
        if "hal" in sources:
            run_python("extraction/hal/extract_hal.py", "--mode", "weekly", *year_args)
        if "scanr" in sources:
            run_python("extraction/scanr/extract_scanr.py", *year_args)
        if "theses" in sources:
            run_python("extraction/theses/extract_theses.py")
    else:
        if "openalex" in sources:
            run_python("extraction/openalex/extract_openalex.py", "--mode", mode, *year_args)
        if "hal" in sources:
            run_python("extraction/hal/extract_hal.py", "--mode", mode, *year_args)
        if "wos" in sources:
            run_python("extraction/wos/extract_wos.py", "--mode", mode, *year_args)
        if "scanr" in sources:
            run_python("extraction/scanr/extract_scanr.py", *year_args)
        if "theses" in sources:
            run_python("extraction/theses/extract_theses.py")
    # Re-fetch des publications OA tronquées à 100 auteurs (sauf mode daily)
    if mode != "daily" and "openalex" in (sources or {"openalex"}):
        run_python("extraction/openalex/refetch_truncated.py")


def phase_cross_imports(mode="full", sources=None, full_cross_import=False, **kw):
    """Phase 2 : Cross-imports entre sources (lit le staging uniquement).

    - daily/weekly : cross-import sur les documents non normalisés (processed=FALSE)
    - monthly : cross-import complet (--all)
    - full : selon le flag --full-cross-import
    """
    if mode in ("daily", "weekly"):
        sources = sources or set(BIBLIO_SOURCES_SET)
        full_flag = []
    elif mode in ("full", "monthly"):
        sources = sources or set(BIBLIO_SOURCES_SET)
        full_flag = ["--all"] if (full_cross_import or mode == "monthly") else []
    else:
        return

    if "hal" in sources:
        run_python("extraction/hal/fetch_missing_hal.py", *full_flag)
        run_python("extraction/hal/cross_import_hal.py", *full_flag)
    if "openalex" in sources:
        run_python("extraction/openalex/cross_import_openalex.py", *full_flag)
    if "wos" in sources:
        run_python("extraction/wos/cross_import_wos.py", *full_flag)
    if "scanr" in sources:
        run_python("extraction/scanr/cross_import_scanr.py", *full_flag)


def phase_normalize(**kw):
    """Normalisation staging -> tables sources.

    Rattache aux publications existantes (DOI/NNT/HAL-ID) sans en creer.
    Stocke les metadonnees (abstract, keywords, topics, biblio, etc.) sur
    source_documents. Vide le raw_data du staging apres traitement.
    Pour HAL : enrichit les structures et moissonne les identifiants (ORCID, IdRef).
    """
    sources = kw.get("sources", set(ALL_SOURCES_SET))
    if "openalex" in sources:
        run_python("processing/normalize_openalex.py")
    if "hal" in sources:
        run_python("processing/normalize_hal.py")
    if "wos" in sources:
        run_python("processing/normalize_wos.py")
    if "scanr" in sources:
        run_python("processing/normalize_scanr.py")
    if "theses" in sources:
        run_python("processing/normalize_theses.py")
    if "hal" in sources:
        run_python("processing/enrich_hal_structures.py")
        if kw.get("mode", "full") in ("full", "monthly"):
            run_python("processing/harvest_hal_identifiers.py")
    # Liberer l'espace TOAST du staging (raw_data vide apres normalisation)
    log.info("VACUUM FULL staging...")
    _vacuum_staging()


def _vacuum_staging():
    """VACUUM FULL sur staging pour liberer l'espace TOAST."""
    from db.connection import get_connection
    conn = get_connection()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("VACUUM FULL staging")
    conn.close()


def phase_addresses(**kw):
    """Extraction des adresses depuis raw_affiliations, resolution structures.

    Ne traite que les source_authorships non encore extraites (addresses_extracted=FALSE).
    Sources concernees : OpenAlex, WoS, ScanR, theses (pas HAL, qui utilise les structures).
    """
    sources = kw.get("sources", {"openalex", "wos", "scanr", "theses"})
    address_sources = ["openalex", "wos", "scanr", "theses"]
    for src in address_sources:
        if src in sources:
            run_python("processing/populate_addresses.py", "--source", src)
    run_python("processing/resolve_addresses.py")


def phase_affiliations(**kw):
    """Resolution des affiliations UCA sur les source_authorships.

    Determine in_perimeter et structure_ids a partir des structures HAL
    (pour HAL) et des adresses resolues (pour les autres sources).
    """
    sources = kw.get("sources", set(ALL_SOURCES_SET))
    source_args = ",".join(sorted(sources))
    run_python("processing/populate_affiliations.py", "--sources", source_args)


def phase_publications(**kw):
    """Creation des publications canoniques.

    Ne cree des publications que pour les source_documents ayant au moins
    une source_authorship in_perimeter (evite de creer des publications
    hors perimetre). Applique ensuite les merges inter-sources (HAL-ID, NNT).
    """
    run_python("processing/create_publications.py")
    run_python("processing/merge_pubs_by_hal_id.py")
    run_python("processing/merge_pubs_by_nnt.py")




def phase_persons(**kw):
    """Creation et rattachement des personnes.

    Cree des personnes a partir des source_authorships in_perimeter non rattachees.
    Exclut les publications de type memoir (v_active_publications).
    Rattache aussi les authorships theses hors-perimetre par IdRef.
    """
    run_python("processing/create_persons_from_source_authorships.py")
    run_python("processing/populate_person_name_forms.py")


def phase_authorships(**kw):
    """Construction de la table de verite authorships.

    Consolide les source_authorships en authorships canoniques
    (une entree par couple publication x personne), avec in_perimeter
    et structure_ids propages.
    """
    sources = kw.get("sources")
    if sources and sources != ALL_SOURCES_SET:
        run_python("processing/build_authorships.py", "--sources", ",".join(sorted(sources)))
    else:
        run_python("processing/build_authorships.py")


def phase_countries(**kw):
    """Detection des pays des adresses et recalcul sur les publications."""
    run_python("scripts/detect_address_countries.py", "--direct", "--apply")
    run_python("scripts/suggest_address_countries.py")
    run_python("processing/refresh_publication_countries.py")


def phase_enrich(mode="full", **kw):
    """Enrichissements optionnels (mode full/monthly uniquement).

    - Statut OA via Unpaywall
    - APC revues (import fichiers budget)
    """
    if mode in ("full", "monthly"):
        run_python("processing/enrich_oa_status.py")
        run_python("processing/enrich_journal_apc.py")
    else:
        log.info("Enrichissements ignorés en mode hebdomadaire")


# Registre des phases, dans l'ordre
PHASES = [
    ("extract", phase_extract),
    ("cross_imports", phase_cross_imports),
    ("normalize", phase_normalize),
    ("addresses", phase_addresses),
    ("affiliations", phase_affiliations),
    ("publications", phase_publications),
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
    parser.add_argument("--mode", choices=["full", "weekly", "monthly", "daily"], default="full",
                        help="Mode d'exécution (défaut: full)")
    parser.add_argument("--sources", default=",".join(ALL_SOURCES_SET),
                        help="Sources, séparées par des virgules (défaut: hal,openalex,wos,scanr,theses)")
    parser.add_argument("--year", type=int,
                        help="Surcharger l'année d'extraction (une seule année)")
    parser.add_argument("--full-cross-import", action="store_true",
                        help="Cross-imports sur tout le staging (pas seulement les non-normalisés)")
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

    # Métriques pipeline
    from db.connection import get_connection
    from pipeline.metrics import snapshot, compute_deltas, generate_report
    metrics_conn = get_connection()
    phase_results = []  # [(name, duration, deltas)]

    t0_total = time.time()
    for name, fn in phases_to_run:
        log.info("─" * 40)
        log.info("PHASE : %s", name)
        log.info("─" * 40)

        before = snapshot(metrics_conn)
        t0_phase = time.time()
        try:
            fn(mode=args.mode, sources=sources, year=args.year,
               full_cross_import=args.full_cross_import)
        except RuntimeError as e:
            log.error("Pipeline interrompu à la phase '%s' : %s", name, e)
            log.error("Pour reprendre : python run_pipeline.py --from %s", name)
            # Générer le rapport partiel avant de quitter
            after = snapshot(metrics_conn)
            phase_results.append((name + " (ERREUR)", time.time() - t0_phase,
                                  compute_deltas(before, after)))
            report_path = generate_report(args.mode, sources, phase_results,
                                          time.time() - t0_total)
            log.info("Rapport partiel : %s", report_path)
            metrics_conn.close()
            sys.exit(1)

        duration = time.time() - t0_phase
        after = snapshot(metrics_conn)
        deltas = compute_deltas(before, after)
        phase_results.append((name, duration, deltas))

        if deltas:
            for key, vals in sorted(deltas.items()):
                log.info("  %s : %d → %d (%+d)", key, vals["before"], vals["after"], vals["delta"])

    elapsed_total = time.time() - t0_total

    # Générer le rapport
    report_path = generate_report(args.mode, sources, phase_results, elapsed_total)
    log.info("Rapport : %s", report_path)

    metrics_conn.close()
    log.info("=" * 60)
    log.info("PIPELINE TERMINÉ en %.0fs (%.1f min)", elapsed_total, elapsed_total / 60)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
