"""Détection du pays d'une adresse par **nom de pays** en fin d'adresse : candidat `country_name`.

Confronte les derniers tokens du `normalized_text` de chaque adresse en file (`address_candidates_queue`) aux noms de pays de `place_name_forms` (`kind = 'country'` : variantes anglais/français, codes ISO, abréviations), le plus long l'emportant. Le candidat `country_name` est recalculé en entier pour chaque adresse traitée. L'appelant commite.
"""

import logging

from sqlalchemy import Connection, text

from domain.countries import PlaceNameKind
from domain.country_detection import CountryDetectionMethod
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, quantity, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.countries.store import CountryCandidatesStore


def load_country_forms(conn: Connection) -> dict[str, str]:
    """Formes normalisées des noms de pays, chacune avec le code ISO du pays qu'elle désigne : `{forme: code ISO}`."""
    rows = conn.execute(
        text(
            "SELECT form_normalized, iso_code FROM place_name_forms "
            f"WHERE kind = '{PlaceNameKind.COUNTRY.value}'"
        )
    ).all()
    return {r.form_normalized: r.iso_code for r in rows}


def _match_trailing_country(
    normalized_text: str, country_forms: dict[str, str], max_tokens: int
) -> str | None:
    """Code ISO du plus long nom de pays qui termine `normalized_text`, ou None.

    Teste les suffixes de N tokens décroissants (N ≤ `max_tokens`) : le plus long l'emporte, de sorte qu'« united kingdom » prime sur « kingdom »."""
    tokens = normalized_text.split()
    for n in range(min(max_tokens, len(tokens)), 0, -1):
        iso = country_forms.get(" ".join(tokens[-n:]))
        if iso:
            return iso
    return None


def run(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Ajoute le candidat `country_name` des adresses à traiter qui se terminent par un nom de pays.

    `seen` = adresses examinées, `new` = adresses qui reçoivent un candidat, `extras["unmatched"]` = adresses sans nom de pays final.
    """
    step(logger, "Pays des adresses d'après le nom de pays qui les termine")
    store = CountryCandidatesStore(conn)
    country_forms = load_country_forms(conn)
    max_tokens = max((form.count(" ") + 1 for form in country_forms), default=1)

    rows = store.queued_addresses()
    logger.info("%s%s à traiter", BRANCH, quantity(len(rows), "adresse"))

    matched: list[tuple[int, list[str]]] = []
    for addr_id, normalized_text in rows:
        if iso := _match_trailing_country(normalized_text, country_forms, max_tokens):
            matched.append((addr_id, [iso]))

    added = store.replace_for_queued_addresses(CountryDetectionMethod.COUNTRY_NAME, matched)
    logger.info("%spays trouvé pour %s", LAST_BRANCH, quantity(added, "adresse"))
    return PhaseMetrics(seen=len(rows), new=added, extras={"unmatched": len(rows) - len(matched)})
