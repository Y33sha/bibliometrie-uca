"""Synchronisation d'une table de liens clé → structure sur les structures détectées par leurs formes de nom.

Deux tables suivent ce modèle : `address_structures` (adresses) et `idref_structures` (PPN des laboratoires partenaires de thèse). Chaque lien garde la forme à l'origine de sa détection (`matched_form_id`) et la décision de l'administration (`is_confirmed`).
"""

from dataclasses import dataclass
from typing import NamedTuple

from sqlalchemy import Connection, text


@dataclass(frozen=True, slots=True)
class DetectionTable:
    """Table de liens : son nom, sa colonne clé et le type SQL de la clé."""

    name: str
    key: str
    key_type: str


ADDRESS_STRUCTURES = DetectionTable("address_structures", "address_id", "int")
IDREF_STRUCTURES = DetectionTable("idref_structures", "idref_ppn", "text")


class Detection(NamedTuple):
    """Structure reconnue pour une clé par une forme de nom."""

    key: int | str
    structure_id: int
    form_id: int


def sync_detections(
    conn: Connection,
    table: DetectionTable,
    detections: list[Detection],
    *,
    scope: list[int] | list[str] | None = None,
) -> None:
    """Aligne les liens de la table sur les détections.

    Un lien automatique absent des détections est supprimé. Un lien confirmé ou infirmé par l'administration reste en place et perd sa forme d'origine. Les liens détectés sont insérés ou mis à jour, seulement s'ils changent. `scope` restreint la synchronisation aux liens de ces clés ; `None` couvre toute la table.
    """
    if scope is not None and not scope:
        return
    detected = (
        f"unnest(CAST(:keys AS {table.key_type}[]), CAST(:sids AS int[]), CAST(:fids AS int[]))"
        " AS d(key, sid, fid)"
    )
    undetected = f"NOT EXISTS (SELECT 1 FROM {detected} WHERE d.key = t.{table.key} AND d.sid = t.structure_id)"
    if scope is not None:
        undetected += f" AND t.{table.key} = ANY(CAST(:scope AS {table.key_type}[]))"
    params = {
        "keys": [d.key for d in detections],
        "sids": [d.structure_id for d in detections],
        "fids": [d.form_id for d in detections],
        "scope": scope,
    }
    conn.execute(
        text(f"DELETE FROM {table.name} t WHERE t.is_confirmed IS NULL AND {undetected}"), params
    )
    conn.execute(
        text(f"""
            UPDATE {table.name} t SET matched_form_id = NULL
            WHERE t.is_confirmed IS NOT NULL AND t.matched_form_id IS NOT NULL AND {undetected}
        """),
        params,
    )
    conn.execute(
        text(f"""
            INSERT INTO {table.name} ({table.key}, structure_id, matched_form_id)
            SELECT d.key, d.sid, d.fid FROM {detected}
            ON CONFLICT ({table.key}, structure_id) DO UPDATE SET matched_form_id = EXCLUDED.matched_form_id
                WHERE {table.name}.matched_form_id IS DISTINCT FROM EXCLUDED.matched_form_id
        """),
        params,
    )
