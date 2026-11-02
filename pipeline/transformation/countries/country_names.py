"""Noms de pays du référentiel `place_name_forms`."""

from sqlalchemy import Connection, text

from domain.countries import PlaceNameKind
from domain.country_detection import CountryNames


def load_country_names(conn: Connection) -> CountryNames:
    """Renvoie les formes normalisées des noms de pays : variantes anglaises et françaises, codes ISO, abréviations."""
    rows = conn.execute(
        text(
            "SELECT form_normalized, iso_code FROM place_name_forms "
            f"WHERE kind = '{PlaceNameKind.COUNTRY.value}'"
        )
    ).all()
    return CountryNames({r.form_normalized: r.iso_code for r in rows})
