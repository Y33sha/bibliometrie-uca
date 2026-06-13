"""
Sub-step de la phase pipeline `publishers_journals` — enrichit les
revues à partir de l'API OpenAlex Sources.

Champs mis à jour :
- `apc_amount`, `apc_currency` (prix catalogue DOAJ exposés par OpenAlex)
- `journal_type` (via `domain.journals.journal.map_openalex_source_type`), uniquement quand le mapping renvoie une valeur exploitable

Utilise le filtre openalex avec pipe (|) pour interroger jusqu'à 50 sources par requête.

L'orchestrateur dépend du port `EnrichQueries`. Le point d'entrée CLI est dans `interfaces/cli/pipeline/enrich_journal_apc.py`. Pour ré-interroger toutes les revues ayant un openalex_id (et pas seulement celles sans APC), utiliser le script `interfaces/cli/oneshot/backfill_journal_types_from_openalex.py`.

Module renommé depuis `application/pipeline/enrich/enrich_journal_apc.py`
le 2026-05-26 dans le cadre de la refonte structurelle de la phase
`publishers_journals` (cf. METIER_pipeline-publishers-journals.md).
"""

import logging
import time
from collections import Counter

import requests
from sqlalchemy import Connection

from application.journals import update_journal_apc
from application.ports.pipeline.enrich import EnrichQueries
from application.ports.repositories.journal_repository import (
    JournalRepository,
    JournalUpdateFields,
)
from domain.journals.journal import map_openalex_source_type

OPENALEX_PREFIX = "https://openalex.org/"
BATCH_SIZE = 50  # max IDs par requête (API limit = 100, on reste prudent)
COMMIT_EVERY = 500  # commit DB tous les N journals traités


def to_full_id(short_id: str) -> str:
    """Convertit 'S20400310' → 'https://openalex.org/S20400310'."""
    if short_id.startswith("http"):
        return short_id
    return OPENALEX_PREFIX + short_id


def to_short_id(full_id: str) -> str:
    """Convertit 'https://openalex.org/S20400310' → 'S20400310'."""
    if full_id.startswith(OPENALEX_PREFIX):
        return full_id[len(OPENALEX_PREFIX) :]
    return full_id


_DEFAULT_SELECT = "id,apc_usd,apc_prices,type"


def fetch_sources_batch(
    openalex_ids: list[str],
    logger: logging.Logger,
    *,
    openalex_sources_api: str,
    api_key: str | None,
    mailto: str,
    select: str = _DEFAULT_SELECT,
) -> dict[str, dict]:
    """Interroge l'API OpenAlex pour un lot d'IDs et retourne un dict short_id → données.

    Le paramètre `select` permet aux scripts d'audit oneshot de demander
    des champs différents (ex. `id,host_organization`) sans dupliquer le
    code de batching/retry.
    """
    full_ids = [to_full_id(oid) for oid in openalex_ids]
    filter_value = "|".join(full_ids)
    params = {
        "filter": f"openalex:{filter_value}",
        "per_page": str(len(openalex_ids)),
        "select": select,
    }
    if api_key:
        params["api_key"] = api_key
    else:
        params["mailto"] = mailto

    for attempt in range(3):
        try:
            resp = requests.get(openalex_sources_api, params=params, timeout=30)
            if resp.status_code == 429:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Rate limited (429), attente {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            results = {}
            for source in data.get("results", []):
                short = to_short_id(source["id"])
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


def extract_apc(source: dict) -> tuple[float | None, str]:
    """Extrait le montant APC et la devise depuis les données OpenAlex.

    Priorité : EUR dans apc_prices > première devise dispo > apc_usd en USD.
    """
    apc_prices = source.get("apc_prices") or []

    for entry in apc_prices:
        if entry.get("currency") == "EUR":
            return entry["price"], "EUR"

    if apc_prices:
        entry = apc_prices[0]
        return entry["price"], entry.get("currency", "USD")

    apc_usd = source.get("apc_usd")
    if apc_usd is not None:
        return apc_usd, "USD"

    return None, "EUR"


def run_enrich_journals_from_openalex(
    conn: Connection,
    queries: EnrichQueries,
    logger: logging.Logger,
    *,
    journal_repo: JournalRepository,
    api_key: str | None,
    mailto: str,
    openalex_sources_api: str,
    limit: int = 0,
    dry_run: bool = False,
    rate_delay: float = 0.1,
) -> None:
    try:
        journals = queries.fetch_journals_of_unknown_type(conn, limit=limit or None)
        total = len(journals)
        logger.info(f"{total} revues à typer (openalex_id, journal_type inconnu).")

        if total == 0:
            logger.info("Rien à faire.")
            return

        updated = 0
        with_apc = 0
        processed = 0
        raw_type_counter: Counter[str] = Counter()
        type_written = 0

        for i in range(0, total, BATCH_SIZE):
            batch = journals[i : i + BATCH_SIZE]
            oa_ids = [row[1] for row in batch]
            id_map = {row[1]: row[0] for row in batch}

            sources = fetch_sources_batch(
                oa_ids,
                logger,
                openalex_sources_api=openalex_sources_api,
                api_key=api_key,
                mailto=mailto,
            )
            time.sleep(rate_delay)

            for oa_id, journal_id in id_map.items():
                source = sources.get(oa_id)
                if not source:
                    processed += 1
                    continue

                apc_amount, apc_currency = extract_apc(source)
                raw_type = source.get("type")
                mapped_type = map_openalex_source_type(raw_type)
                if raw_type:
                    raw_type_counter[raw_type] += 1

                if not dry_run:
                    update_journal_apc(
                        journal_id,
                        apc_amount=apc_amount,
                        apc_currency=apc_currency,
                        repo=journal_repo,
                    )
                    # journal_type : on ne traite que les revues `unknown`
                    # (cf. `fetch_journals_of_unknown_type`). On écrit dès que le
                    # mapping OpenAlex renvoie une valeur ; sinon la revue reste
                    # `unknown` (re-tentée au prochain run — cas `metadata`/`other`).
                    if mapped_type is not None:
                        journal_repo.update_journal_fields(
                            journal_id,
                            JournalUpdateFields(journal_type=mapped_type),
                        )
                        type_written += 1

                updated += 1
                if apc_amount is not None:
                    with_apc += 1
                processed += 1

            if not dry_run and processed % COMMIT_EVERY < BATCH_SIZE:
                conn.commit()

            logger.info(
                f"  {min(i + BATCH_SIZE, total)}/{total} — {with_apc} avec APC, {type_written} types écrits"
            )

        if not dry_run:
            conn.commit()

        logger.info(
            f"Terminé : {updated}/{total} revues mises à jour, "
            f"{with_apc} avec APC, {type_written} journal_type écrits."
        )
        if raw_type_counter:
            distrib = ", ".join(f"{t}={n}" for t, n in raw_type_counter.most_common())
            logger.info(f"Distribution OpenAlex `type` : {distrib}")

    except KeyboardInterrupt:
        # Ctrl+C peut frapper en plein execute (transaction avortée → `commit()`
        # lèverait `PendingRollbackError`) : on rollback le batch en cours et on
        # re-raise pour laisser `run_pipeline` arrêter proprement le pipeline.
        conn.rollback()
        logger.warning("Interruption — batches déjà committés conservés.")
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
