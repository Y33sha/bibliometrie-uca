"""Détection du pays d'une adresse par **nom de lieu** : candidats `institution` et `city`.

Cherche dans tout le texte normalisé des adresses en file (`address_candidates_queue`) les noms d'institutions et de villes connus (`place_name_forms`), chacun rattaché à un pays, via un automate Aho-Corasick (`PlaceNameDetector`) par nature de lieu. Chaque pays trouvé devient un candidat du moyen de même nature : des lieux de pays différents donnent plusieurs candidats. Les candidats de ces deux moyens sont recalculés en entier pour chaque adresse traitée.

Le commit est laissé au caller.
"""

import logging

from sqlalchemy import Connection, text

from domain.countries import PlaceNameKind
from domain.country_detection import CountryDetectionMethod
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, quantity, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.countries.place_name_detector import PlaceNameDetector
from pipeline.transformation.countries.store import CountryCandidatesStore

_METHODS = {
    PlaceNameKind.INSTITUTION: CountryDetectionMethod.INSTITUTION,
    PlaceNameKind.CITY: CountryDetectionMethod.CITY,
}
_LABELS = {PlaceNameKind.INSTITUTION: "institutions", PlaceNameKind.CITY: "villes"}


def load_place_forms(conn: Connection, kind: PlaceNameKind) -> dict[str, str]:
    """Formes normalisées des noms de lieux de nature `kind` (institution ou ville), chacune avec le code ISO du pays où le lieu se situe : `{forme: code ISO}`."""
    rows = conn.execute(
        text("SELECT form_normalized, iso_code FROM place_name_forms WHERE kind = :kind"),
        {"kind": kind.value},
    ).all()
    return {r.form_normalized: r.iso_code for r in rows}


def run(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Ajoute les candidats `institution` et `city` des adresses à traiter.

    `seen` = adresses examinées, `new` = adresses qui reçoivent un candidat.
    """
    step(logger, "Pays des adresses d'après les noms de villes et d'institutions")
    store = CountryCandidatesStore(conn)
    rows = store.queued_addresses()
    added = 0
    for kind, method in _METHODS.items():
        detector = PlaceNameDetector(load_place_forms(conn, kind))
        proposals = [
            (addr_id, sorted(isos))
            for addr_id, normalized_text in rows
            if (isos := detector.detect(normalized_text))
        ]
        n = store.replace_for_queued_addresses(method, proposals)
        logger.info(
            "%s%s : pays trouvé pour %s",
            BRANCH if method is CountryDetectionMethod.INSTITUTION else LAST_BRANCH,
            _LABELS[kind],
            quantity(n, "adresse"),
        )
        added += n
    return PhaseMetrics(seen=len(rows), new=added)
