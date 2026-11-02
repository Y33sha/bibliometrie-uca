"""Règles sur les métadonnées d'une publication : titre, métadonnées minimales."""

import re

from domain.normalize import clean_source_text, normalize_text


def has_minimal_publication_metadata(title: str | None, publication_year: int | None) -> bool:
    """Vrai si une publication candidate a un titre et une année, condition de sa création. Une année à 0 compte comme absente."""
    return bool(title) and bool(publication_year)


TITLE_NORMALIZED_MAX_LENGTH = 2000


def is_overlong_title(title: str | None) -> bool:
    """Vrai si le titre normalisé dépasse `TITLE_NORMALIZED_MAX_LENGTH` caractères. Un titre aussi long réunit d'autres textes : programme de congrès, résumé, remerciements."""
    return bool(title) and len(normalize_text(title)) > TITLE_NORMALIZED_MAX_LENGTH


# Espaces ASCII seuls : les espaces insécables de la typographie (« pratiques : ») restent.
_ASCII_WHITESPACE_RE = re.compile(r"[ \t\n\r\f\v]+")


def clean_publication_title(title: str | None) -> str | None:
    """Nettoie un titre à son écriture (`clean_source_text`). Les suites d'espaces ASCII se réduisent à un espace, les espaces de bordure sont retirés."""
    if not title:
        return title
    return _ASCII_WHITESPACE_RE.sub(" ", clean_source_text(title)).strip()


def normalized_title(title: str | None) -> str:
    """Renvoie la forme de comparaison d'un titre, valeur de `source_records.title_normalized`."""
    return normalize_text(clean_publication_title(title) or "")
