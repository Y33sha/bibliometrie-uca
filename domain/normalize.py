"""Fonctions de normalisation centralisées.

Toutes les normalisations textuelles du projet passent par ce module
afin d'éviter la duplication et les incohérences.

La normalisation Python est alignée sur la fonction SQL normalize_name_form() :
  lowercase → unaccent → tout sauf [a-z0-9] → espaces → collapse
"""

import re
import unicodedata

# Caractères Unicode qui doivent être remplacés par leur équivalent ASCII
# avant la suppression des non-ASCII (sinon ils disparaissent silencieusement
# et collent les mots : "Abeywickrama‐Samarakoon" → "abeywickramasamarakoon").
# Les ligatures œ/æ sont avalées par NFKD + encode("ascii", "ignore") parce
# qu'elles ne se décomposent pas (un seul caractère sans diacritique) : on
# les expanse explicitement vers oe/ae. `str.maketrans` accepte les valeurs
# multi-caractères quand on lui passe un dict.
_UNICODE_TO_ASCII = str.maketrans(
    {
        "\u2010": "-",  # HYPHEN
        "\u2011": "-",  # NON-BREAKING HYPHEN
        "\u2012": "-",  # FIGURE DASH
        "\u2013": "-",  # EN DASH
        "\u2014": "-",  # EM DASH
        "\u2015": "-",  # HORIZONTAL BAR
        "\u2018": "'",  # LEFT SINGLE QUOTATION MARK
        "\u2019": "'",  # RIGHT SINGLE QUOTATION MARK (apostrophe typographique)
        "\u201a": "'",  # SINGLE LOW-9 QUOTATION MARK
        "\u201c": '"',  # LEFT DOUBLE QUOTATION MARK
        "\u201d": '"',  # RIGHT DOUBLE QUOTATION MARK
        "\u2032": "'",  # PRIME
        "\u00ad": "-",  # SOFT HYPHEN
        "\u0153": "oe",  # LATIN SMALL LIGATURE OE (\u0153)
        "\u00e6": "ae",  # LATIN SMALL LIGATURE AE (\u00e6)
    }
)


def normalize_text(text: str) -> str:
    """Normalise un texte pour comparaison / dédoublonnage / matching.

    Pipeline :
      1. minuscules + strip
      2. remplacer les tirets/apostrophes Unicode par ASCII
      3. NFKD (décompose les accents)
      4. ASCII encode/ignore (supprime les combining marks)
      5. tout sauf [a-z0-9] → espaces
      6. collapse espaces multiples
    """
    if not text:
        return ""
    text = text.lower().strip()
    text = text.translate(_UNICODE_TO_ASCII)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


# Alias — normalize_name est identique à normalize_text.
# Les deux noms sont conservés pour la lisibilité du code appelant.
normalize_name = normalize_text

# Équivalent Python de la fonction SQL normalize_name_form()
normalize_name_form = normalize_text
