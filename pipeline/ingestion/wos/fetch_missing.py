"""Recherche par DOI dans Web of Science : tâche `fetch_missing.doi.wos`.

WoS accepte une requête groupée par DOI (`DO=("doi1" OR "doi2" OR ...)`). Lot de 20 DOI par requête pour éviter des URLs trop longues, pagination interne de `WOS_PER_PAGE` records, retries exponentiels sur 429/erreurs.

Certains DOI (preprints Zenodo, arXiv, SSRN, Research Square...) sont systématiquement absents de WoS : on les filtre côté client pour éviter les appels inutiles.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping

import httpx2

from domain.types import JsonValue
from pipeline.http.lookup import UNAVAILABLE, NotFound, Unavailable
from pipeline.ingestion.api_params import WOS_DELAY, WOS_PER_PAGE
from pipeline.ingestion.common.lookup import LookupBatch
from pipeline.ingestion.wos.api import filter_doi_for_wos, get_records, get_records_found, search
from pipeline.ingestion.wos.fields import extract_doi

log = logging.getLogger(__name__)


class WosDoiSearch:
    """Recherche par DOI dans WoS (`DoiSearch`) : requête `DO=(…)`, par lots."""

    source_key = "wos"
    batch_size = 20
    # WoS Clarivate : instable, rate-limit serré (~2-5 req/s selon contrat).
    # `max_concurrent=2` × pause 500 ms, latence ~500 ms → ≈ 2 req/s (sous le seuil).
    max_concurrent = 2
    request_delay_s = 0.5

    async def fetch_async(
        self, client: httpx2.AsyncClient, dois: list[str]
    ) -> LookupBatch | Unavailable:
        # (doi d'origine, forme envoyable à WoS ou None si filtré). Les DOI preprints filtrés (c=None) ne sont pas interrogeables, donc jamais enregistrés comme not-found (le filtre client les écarte gratuitement).
        queried = [(d, filter_doi_for_wos(d)) for d in dois]
        clean = [c for _, c in queried if c]

        records: list[Mapping[str, JsonValue]] = []
        # complete : a-t-on un résultat fiable pour calculer les not-found ? Mis à False sur tout arrêt prématuré (erreur réseau, corps vide, réponse mal formée) où l'absence d'un DOI ne prouve rien.
        complete = True
        first_record = 1
        while clean:
            query = "DO=(" + " OR ".join(f'"{d}"' for d in clean) + ")"
            data = await search(
                client, query, first_record=first_record, label=f"rec {first_record}"
            )
            if isinstance(data, NotFound):
                # WoS 400 = lot sans correspondance : zéro match, le lot entier est confirmé absent (résultat fiable → on garde complete=True).
                log.warning("WoS 400 rec %d, lot ignoré", first_record)
                break
            if isinstance(data, Unavailable):
                # Lot non fiable (erreur réseau, corps vide) : on rend ce qu'on a sans calculer de not-found.
                complete = False
                break
            recs = get_records(data)
            if not recs:
                break
            records.extend(recs)

            total = get_records_found(data)
            if first_record + WOS_PER_PAGE - 1 >= total:
                break
            first_record += WOS_PER_PAGE
            await asyncio.sleep(WOS_DELAY)

        if not complete:
            # Lot interrompu : les records reçus sont écrits, sans conclure sur les absents.
            return LookupBatch(records=records) if records else UNAVAILABLE
        # Lot complet : tout DOI interrogé sans record correspondant est confirmé absent de WoS. `extract_doi` et les candidats sont tous deux normalisés par `clean_doi`, donc comparables directement.
        found = {d for r in records if (d := extract_doi(r))}
        return LookupBatch(
            records=records, absent=[orig for orig, c in queried if c and c not in found]
        )
