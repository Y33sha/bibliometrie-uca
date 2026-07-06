"""Neutralisation du bruit volatil du payload HAL pour la détection de changement.

Le TEI HAL (`label_xml`) porte dans son en-tête un horodatage de génération de
fiche (`<date when="…"/>`) réémis à chaque moissonnage, sans lien avec le contenu
bibliographique. Sur la population UCA, ce seul timestamp fait diverger le hash de
près des trois quarts des fiches HAL réextraites, déclenchant un UPSERT et une
re-normalisation complète pour un changement nul.

`strip_volatile_for_hash` renvoie une copie du payload où ces horodatages sont
neutralisés, à seule fin de calculer le hash de détection de changement. Le payload
réellement stocké (`staging.raw_data`, raw store) reste fidèle à la source : les
parsers qui lisent le TEI entier (date d'embargo `@notBefore`, ORCID/IdRef par
auteur) reçoivent le `label_xml` intact.

Seul l'attribut `@when` est neutralisé : les dates bibliographiques du TEI portent
d'autres attributs (`@notBefore`) ou sont du texte, et ne sont pas touchées. Une
modification réelle de `label_xml` (structure, embargo, identifiants) reste donc
bien détectée.
"""

import re

_WHEN_ATTR = re.compile(r'(\swhen=")[^"]*(")')


def strip_volatile_for_hash(raw_data: dict) -> dict:
    """Copie du payload HAL avec les horodatages de génération TEI neutralisés.

    Retourne `raw_data` inchangé (même objet) en l'absence de `label_xml`. Ne mute
    jamais l'entrée : la copie ne sert qu'au calcul du hash, pas au stockage.
    """
    label_xml = raw_data.get("label_xml")
    if not isinstance(label_xml, str):
        return raw_data
    return {**raw_data, "label_xml": _WHEN_ATTR.sub(r"\1\2", label_xml)}
