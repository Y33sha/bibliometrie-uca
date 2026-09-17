"""Clé de rapprochement des noms d'éditeurs."""

import re

from domain.normalize import normalize_text

# Formes juridiques retirées en fin de nom : « Elsevier BV », « Taylor & Francis Ltd », « S. Karger AG ».
_LEGAL_FORMS = frozenset(
    {
        "ag", "b", "bv", "co", "company", "corp", "corporation", "gmbh", "inc", "incorporated",
        "kg", "limited", "llc", "llp", "lp", "ltd", "nv", "plc", "pty", "pvt", "sa", "sarl",
        "sas", "spa", "srl", "v",
    }
)  # fmt: skip
_BRACKETS = re.compile(r"\[[^\]]*\]")
_PARENTHESES = re.compile(r"\([^)]*\)")
_ON_BEHALF_OF = re.compile(r"\bon behalf of\b.*$", re.IGNORECASE)
_YEARS = re.compile(r"\bc?\d{4}\s*-\s*(?:\d{4})?")


def _strip_legal_forms(words: list[str]) -> list[str]:
    while words and words[-1] in _LEGAL_FORMS:
        words = words[:-1]
    return words


def publisher_name_key(name: str) -> str:
    """Clé de rapprochement d'un nom d'éditeur : le nom normalisé, débarrassé du bruit que les sources y ajoutent.

    Sont retirés : les crochets (« Elsevier [1977-....] »), les années et périodes (« Nature Publishing Group, 2009- »), la mention « on behalf of » et sa suite, puis les formes juridiques finales. Les parenthèses (« Taylor & Francis (Routledge) », « Oxford University Press (UK) ») sont retirées, sauf si le nom se réduit alors à un seul mot court : « AIMS (Association internationale de management stratégique) » garde sa précision.
    """
    base = _YEARS.sub(" ", _ON_BEHALF_OF.sub(" ", _BRACKETS.sub(" ", name)))
    words = _strip_legal_forms(normalize_text(_PARENTHESES.sub(" ", base)).split())
    if len(words) == 1 and len(words[0]) <= 5:
        words = _strip_legal_forms(normalize_text(base).split())
    return " ".join(words)
