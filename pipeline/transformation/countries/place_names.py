"""Noms de lieux du référentiel `place_name_forms` : pays, villes, institutions."""

from sqlalchemy import Connection, text

from domain.countries import PlaceNameKind
from domain.country_detection import CountryNames


def load_place_forms(conn: Connection, kind: PlaceNameKind) -> dict[str, str]:
    """Renvoie les formes normalisées des noms de lieux de nature `kind`, avec le code ISO de leur pays : `{forme: code ISO}`."""
    rows = conn.execute(
        text("SELECT form_normalized, iso_code FROM place_name_forms WHERE kind = :kind"),
        {"kind": kind.value},
    ).all()
    return {r.form_normalized: r.iso_code for r in rows}


def load_country_names(conn: Connection) -> CountryNames:
    """Renvoie les formes normalisées des noms de pays : variantes anglaises et françaises, codes ISO, abréviations."""
    return CountryNames(load_place_forms(conn, PlaceNameKind.COUNTRY))
