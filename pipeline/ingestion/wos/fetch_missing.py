"""Recherche par DOI dans Web of Science : tâche `fetch_missing.doi.wos`.

WoS accepte une requête groupée par DOI (`DO=("doi1" OR "doi2" OR …)`). Un lot compte 20 DOI, pour que l'URL reste courte ; ses résultats se lisent par pages de `WOS_PER_PAGE` records.

Les DOI de preprints que WoS n'indexe pas (Zenodo, arXiv, SSRN, Research Square…) restent hors des requêtes (`filter_doi_for_wos`).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

import httpx2

from domain.types import JsonValue
from pipeline.http.lookup import UNAVAILABLE, NotFound, Unavailable
from pipeline.ingestion.api_params import WOS_PER_PAGE
from pipeline.ingestion.common.lookup import LookupBatch
from pipeline.ingestion.wos.api import filter_doi_for_wos, get_records, get_records_found, search
from pipeline.ingestion.wos.fields import extract_doi

log = logging.getLogger(__name__)


class WosDoiSearch:
    """Recherche par DOI dans WoS (`DoiSearch`) : requête `DO=(…)`, par lots."""

    source_key = "wos"
    batch_size = 20
    # API instable : 2 requêtes simultanées au plus.
    max_concurrent = 2

    async def fetch_async(
        self, client: httpx2.AsyncClient, dois: list[str]
    ) -> LookupBatch | Unavailable:
        # DOI d'origine et forme envoyée à WoS, `None` pour un DOI écarté. Un DOI écarté reste hors des absents.
        queried = [(d, filter_doi_for_wos(d)) for d in dois]
        clean = [c for _, c in queried if c]

        records: list[Mapping[str, JsonValue]] = []
        # Vrai tant que le lot est lu en entier : après un arrêt prématuré (réseau, corps vide, réponse mal formée), l'absence d'un DOI ne prouve rien.
        complete = True
        first_record = 1
        while clean:
            query = "DO=(" + " OR ".join(f'"{d}"' for d in clean) + ")"
            data = await search(
                client, query, first_record=first_record, label=f"rec {first_record}"
            )
            if isinstance(data, NotFound):
                # 400 : lot sans correspondance, absent en entier de WoS.
                log.warning("WoS 400 rec %d, lot ignoré", first_record)
                break
            if isinstance(data, Unavailable):
                # Lot interrompu (réseau, corps vide) : les absents restent inconnus.
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

        if not complete:
            # Lot interrompu : les records reçus sont écrits, sans conclure sur les absents.
            return LookupBatch(records=records) if records else UNAVAILABLE
        # Lot complet : un DOI interrogé sans record est absent de WoS. Les DOI des records et les DOI cherchés passent tous par `clean_doi`.
        found = {d for r in records if (d := extract_doi(r))}
        return LookupBatch(
            records=records, absent=[orig for orig, c in queried if c and c not in found]
        )
