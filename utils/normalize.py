"""Fonctions de normalisation centralisées.

Toutes les normalisations textuelles du projet passent par ce module
afin d'éviter la duplication et les incohérences.
"""

import re
import unicodedata


def normalize_text(text: str) -> str:
    """Normalise un texte pour comparaison / dédoublonnage / matching.

    Pipeline :
      1. minuscules + strip
      2. ponctuation unicode → espaces (avant NFKD, pour ne pas perdre U+2010 etc.)
      3. NFKD (décompose les accents)
      4. ASCII encode/ignore (supprime les combining marks)
      5. caractères non-alphanumériques résiduels → espaces
      6. collapse espaces multiples
    """
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[\u0027\u2018\u2019\u02BC\u02EE\u0060\u00B4]", " ", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_name(text: str) -> str:
    """Normalise un nom de personne pour matching.

    Comme normalize_text mais ne conserve que les lettres et espaces
    (supprime les chiffres, tirets, etc.).
    """
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[\u0027\u2018\u2019\u02BC\u02EE\u0060\u00B4]", " ", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
