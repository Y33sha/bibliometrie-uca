# STATUS: oneshot (2026-11-04)
"""Liste des personnes RH avec, pour chacune, le nombre de publications, de publications avec adresse brute, et de publications dont aucune adresse brute ne mentionne une structure du périmètre.

Une publication compte comme « avec adresse brute » quand l'une des contributions sources de la personne dans la publication a une adresse d'origine `raw`. Elle compte comme « sans structure du périmètre » quand aucune de ces adresses brutes n'est rattachée à une structure du périmètre (rattachement non infirmé). Ces publications signalent de potentiels homonymes.

Le script écrit un CSV trié par nombre de publications sans structure du périmètre décroissant. Il n'écrit pas dans la base.

Usage :
    uv run python -m interfaces.cli.oneshot.measure_hr_person_addresses [--output data/personnes_rh_adresses.csv]
"""

import argparse
import csv
from pathlib import Path

from sqlalchemy import text

from infrastructure.db.engine import build_sync_engine

_DEFAULT_OUTPUT = Path("data/personnes_rh_adresses.csv")

_QUERY = text("""
    WITH perimeter AS (
        SELECT ps.structure_id
        FROM structures.perimeter_structures ps
        JOIN structures.perimeters pr ON pr.id = ps.perimeter_id
        WHERE pr.code = (SELECT value #>> '{}' FROM ops.config WHERE key = 'perimeter_extraction')
    ),
    hr_persons AS (
        SELECT person_id, string_agg(DISTINCT siham_id, ' | ') AS siham_ids
        FROM persons.hr_records
        GROUP BY person_id
    ),
    hr_units AS (
        SELECT person_id, string_agg(DISTINCT unit_label, ' | ') AS units
        FROM persons.hr_periods
        GROUP BY person_id
    ),
    raw_addresses AS (
        SELECT c.id AS contribution_id,
               bool_or(EXISTS (
                   SELECT 1 FROM structures.address_structures ast
                   WHERE ast.address_id = a.id
                     AND ast.is_confirmed IS DISTINCT FROM false
                     AND ast.structure_id IN (SELECT structure_id FROM perimeter)
               )) AS in_perimeter
        FROM publications.contributions c
        JOIN hr_persons h ON h.person_id = c.person_id
        JOIN publications.aligned_source_contributions asc_ ON asc_.contribution_id = c.id
        JOIN sources.source_contribution_addresses sca ON sca.source_contribution_id = asc_.source_contribution_id
        JOIN structures.addresses a ON a.id = sca.address_id AND a.origin = 'raw'
        GROUP BY c.id
    )
    SELECT p.id AS person_id, p.last_name, p.first_name, h.siham_ids, u.units, p.exclusion::text AS exclusion,
           count(DISTINCT c.publication_id) AS publications,
           count(DISTINCT c.publication_id) FILTER (WHERE r.contribution_id IS NOT NULL) AS with_raw_address,
           count(DISTINCT c.publication_id) FILTER (WHERE NOT r.in_perimeter) AS raw_address_outside_perimeter
    FROM hr_persons h
    JOIN persons.persons p ON p.id = h.person_id
    LEFT JOIN hr_units u ON u.person_id = h.person_id
    LEFT JOIN publications.contributions c ON c.person_id = h.person_id
    LEFT JOIN raw_addresses r ON r.contribution_id = c.id
    GROUP BY p.id, p.last_name, p.first_name, h.siham_ids, u.units, p.exclusion
    ORDER BY raw_address_outside_perimeter DESC, publications DESC, p.last_name, p.first_name
""")

_HEADER = (
    "person_id",
    "nom",
    "prénom",
    "siham_id",
    "unités RH",
    "exclusion",
    "publications",
    "publications avec adresse brute",
    "publications avec adresse brute sans structure du périmètre",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    args = parser.parse_args()

    with build_sync_engine().connect() as conn:
        rows = conn.execute(_QUERY).all()

    with args.output.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_HEADER)
        writer.writerows(rows)
    print(f"{len(rows)} personnes RH écrites dans {args.output}")


if __name__ == "__main__":
    main()
