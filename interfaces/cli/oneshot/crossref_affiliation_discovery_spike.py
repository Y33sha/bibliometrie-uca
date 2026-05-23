# STATUS: oneshot (2026-05-23)
"""
Spike Phase 3 (suite) — chantier METIER_doi-ra-datacite (volet Crossref).

Évalue si `api.crossref.org/works?query.affiliation=…` permet de retrouver des publications UCA via leur affiliation textuelle, en parallèle de l'extracteur DataCite affiliation-driven évalué dans `datacite_affiliation_discovery_spike.py`. Crossref expose une recherche full-text Elasticsearch sur `query.affiliation` (substring/word match — pas d'égalité stricte), mais la couverture des affiliations dépend du publisher (Springer Nature, PLOS bien renseignés ; certains autres peu). À mesurer.

Filtre années 2020-2026 (périmètre des publications présentes en base actuelle).

NOTE : le diff avec la base est mesuré sur la base locale de cette session, qui n'est pas la base de prod. Le nombre de « nouveaux candidats » est donc indicatif ; à refaire sur prod pour le vrai delta.

Usage :
    python -m interfaces.cli.oneshot.crossref_affiliation_discovery_spike [--max-pages N]
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sources.config import get_openalex_email

log = setup_logger("crossref_affiliation_discovery_spike", os.path.dirname(__file__))

DATA_DIR = (
    Path(__file__).resolve().parents[3] / "docs" / "chantiers" / "datacite-vs-natives-spike-data"
)

CROSSREF_WORKS_URL = "https://api.crossref.org/works"
UCA_NAME = "Université Clermont Auvergne"
YEAR_FROM = 2020
YEAR_TO = 2026
PAGE_SIZE = 1000
SLEEP_BETWEEN_PAGES = 0.3


def _user_agent(email: str) -> str:
    return f"UCA-bibliometrie-spike/0.1 (mailto:{email})"


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def get_known_uca_dois(conn: Connection) -> set[str]:
    """DOIs déjà présents en base."""
    rows = conn.execute(
        text("SELECT lower(doi) AS doi FROM publications WHERE doi IS NOT NULL AND doi <> ''")
    ).fetchall()
    return {r.doi for r in rows}


def fetch_volume(client: httpx.Client) -> dict[str, Any]:
    """Page 1 (rows=5) pour mesurer le volume total et inspecter un échantillon."""
    resp = client.get(
        CROSSREF_WORKS_URL,
        params={
            "query.affiliation": UCA_NAME,
            "filter": f"from-pub-date:{YEAR_FROM},until-pub-date:{YEAR_TO}",
            "rows": 5,
        },
    )
    resp.raise_for_status()
    return resp.json()


def paginate_dois(client: httpx.Client, max_pages: int) -> list[str]:
    """Pagine les DOIs via deep paging Crossref. Le cursor renvoyé est un identifiant de session Elasticsearch stable côté serveur (les pages avancent même si le cursor ne change pas) — on stoppe sur `items` vide."""
    dois: list[str] = []
    cursor: str | None = "*"
    for page in range(max_pages):
        resp = client.get(
            CROSSREF_WORKS_URL,
            params={
                "query.affiliation": UCA_NAME,
                "filter": f"from-pub-date:{YEAR_FROM},until-pub-date:{YEAR_TO}",
                "rows": PAGE_SIZE,
                "cursor": cursor,
            },
        )
        resp.raise_for_status()
        msg = resp.json().get("message") or {}
        items = msg.get("items") or []
        page_dois = [(it.get("DOI") or "").lower() for it in items if it.get("DOI")]
        dois.extend(page_dois)
        next_cursor = msg.get("next-cursor")
        log.info(
            "    page %d : +%d DOIs (cumul %d)",
            page + 1,
            len(page_dois),
            len(dois),
        )
        if not page_dois or not next_cursor:
            break
        cursor = next_cursor
        time.sleep(SLEEP_BETWEEN_PAGES)
    return dois


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=30,
        help=f"Cap de pages (PAGE_SIZE={PAGE_SIZE} par page).",
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    engine = get_sync_engine()

    with engine.connect() as conn:
        user_agent = _user_agent(get_openalex_email(conn))
        known_dois = get_known_uca_dois(conn)
        log.info("Base connue (locale, pas prod) : %d DOIs UCA en publications", len(known_dois))

        with httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "application/json"}, timeout=30.0
        ) as client:
            # Étape 1 : volume
            log.info(
                "▶ Étape 1 — volume Crossref UCA %d-%d via query.affiliation",
                YEAR_FROM,
                YEAR_TO,
            )
            volume_payload = fetch_volume(client)
            total = (volume_payload.get("message") or {}).get("total-results")
            sample = [
                it.get("DOI") for it in (volume_payload.get("message") or {}).get("items", [])[:3]
            ]
            log.info("  total=%s, sample=%s", total, sample)
            _save_json(
                DATA_DIR / "crossref_affiliation_volume.json",
                {
                    "query_affiliation": UCA_NAME,
                    "year_from": YEAR_FROM,
                    "year_to": YEAR_TO,
                    "total": total,
                    "first_page": volume_payload,
                },
            )

            # Étape 2 : pagination
            log.info("▶ Étape 2 — pagination (cap %d pages × %d)", args.max_pages, PAGE_SIZE)
            all_dois = paginate_dois(client, args.max_pages)
            log.info("  Récupéré %d DOIs", len(all_dois))
            _save_json(
                DATA_DIR / "crossref_affiliation_dois.json",
                {
                    "query_affiliation": UCA_NAME,
                    "year_from": YEAR_FROM,
                    "year_to": YEAR_TO,
                    "dois": all_dois,
                },
            )

            # Étape 3 : diff avec la base
            discovered = set(all_dois)
            overlap = discovered & known_dois
            new = discovered - known_dois
            log.info("▶ Étape 3 — diff avec publications.doi (base locale)")
            log.info("  DOIs Crossref trouvés : %d", len(discovered))
            log.info(
                "  Déjà en base : %d (%.1f %%)",
                len(overlap),
                100 * len(overlap) / max(1, len(discovered)),
            )
            log.info(
                "  Nouveaux candidats : %d (%.1f %%) — sur base locale, non représentatif prod",
                len(new),
                100 * len(new) / max(1, len(discovered)),
            )

            new_by_prefix: dict[str, int] = {}
            for doi in new:
                p = doi.split("/", 1)[0] if "/" in doi else "?"
                new_by_prefix[p] = new_by_prefix.get(p, 0) + 1
            top_prefixes = sorted(new_by_prefix.items(), key=lambda kv: -kv[1])[:20]
            log.info("  Top préfixes des nouveaux candidats :")
            for p, n in top_prefixes:
                log.info("    %s : %d", p, n)

            _save_json(
                DATA_DIR / "crossref_affiliation_diff.json",
                {
                    "discovered_total": len(discovered),
                    "already_in_db": len(overlap),
                    "new_candidates": len(new),
                    "new_by_prefix_top20": top_prefixes,
                    "sample_new_dois": sorted(new)[:50],
                    "note": (
                        "Base locale, pas prod. À refaire sur la vraie base "
                        "pour mesurer le delta réel."
                    ),
                },
            )

    log.info("✓ outputs dans %s", DATA_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
