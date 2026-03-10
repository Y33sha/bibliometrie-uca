"""
Scraper WoS via Playwright — plan B quand l'API Expanded est HS.

Ouvre un vrai navigateur Chromium, se connecte au portail Clarivate,
exécute la recherche Advanced Search, et exporte les résultats en
fichier texte brut (Plain Text) via Fast 5000.

Usage:
    python scrape_wos.py                    # toutes les années (settings.py)
    python scrape_wos.py --year 2024        # une seule année
    python scrape_wos.py --skip-login       # si déjà connecté (session reprise)
    python scrape_wos.py --download-only    # ne parse/insère pas, télécharge seulement
    python scrape_wos.py --parse-only       # ne scrape pas, parse les fichiers déjà téléchargés

Le navigateur est visible (headed) pour permettre l'intervention manuelle
en cas de captcha ou de changement d'interface.

Les fichiers téléchargés sont stockés dans extraction/wos/downloads/.
Les records parsés sont insérés dans staging_wos (même table que l'API).
"""

import argparse
import glob
import json
import logging
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright, Page, Browser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.settings import WOS

# Optionnel : insertion en base
try:
    import psycopg2
    from psycopg2.extras import Json, execute_values
    from db.connection import get_connection
    HAS_DB = True
except ImportError:
    HAS_DB = False

# ----- Logging -----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "scrape_wos.log")
        ),
    ],
)
logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")


# =====================================================================
#  1. PARSING DES FICHIERS WoS (TSV tab-delimited ou plaintext)
# =====================================================================

def _detect_format(filepath: str) -> str:
    """Détecte le format d'un fichier WoS : 'tsv' ou 'plaintext'."""
    with open(filepath, "r", encoding="utf-8-sig") as f:
        first_line = f.readline()
        # TSV : la première ligne contient les en-têtes séparés par des tabs
        if "\t" in first_line and ("UT" in first_line or "PT" in first_line):
            return "tsv"
        return "plaintext"


def parse_wos_file(filepath: str) -> list[dict]:
    """Parse un fichier WoS (détecte automatiquement TSV ou plaintext)."""
    fmt = _detect_format(filepath)
    if fmt == "tsv":
        return parse_wos_tsv(filepath)
    return parse_wos_plaintext(filepath)


def parse_wos_tsv(filepath: str) -> list[dict]:
    """Parse un fichier tab-delimited WoS et retourne une liste de records.

    La première ligne contient les en-têtes (tags WoS 2 lettres).
    Chaque ligne suivante est un record.
    """
    import csv

    records = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            # Normaliser les clés (enlever BOM éventuel du premier champ)
            clean = {}
            for k, v in row.items():
                key = k.strip().lstrip("\ufeff")
                clean[key] = (v or "").strip()

            ut = clean.get("UT", "")
            doi = clean.get("DI") or None
            if doi:
                doi = doi.strip()

            # Construire le raw_data (tout le row, valeurs non vides)
            raw = {k: v for k, v in clean.items() if v}

            # Champs multi-valeurs : AU (auteurs séparés par ;)
            authors = [a.strip() for a in clean.get("AU", "").split(";") if a.strip()]

            records.append({
                "ut": ut,
                "doi": doi,
                "raw": raw,
                "_title": clean.get("TI") or "(sans titre)",
                "_year": clean.get("PY"),
                "_journal": clean.get("SO"),
                "_authors": authors,
            })

    return records


