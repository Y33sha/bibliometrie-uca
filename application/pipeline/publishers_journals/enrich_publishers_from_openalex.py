"""
Sub-step de la phase pipeline `publishers_journals` — enrichit les
éditeurs à partir de l'API OpenAlex Publishers.

Champs mis à jour (si NULL côté DB, politique d'écrasement « ne pas
écraser un signal admin » — cf. décision 7 de
docs/chantiers/METIER_pipeline-publishers-journals.md) :
- `country` (depuis `country_codes[0]` ; un éditeur peut opérer dans
  plusieurs pays côté OpenAlex, on prend le premier qui correspond
  généralement au siège social)
- `ror` (depuis `ids.ror`, stocké en short form `02scfj030` sans le
  préfixe `https://ror.org/`)

Le `ror` posé ici sera consommé par le futur sub-step Phase 3 pour
dériver `publisher_type` via les types ROR.

L'API Publishers utilise un filtre différent de Sources :
`ids.openalex:P1|P2|...` (et non `openalex:`).
"""

import logging
import time
from collections import Counter

import requests
from sqlalchemy import Connection

from application.ports.pipeline.enrich import EnrichQueries
from application.ports.repositories.publisher_repository import (
    PublisherRepository,
    PublisherUpdateFields,
)

OPENALEX_PREFIX = "https://openalex.org/"
ROR_PREFIX = "https://ror.org/"
BATCH_SIZE = 50
COMMIT_EVERY = 500


def to_full_openalex_id(short_id: str) -> str:
    """Convertit 'P4310320990' → 'https://openalex.org/P4310320990'."""
    if short_id.startswith("http"):
        return short_id
    return OPENALEX_PREFIX + short_id


def to_short_openalex_id(full_id: str) -> str:
    """Convertit 'https://openalex.org/P4310320990' → 'P4310320990'."""
    if full_id.startswith(OPENALEX_PREFIX):
        return full_id[len(OPENALEX_PREFIX) :]
    return full_id


def to_short_ror(full_url: str) -> str:
    """Convertit 'https://ror.org/02scfj030' → '02scfj030'."""
    if full_url.startswith(ROR_PREFIX):
        return full_url[len(ROR_PREFIX) :]
    return full_url


def fetch_publishers_batch(
    openalex_ids: list[str],
    logger: logging.Logger,
    *,
    openalex_publishers_api: str,
    api_key: str | None,
    mailto: str,
) -> dict[str, dict]:
    """Interroge l'API OpenAlex Publishers pour un lot d'IDs et retourne
    un dict short_id → données. Select restreint aux champs consommés."""
    full_ids = [to_full_openalex_id(oid) for oid in openalex_ids]
    filter_value = "|".join(full_ids)
    params = {
        "filter": f"ids.openalex:{filter_value}",
        "per_page": str(len(openalex_ids)),
        "select": "id,country_codes,ids",
    }
    if api_key:
        params["api_key"] = api_key
    else:
        params["mailto"] = mailto

    for attempt in range(3):
        try:
            resp = requests.get(openalex_publishers_api, params=params, timeout=30)
            if resp.status_code == 429:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Rate limited (429), attente {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            results = {}
            for source in data.get("results", []):
                short = to_short_openalex_id(source["id"])
                results[short] = source
            return results
        except requests.RequestException as e:
            if attempt < 2:
                logger.warning(f"Erreur requête (tentative {attempt + 1}/3): {e}")
                time.sleep(2 ** (attempt + 1))
            else:
                logger.error(f"Échec après 3 tentatives: {e}")
                return {}
    return {}


def extract_country_ror(source: dict) -> tuple[str | None, str | None]:
    """Extrait `(country, ror)` depuis la payload OpenAlex Publishers.

    `country` = premier code de `country_codes` (vide → None).
    `ror` = `ids.ror` parsé en short form (vide → None).
    """
    country_codes = source.get("country_codes") or []
    country = country_codes[0] if country_codes else None

    ids = source.get("ids") or {}
    ror_url = ids.get("ror")
    ror = to_short_ror(ror_url) if ror_url else None

    return country, ror


def run_enrich_publishers_from_openalex(
    conn: Connection,
    queries: EnrichQueries,
    logger: logging.Logger,
    *,
    publisher_repo: PublisherRepository,
    api_key: str | None,
    mailto: str,
    openalex_publishers_api: str,
    limit: int = 0,
    dry_run: bool = False,
    rate_delay: float = 0.1,
) -> None:
    try:
        publishers = queries.fetch_publishers_needing_enrichment(conn, limit=limit or None)
        total = len(publishers)
        logger.info(f"{total} publishers à enrichir (avec openalex_id, manque country ou ror).")

        if total == 0:
            logger.info("Rien à faire.")
            return

        updated = 0
        with_country = 0
        with_ror = 0
        country_counter: Counter[str] = Counter()
        no_response = 0
        processed = 0

        # On a besoin du state actuel (country/ror déjà posés ?) pour
        # respecter la politique d'écrasement (NULL only). Charger en
        # bloc par batch pour éviter N+1.
        for i in range(0, total, BATCH_SIZE):
            batch = publishers[i : i + BATCH_SIZE]
            oa_ids = [row[1] for row in batch]
            id_map = {row[1]: row[0] for row in batch}

            sources = fetch_publishers_batch(
                oa_ids,
                logger,
                openalex_publishers_api=openalex_publishers_api,
                api_key=api_key,
                mailto=mailto,
            )
            time.sleep(rate_delay)

            for oa_id, publisher_id in id_map.items():
                source = sources.get(oa_id)
                if not source:
                    no_response += 1
                    processed += 1
                    continue

                country, ror = extract_country_ror(source)

                # On charge l'état actuel via l'aggregate pour décider du
                # gating "NULL only". Un fetch supplémentaire par publisher
                # — acceptable vu le volume (au max ~1000 publishers à
                # enrichir).
                current = publisher_repo.find_by_id(publisher_id)
                if current is None:
                    no_response += 1
                    processed += 1
                    continue

                fields: PublisherUpdateFields = {}
                if country and current.country is None:
                    fields["country"] = country
                    with_country += 1
                    country_counter[country] += 1
                if ror and current.ror is None:
                    fields["ror"] = ror
                    with_ror += 1

                if fields and not dry_run:
                    publisher_repo.update_publisher_fields(publisher_id, fields)
                    updated += 1
                elif fields:
                    updated += 1  # compté en dry-run aussi
                processed += 1

            if not dry_run and processed % COMMIT_EVERY < BATCH_SIZE:
                conn.commit()

            logger.info(
                f"  {min(i + BATCH_SIZE, total)}/{total} — {with_country} countries, {with_ror} ROR écrits"
            )

        if not dry_run:
            conn.commit()

        logger.info(
            f"Terminé : {updated}/{total} publishers mis à jour "
            f"({with_country} countries, {with_ror} ROR, {no_response} sans réponse)."
        )
        if country_counter:
            distrib = ", ".join(f"{c}={n}" for c, n in country_counter.most_common(10))
            logger.info(f"Top 10 countries posés : {distrib}")

    except KeyboardInterrupt:
        if not dry_run:
            conn.commit()
        logger.warning("Interruption — données déjà traitées conservées.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
