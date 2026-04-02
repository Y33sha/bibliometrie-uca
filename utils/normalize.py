"""Fonctions de normalisation centralisées.

Toutes les normalisations textuelles du projet passent par ce module
afin d'éviter la duplication et les incohérences.

La normalisation Python est alignée sur la fonction SQL normalize_name_form() :
  lowercase → unaccent → tout sauf [a-z0-9] → espaces → collapse
"""

import re
import unicodedata


def normalize_text(text: str) -> str:
    """Normalise un texte pour comparaison / dédoublonnage / matching.

    Pipeline :
      1. minuscules + strip
      2. NFKD (décompose les accents)
      3. ASCII encode/ignore (supprime les combining marks)
      4. tout sauf [a-z0-9] → espaces
      5. collapse espaces multiples
    """
    if not text:
        return ""
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


# Alias — normalize_name est identique à normalize_text.
# Les deux noms sont conservés pour la lisibilité du code appelant.
normalize_name = normalize_text