def parse_wos_plaintext(filepath: str) -> list[dict]:
    """Parse un fichier plaintext WoS et retourne une liste de records.

    Le format utilise des tags de 2 lettres en début de ligne.
    Les lignes de continuation commencent par 3 espaces.
    Chaque record se termine par 'ER'.
    """
    records = []
    current: dict[str, list[str]] = {}
    current_tag = None

    with open(filepath, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.rstrip("\n\r")

            if not line:
                continue
            if line.startswith("FN ") or line.startswith("VR "):
                continue
            if line.strip() == "EF":
                break

            if line.startswith("ER"):
                if current:
                    records.append(_finalize_record(current))
                    current = {}
                    current_tag = None
                continue

            if line.startswith("   ") and current_tag:
                current.setdefault(current_tag, []).append(line[3:])
                continue

            if len(line) >= 3 and line[2] == " " and line[:2].isalpha():
                current_tag = line[:2]
                current.setdefault(current_tag, []).append(line[3:])
                continue

            if current_tag:
                current[current_tag][-1] += " " + line.strip()

    if current:
        records.append(_finalize_record(current))

    return records


def _finalize_record(fields: dict[str, list[str]]) -> dict:
    """Convertit les champs bruts plaintext en dict structuré pour staging_wos."""
    def first(tag: str) -> str | None:
        vals = fields.get(tag)
        return vals[0].strip() if vals else None

    def joined(tag: str) -> str | None:
        vals = fields.get(tag)
        return " ".join(v.strip() for v in vals).strip() if vals else None

    def all_vals(tag: str) -> list[str]:
        return [v.strip() for v in fields.get(tag, [])]

    ut = first("UT") or ""
    doi = first("DI")

    raw = {}
    for tag, vals in fields.items():
        if len(vals) == 1:
            raw[tag] = vals[0].strip()
        else:
            raw[tag] = [v.strip() for v in vals]

    return {
        "ut": ut,
        "doi": doi.strip() if doi else None,
        "raw": raw,
        "_title": joined("TI") or "(sans titre)",
        "_year": first("PY"),
        "_journal": first("SO"),
        "_authors": all_vals("AU"),
    }


# =====================================================================
#  2. SCRAPING WoS
# =====================================================================

def build_query(year: int) -> str:
    """Construit la requête WoS Advanced Search pour une année."""
    orgs = " OR ".join(WOS["affiliations"])
    return f"OG=({orgs}) AND PY=({year})"


def login(page: Page):
    """Se connecte au portail Clarivate."""
    email = WOS.get("web_email", "")
    password = WOS.get("web_password", "")
    if not email or not password:
        logger.error("Credentials web manquants dans config/settings.py (web_email, web_password)")
        sys.exit(1)

    logger.info("Navigation vers la page de connexion Clarivate...")
    page.goto("https://access.clarivate.com/login?app=wos&locale=en-US", timeout=30000)
    page.wait_for_load_state("networkidle", timeout=30000)

    # Remplir email
    logger.info("Saisie de l'email...")
    email_input = page.locator('input[name="email"], input[type="email"], #email')
    email_input.wait_for(timeout=15000)
    email_input.fill(email)

    # Cliquer sur Next/Continue si nécessaire
    next_btn = page.locator('button:has-text("Next"), button:has-text("Continue"), button:has-text("Suivant"), button[type="submit"]').first
    if next_btn.is_visible(timeout=3000):
        next_btn.click()
        page.wait_for_load_state("networkidle", timeout=15000)

    # Remplir mot de passe
    logger.info("Saisie du mot de passe...")
    pwd_input = page.locator('input[name="password"], input[type="password"], #password')
    pwd_input.wait_for(timeout=15000)
    pwd_input.fill(password)

    # Soumettre
    submit_btn = page.locator('button:has-text("Sign in"), button:has-text("Log in"), button:has-text("Connexion"), button[type="submit"]').first
    submit_btn.click()

    # Attendre la redirection vers WoS
    logger.info("Attente de la connexion...")
    try:
        page.wait_for_url("**/wos/**", timeout=30000)
        logger.info("Connexion réussie !")
    except Exception:
        # Peut-être un captcha ou une validation supplémentaire
        logger.warning(
            "La connexion n'a pas abouti automatiquement. "
            "Veuillez compléter manuellement (captcha, 2FA...) "
            "puis appuyer sur Entrée dans le terminal."
        )
        input(">>> Appuyez sur Entrée une fois connecté à WoS...")


def run_search(page: Page, query: str):
    """Exécute une recherche Advanced Search et navigue vers la page de résultats."""
    logger.info(f"Navigation vers Advanced Search...")
    page.goto("https://www.webofscience.com/wos/woscc/advanced-search", timeout=30000)
    page.wait_for_load_state("networkidle", timeout=30000)

    # Accepter les cookies si demandé
    try:
        cookie_btn = page.locator('#onetrust-accept-btn-handler, button:has-text("Accept")')
        if cookie_btn.is_visible(timeout=3000):
            cookie_btn.click()
            time.sleep(1)
    except Exception:
        pass

    # Trouver le champ de recherche avancée (textarea)
    logger.info(f"Saisie de la requête : {query}")
    search_input = page.locator('textarea#advancedSearchInputArea, textarea[name="search"]').first
    try:
        search_input.wait_for(timeout=10000)
    except Exception:
        # L'interface a peut-être changé, essayons d'autres sélecteurs
        search_input = page.locator('textarea').first
        search_input.wait_for(timeout=10000)

    search_input.fill("")
    search_input.fill(query)
    time.sleep(1)

    # Cliquer sur Search
    search_btn = page.locator('button:has-text("Search")').first
    search_btn.click()

    # Attendre la page de résultats
    logger.info("Attente de la page de résultats...")
    page.wait_for_load_state("networkidle", timeout=60000)
    time.sleep(3)

    # Vérifier qu'on est bien sur une page de résultats (URL contient /summary/)
    if "/summary/" not in page.url and "/woscc/" not in page.url:
        logger.warning(f"URL inattendue après recherche : {page.url}")
        input(">>> Naviguez vers la page de résultats, puis Entrée...")
        page.wait_for_load_state("networkidle", timeout=30000)

    logger.info(f"Page de résultats chargée : {page.url}")


def do_export(page: Page, download_dir: str, batch_num: int) -> str | None:
    """Lance un export Fast 5000 (plaintext). Retourne le chemin du fichier téléchargé."""
    logger.info("Clic sur Export...")

    # Cliquer sur le bouton Export
    try:
        export_btn = page.locator(
            'button:has-text("Export"), '
            'button[data-ta="export-button"], '
            '[aria-label="Export"]'
        ).first
        export_btn.wait_for(timeout=10000)
        export_btn.click()
        time.sleep(2)
    except Exception:
        logger.warning("Bouton Export non trouvé automatiquement.")
        input(">>> Cliquez sur Export manuellement, puis Entrée...")

    # Cliquer sur "Plain text file" (ou similaire)
    try:
        plain_opt = page.locator(
            'button:has-text("Plain text"), '
            'a:has-text("Plain text"), '
            'label:has-text("Plain text"), '
            'mat-option:has-text("Plain text"), '
            'li:has-text("Plain text")'
        ).first
        plain_opt.wait_for(timeout=5000)
        plain_opt.click()
        time.sleep(2)
    except Exception:
        logger.warning("Option 'Plain text' non trouvée.")
        input(">>> Sélectionnez 'Plain text file', puis Entrée...")

    # Sur la modale d'export, cliquer sur "Fast 5000"
    try:
        fast_opt = page.locator(
            'label:has-text("Fast 5,000"), '
            'label:has-text("Fast 5000"), '
            'span:has-text("Fast 5,000"), '
            'span:has-text("Fast 5000"), '
            'input[value="fast5k"]'
        ).first
        fast_opt.wait_for(timeout=5000)
        fast_opt.click()
        time.sleep(1)
    except Exception:
        # Peut-être déjà sélectionné par défaut, ou nommé autrement
        logger.info("Option Fast 5000 non trouvée (peut-être déjà sélectionnée).")

    # Lancer le téléchargement
    logger.info("Lancement du téléchargement...")
    try:
        with page.expect_download(timeout=120000) as download_info:
            dl_btn = page.locator(
                'button:has-text("Export"), '
                'button:has-text("Download"), '
                'button[data-ta="export-submit"], '
                'button.cdx-but-md'
            ).first
            dl_btn.click()

        download = download_info.value
        filename = f"wos_batch_{batch_num:03d}.txt"
        filepath = os.path.join(download_dir, filename)
        download.save_as(filepath)
        logger.info(f"Fichier téléchargé : {filepath}")

        # Fermer la modale si encore ouverte
        time.sleep(2)
        try:
            close_btn = page.locator(
                'button:has-text("Close"), '
                'button[aria-label="Close"]'
            ).first
            if close_btn.is_visible(timeout=2000):
                close_btn.click()
        except Exception:
            pass

        return filepath

    except Exception as e:
        logger.error(f"Échec du téléchargement automatique : {e}")
        logger.info("Effectuez l'export manuellement dans le navigateur.")
        manual = input(">>> Chemin du fichier téléchargé (ou Entrée pour passer) : ").strip()
        return manual if manual else None


def scrape_year(page: Page, year: int, download_dir: str) -> list[str]:
    """Scrape les publications d'une année. Retourne les fichiers téléchargés.

    Utilise Fast 5000 : exporte jusqu'à 5000 records d'un coup.
    Si plus de 5000, on fait plusieurs exports (non implémenté pour le moment,
    on demandera à l'utilisateur de faire les exports manuels supplémentaires).
    """
    query = build_query(year)
    run_search(page, query)

    files = []

    # Premier export Fast 5000
    filepath = do_export(page, download_dir, batch_num=1)
    if filepath:
        files.append(filepath)

        # Vérifier combien de records on a obtenu
        try:
            records = parse_wos_file(filepath)
            count = len(records)
            logger.info(f"Premier export : {count} records")
            if count >= 5000:
                logger.warning(
                    f"L'export contient 5000 records (limite Fast 5000). "
                    f"Il y a probablement plus de résultats pour {year}."
                )
                logger.info(
                    "Vous pouvez exporter les records restants manuellement "
                    "(Records from 5001 to ...) et les placer dans le même dossier."
                )
                more = input(">>> Chemin d'un fichier supplémentaire (ou Entrée pour continuer) : ").strip()
                if more and os.path.isfile(more):
                    files.append(more)
        except Exception:
            pass
    else:
        logger.warning(f"Export manqué pour {year}")

    return files


# =====================================================================
#  3. INSERTION EN BASE
# =====================================================================

def insert_records(records: list[dict], dry_run: bool = False) -> int:
    """Insère les records dans staging_wos. Retourne le nombre d'insertions."""
    if not HAS_DB:
        logger.error("psycopg2 non disponible, impossible d'insérer en base")
        return 0

    if dry_run:
        logger.info(f"[DRY RUN] {len(records)} records à insérer")
        return 0

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Récupérer les UT existants
            cur.execute("SELECT ut FROM staging_wos")
            existing = {row[0] for row in cur.fetchall()}

            batch = []
            for rec in records:
                ut = rec["ut"]
                if not ut or ut in existing:
                    continue
                batch.append((ut, rec["doi"], Json(rec["raw"])))
                existing.add(ut)

            if not batch:
                logger.info("Aucun nouveau record à insérer")
                return 0

            execute_values(
                cur,
                """INSERT INTO staging_wos (ut, doi, raw_data)
                   VALUES %s ON CONFLICT (ut) DO NOTHING""",
                batch,
                template="(%s, %s, %s::jsonb)",
            )
            conn.commit()
            logger.info(f"{len(batch)} records insérés dans staging_wos")
            return len(batch)
    finally:
        conn.close()


# =====================================================================
#  4. MAIN
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description="Scraper WoS via Playwright")
    parser.add_argument("--year", type=int, help="Année spécifique")
    parser.add_argument("--skip-login", action="store_true",
                        help="Sauter le login (session déjà active)")
    parser.add_argument("--download-only", action="store_true",
                        help="Télécharger sans parser/insérer")
    parser.add_argument("--parse-only", action="store_true",
                        help="Parser les fichiers existants sans scraper")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parser sans insérer en base")
    args = parser.parse_args()

    years = [args.year] if args.year else WOS["years"]
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    logger.info("=== Scraper Web of Science démarré ===")
    logger.info(f"Années : {years}")

    all_files: list[str] = []

    # --- Phase 1 : Scraping ---
    if not args.parse_only:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=False,  # Navigateur visible !
                slow_mo=500,     # Ralentir pour simuler un humain
            )
            context = browser.new_context(
                accept_downloads=True,
                viewport={"width": 1400, "height": 900},
            )
            page = context.new_page()

            # Login
            if not args.skip_login:
                login(page)
            else:
                page.goto("https://www.webofscience.com/wos/woscc/advanced-search",
                           timeout=30000)
                page.wait_for_load_state("networkidle", timeout=30000)

            # Scraper chaque année
            for i, year in enumerate(years):
                logger.info(f"\n{'='*60}")
                logger.info(f"ANNÉE {year}")
                logger.info(f"{'='*60}")

                year_dir = os.path.join(DOWNLOAD_DIR, str(year))
                os.makedirs(year_dir, exist_ok=True)

                try:
                    files = scrape_year(page, year, year_dir)
                    all_files.extend(files)
                except Exception as e:
                    logger.error(f"Erreur sur l'année {year} : {e}")
                    logger.info("Vous pouvez intervenir manuellement.")
                    cont = input(">>> Continuer avec l'année suivante ? (O/n) : ").strip()
                    if cont.lower() == "n":
                        break

                # Pause entre les années
                if i < len(years) - 1:
                    logger.info("Pause de 10s avant l'année suivante...")
                    time.sleep(10)

            browser.close()

    # --- Phase 2 : Parsing ---
    if args.download_only:
        logger.info(f"Download terminé. {len(all_files)} fichiers téléchargés.")
        return

    # Collecter les fichiers à parser
    if args.parse_only:
        # Parser tous les fichiers existants
        all_files = sorted(glob.glob(os.path.join(DOWNLOAD_DIR, "**", "*.txt"), recursive=True))
        logger.info(f"{len(all_files)} fichiers trouvés à parser")

    if not all_files:
        logger.warning("Aucun fichier à parser")
        return

    all_records = []
    for filepath in all_files:
        logger.info(f"Parsing : {filepath}")
        try:
            records = parse_wos_file(filepath)
            logger.info(f"  → {len(records)} records")
            all_records.extend(records)
        except Exception as e:
            logger.error(f"  Erreur de parsing : {e}")

    logger.info(f"\nTotal : {len(all_records)} records parsés")

    # Dédoublonner par UT
    seen = set()
    unique = []
    for rec in all_records:
        if rec["ut"] not in seen:
            seen.add(rec["ut"])
            unique.append(rec)
    logger.info(f"Après dédoublonnage : {len(unique)} records uniques")

    # Stats
    with_doi = sum(1 for r in unique if r["doi"])
    logger.info(f"  Avec DOI : {with_doi}")
    logger.info(f"  Sans DOI : {len(unique) - with_doi}")

    # Aperçu
    for rec in unique[:3]:
        logger.info(f"  [{rec['_year']}] {rec['_title'][:80]}...")

    # --- Phase 3 : Insertion ---
    inserted = insert_records(unique, dry_run=args.dry_run)
    logger.info(f"\n=== Terminé : {inserted} records insérés sur {len(unique)} uniques ===")


if __name__ == "__main__":
    main()
