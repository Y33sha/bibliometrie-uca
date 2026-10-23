# STATUS: oneshot (2026-10-10)
"""Audit (lecture seule) : compléter les auteurs tronqués pendant la pagination du moissonnage OpenAlex.

Parcourt une année du moissonnage OpenAlex par curseur, comme la phase `harvest`. Entre la lecture d'une page et la demande de la suivante, retélécharge par son identifiant chaque enregistrement qui compte exactement 100 auteurs dans la liste, plafond des réponses de liste. Rien n'est écrit en base.

Vérifie :

1. que la pagination arrive au bout, avec autant d'enregistrements que le total annoncé par OpenAlex ;
2. combien d'enregistrements retéléchargés reviennent avec plus de 100 auteurs, et combien en comptent bien 100.

Mesure le temps des retéléchargements.

Usage :
    python -m interfaces.cli.oneshot.audit_openalex_inline_truncation --year 2023
"""

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Mapping

from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str, at_path
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.read_models.perimeters import get_extraction_api_ids
from pipeline.http.circuit_breaker import source_circuit_breaker
from pipeline.http.http_retry import http_request_with_retry
from pipeline.ingestion.api_params import API_BASE_URLS, request_budget
from pipeline.ingestion.openalex.api import SELECT_FIELDS, auth_params, build_params
from pipeline.ingestion.openalex.fields import extract_openalex_id
from pipeline.ingestion.openalex.payload import BULK_AUTHORSHIPS_CAP

log = setup_logger("audit_openalex_inline_truncation", os.path.dirname(__file__))


def _get(
    url: str, params: Mapping[str, str | int | float | bool | None], label: str
) -> dict[str, JsonValue]:
    return dict(
        as_mapping(http_request_with_retry("GET", url, params=params, timeout=30, label=label))
    )


def audit(year: int) -> int:
    with get_sync_engine().connect() as conn:
        institution_ids = get_extraction_api_ids(conn, "openalex")
    works_url = API_BASE_URLS["openalex"]

    cursor = "*"
    pages = fetched = flagged = complete = genuine = failed = 0
    announced: int | None = None
    refetch_seconds = 0.0
    started = time.monotonic()

    while True:
        params = {
            **build_params(institution_ids, years=[year], cursor=cursor),
            "select": SELECT_FIELDS,
        }
        page = _get(works_url, params, f"page {pages + 1}")
        if announced is None:
            announced = as_int(at_path(page, "meta").get("count")) or 0
        results = [as_mapping(r) for r in as_sequence(page.get("results"))]
        if not results:
            break
        pages += 1
        fetched += len(results)

        t0 = time.monotonic()
        for work in results:
            if len(as_sequence(work.get("authorships"))) != BULK_AUTHORSHIPS_CAP:
                continue
            flagged += 1
            work_id = extract_openalex_id(work)
            try:
                full = _get(
                    f"{works_url}/{work_id}",
                    {"select": SELECT_FIELDS, **auth_params()},
                    f"work {work_id}",
                )
            except Exception as e:  # noqa: BLE001 — audit : on compte l'échec et on continue
                failed += 1
                log.warning("retéléchargement en échec pour %s : %s", work_id, e)
                continue
            if len(as_sequence(full.get("authorships"))) > BULK_AUTHORSHIPS_CAP:
                complete += 1
            else:
                genuine += 1
        refetch_seconds += time.monotonic() - t0

        cursor = as_str(at_path(page, "meta").get("next_cursor")) or ""
        if not cursor:
            break
        if pages % 10 == 0:
            log.info("%d pages, %d / %s enregistrements", pages, fetched, announced)

    total = time.monotonic() - started
    log.info(
        "Année %d : %d pages, %d enregistrements reçus sur %s annoncés",
        year,
        pages,
        fetched,
        announced,
    )
    log.info(
        "À 100 auteurs dans la liste : %d — plus de 100 en lecture unitaire : %d, 100 exactement : %d, échecs : %d",
        flagged,
        complete,
        genuine,
        failed,
    )
    log.info("Durée : %.0f s, dont %.0f s de retéléchargements", total, refetch_seconds)
    return 0 if fetched == announced and failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True, help="Année de publication parcourue.")
    with source_circuit_breaker("openalex", max_per_second=request_budget("openalex")):
        return audit(parser.parse_args().year)


if __name__ == "__main__":
    raise SystemExit(main())
