"""
Détection du pays d'adresses institutionnelles via les noms d'institutions.

Cherche les formes `place_name_forms` de `kind = 'institution'` (universités, CHU…)
comme sous-chaînes du `normalized_text` de chaque adresse sans pays, via un automate
Aho-Corasick (cf. application/pipeline/countries/place_name_detector.py). Quand
toutes les institutions matchées pointent le même pays, écrit `countries`
(autoritaire) ; en cas de conflit (pays multiples), n'écrit rien.

Se lance après detect_address_countries.py (noms de pays en fin de segment) et
avant suggest_address_countries.py (emprunt flou).

Usage:
    python -m interfaces.cli.pipeline.detect_institution_countries
    python -m interfaces.cli.pipeline.detect_institution_countries --suggest  # → suggested_countries
"""

import argparse

from sqlalchemy import Connection, bindparam, func, select, update

from application.pipeline.countries.place_name_detector import PlaceNameDetector
from application.pipeline.metrics import PhaseMetrics
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.tables import addresses, place_name_forms
from infrastructure.observability.log import setup_logger

logger = setup_logger("detect_institution_countries", "processing/logs")


def load_institution_forms(conn: Connection) -> dict[str, str]:
    """Charge les formes d'institutions (`place_name_forms`, `kind = 'institution'`)."""
    stmt = select(place_name_forms.c.form_normalized, place_name_forms.c.iso_code).where(
        place_name_forms.c.kind == "institution"
    )
    return {r.form_normalized: r.iso_code for r in conn.execute(stmt)}


def detect_institution_countries(conn: Connection, *, direct: bool = True) -> PhaseMetrics:
    """Détecte le pays d'adresses institutionnelles via les noms d'institutions.

    Phase importable depuis `run_pipeline.py` ; ne ferme pas la connexion. Pour
    chaque adresse sans pays, si toutes les institutions matchées pointent le même
    pays, écrit `countries` (autoritaire ; `direct=False` → `suggested_countries`).
    Conflit (pays multiples) → rien écrit, laissé à la passe `suggest`.

    `total` = adresses sans pays examinées, `new` = adresses résolues,
    `extras["conflicts"]` = adresses à pays multiples ignorées.
    """
    forms = load_institution_forms(conn)
    logger.info(f"{len(forms)} formes d'institutions chargées")
    if not forms:
        return PhaseMetrics()
    detector = PlaceNameDetector(forms)

    rows = conn.execute(
        select(addresses.c.id, addresses.c.normalized_text).where(
            addresses.c.countries.is_(None) & (func.length(addresses.c.normalized_text) >= 5)
        )
    ).all()
    logger.info(f"{len(rows)} adresses sans pays à examiner")

    matched: list[tuple[int, list[str]]] = []
    conflicts = 0
    for r in rows:
        isos = detector.detect(r.normalized_text)
        if len(isos) == 1:
            matched.append((r.id, [next(iter(isos))]))
        elif len(isos) > 1:
            conflicts += 1
    logger.info(f"Résolues : {len(matched)}, conflits (pays multiples, ignorés) : {conflicts}")

    column = addresses.c.countries if direct else addresses.c.suggested_countries
    stmt = (
        update(addresses)
        .where(addresses.c.id == bindparam("addr_id"))
        .values({column: bindparam("val")})
    )
    for i in range(0, len(matched), 5000):
        batch = matched[i : i + 5000]
        conn.execute(stmt, [{"addr_id": addr_id, "val": val} for addr_id, val in batch])
    conn.commit()

    return PhaseMetrics(total=len(rows), new=len(matched), extras={"conflicts": conflicts})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--suggest",
        action="store_true",
        help="Écrire dans suggested_countries au lieu de countries (revue manuelle)",
    )
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        metrics = detect_institution_countries(conn, direct=not args.suggest)
    logger.info(metrics.as_summary())


if __name__ == "__main__":
    main()
