# STATUS: oneshot (2026-05-26)
"""
Audit (pure lecture) : combien de publishers locaux sans `openalex_id`
pourraient en gagner un via le champ `host_organization` des sources
OpenAlex de leurs journals — et combien entreraient en collision avec
des `openalex_id` déjà attribués à d'autres publishers (= doublons à
fusionner).

Ne fait AUCUNE écriture en base. Sert à décider, avant Phase 2 :
- (a) attribuer les `safe`, queuer les `conflict` pour dédoublonnage
  manuel ;
- (b) ou exécuter Phase 2 partielle et différer la déduplication à un
  chantier dédié.

Usage :
    python -m interfaces.cli.oneshot.audit_publisher_openalex_via_journals
"""

from __future__ import annotations

import os
import time
from collections import defaultdict

from sqlalchemy import text

from application.pipeline.publishers_journals.enrich_journals_from_openalex import (
    BATCH_SIZE,
    fetch_sources_batch,
    to_short_id,
)
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sources.api_limits import DOAJ_DELAY
from infrastructure.sources.config import (
    get_api_base_urls,
    get_openalex_api_key,
    get_polite_pool_email,
)

log = setup_logger("audit_publisher_openalex_via_journals", os.path.dirname(__file__))


def main() -> int:
    engine = get_sync_engine()
    with engine.connect() as conn:
        api_key = get_openalex_api_key(conn)
        mailto = get_polite_pool_email(conn)
        openalex_sources_api = get_api_base_urls(conn)["openalex_sources"]

        # 1. Charger le set des openalex_id déjà attribués à un publisher
        # (= contraintes de collision). On garde aussi le nom pour le report.
        occupied_rows = conn.execute(
            text("""
                SELECT openalex_id, id, name
                FROM publishers
                WHERE openalex_id IS NOT NULL
            """)
        ).all()
        # short_id (sans préfixe URL) → (publisher_id, name)
        occupied: dict[str, tuple[int, str]] = {
            to_short_id(r.openalex_id): (r.id, r.name) for r in occupied_rows
        }
        log.info("openalex_id déjà occupés en base : %d", len(occupied))

        # 2. Publishers candidats : sans openalex_id, actifs (≥ 1 publi),
        # avec au moins un journal OA-typé. On ramène (publisher_id, name,
        # journal_openalex_id) — 1 ligne par journal.
        rows = conn.execute(
            text("""
                SELECT p.id AS pub_id, p.name AS pub_name, j.openalex_id AS j_oa_id
                FROM publishers p
                JOIN journals j ON j.publisher_id = p.id
                WHERE p.openalex_id IS NULL
                  AND j.openalex_id IS NOT NULL
                  AND EXISTS (
                      SELECT 1 FROM publications pub
                      JOIN journals j2 ON j2.id = pub.journal_id
                      WHERE j2.publisher_id = p.id
                  )
                ORDER BY p.id
            """)
        ).all()
        pub_to_name: dict[int, str] = {}
        pub_to_journal_oas: dict[int, list[str]] = defaultdict(list)
        for r in rows:
            pub_to_name[r.pub_id] = r.pub_name
            pub_to_journal_oas[r.pub_id].append(to_short_id(r.j_oa_id))
        all_journal_oa_ids: list[str] = sorted(
            {oa for oas in pub_to_journal_oas.values() for oa in oas}
        )
        log.info(
            "Publishers candidats : %d (journals OA distincts à fetcher : %d)",
            len(pub_to_journal_oas),
            len(all_journal_oa_ids),
        )

        if not pub_to_journal_oas:
            log.info("Rien à faire.")
            return 0

        # 3. Batch fetch des host_organization pour tous les journals OA
        # concernés. Select restreint pour économiser bande passante.
        journal_to_host: dict[str, str | None] = {}
        for i in range(0, len(all_journal_oa_ids), BATCH_SIZE):
            batch = all_journal_oa_ids[i : i + BATCH_SIZE]
            sources = fetch_sources_batch(
                batch,
                log,
                openalex_sources_api=openalex_sources_api,
                api_key=api_key,
                mailto=mailto,
                select="id,host_organization",
            )
            time.sleep(DOAJ_DELAY)
            for oa_id in batch:
                source = sources.get(oa_id)
                host_url = source.get("host_organization") if source else None
                journal_to_host[oa_id] = to_short_id(host_url) if host_url else None
            log.info(
                "  %d/%d journals fetchés",
                min(i + BATCH_SIZE, len(all_journal_oa_ids)),
                len(all_journal_oa_ids),
            )

        # 4. Pour chaque publisher candidat, agréger les host_organization
        # distincts observés sur ses journals.
        pub_to_hosts: dict[int, set[str]] = {}
        for pub_id, journal_oas in pub_to_journal_oas.items():
            pub_to_hosts[pub_id] = {
                h for j in journal_oas if (h := journal_to_host.get(j)) is not None
            }

        # 5. Classifier
        safe: list[tuple[int, str, str]] = []  # (pub_id, pub_name, host)
        conflict: list[tuple[int, str, str, int, str]] = []  # + (occupant_id, occupant_name)
        multi_host: list[tuple[int, str, set[str]]] = []
        no_host: list[tuple[int, str]] = []

        for pub_id, hosts in pub_to_hosts.items():
            name = pub_to_name[pub_id]
            if not hosts:
                no_host.append((pub_id, name))
            elif len(hosts) > 1:
                multi_host.append((pub_id, name, hosts))
            else:
                host = next(iter(hosts))
                if host in occupied:
                    occ_id, occ_name = occupied[host]
                    conflict.append((pub_id, name, host, occ_id, occ_name))
                else:
                    safe.append((pub_id, name, host))

        # 6. Report
        total = len(pub_to_hosts)
        log.info("─" * 70)
        log.info("Bilan sur %d publishers candidats :", total)
        log.info("  safe         : %d  (attribution propre faisable)", len(safe))
        log.info(
            "  conflict     : %d  (l'openalex_id est déjà sur un autre publisher = doublon)",
            len(conflict),
        )
        log.info(
            "  multi_host   : %d  (journaux pointent vers plusieurs publishers OpenAlex)",
            len(multi_host),
        )
        log.info(
            "  no_host      : %d  (OpenAlex ne renvoie pas de host_organization)", len(no_host)
        )
        log.info("─" * 70)

        def _show(label: str, items: list, limit: int = 5) -> None:
            if not items:
                return
            log.info("Exemples %s (max %d) :", label, limit)
            for item in items[:limit]:
                log.info("  %s", item)

        _show("safe", safe)
        _show("conflict", conflict)
        _show("multi_host", multi_host)
        _show("no_host", no_host)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
