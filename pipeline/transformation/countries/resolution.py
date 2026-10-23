"""Résolution des pays d'une adresse : `addresses.countries` composé de ses pays candidats par la préséance du domaine (`retained_countries`)."""

import json
from collections import defaultdict

from sqlalchemy import Connection, text

from domain.country_detection import CountryDetectionMethod, retained_countries
from infrastructure.db.queues import Queue, enqueue_sql

# Adresses résolues par lot : chaque lot charge ses candidats en mémoire.
_RESOLVE_BATCH = 50_000

_MARK_CHANGED = enqueue_sql(Queue.ADDRESS_COUNTRIES, "SELECT id FROM changed")


def resolve_address_countries(conn: Connection, address_ids: list[int] | None = None) -> int:
    """Compose `addresses.countries` pour `address_ids`, ou pour les adresses `candidates_dirty` quand `address_ids` vaut `None`.

    Une adresse sans candidat perd son pays. Marque pour le recalcul des pays de leurs contributions sources les adresses dont le pays change, efface `candidates_dirty`. Retourne le nombre d'adresses dont le pays change.
    """
    if address_ids is None:
        address_ids = list(
            conn.execute(text("SELECT id FROM addresses WHERE candidates_dirty")).scalars()
        )
    changed = 0
    for start in range(0, len(address_ids), _RESOLVE_BATCH):
        ids = address_ids[start : start + _RESOLVE_BATCH]
        candidates: defaultdict[int, defaultdict[CountryDetectionMethod, list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for r in conn.execute(
            text(
                "SELECT address_id, country_code, method::text AS method"
                " FROM address_country_candidates WHERE address_id = ANY(:ids)"
            ),
            {"ids": ids},
        ):
            candidates[r.address_id][CountryDetectionMethod(r.method)].append(r.country_code)
        payload = json.dumps(
            [
                {"id": addr_id, "c": sorted(retained_countries(candidates.get(addr_id, {})))}
                for addr_id in ids
            ]
        )
        changed += conn.execute(
            text(f"""
                WITH changed AS (
                    UPDATE addresses a
                    SET countries = d.cty
                    FROM (
                        SELECT (e->>'id')::int AS id,
                               nullif(ARRAY(SELECT jsonb_array_elements_text(e->'c'))::char(2)[],
                                      '{{}}'::char(2)[]) AS cty
                        FROM jsonb_array_elements(CAST(:payload AS jsonb)) e
                    ) d
                    WHERE a.id = d.id AND a.countries IS DISTINCT FROM d.cty
                    RETURNING a.id
                ),
                marked AS ({_MARK_CHANGED})
                SELECT count(*) FROM changed
            """),
            {"payload": payload},
        ).scalar_one()
        conn.execute(
            text(
                "UPDATE addresses SET candidates_dirty = false"
                " WHERE id = ANY(:ids) AND candidates_dirty"
            ),
            {"ids": ids},
        )
    return changed
