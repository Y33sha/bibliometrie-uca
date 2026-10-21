"""Lecture des enregistrements sources HAL par la normalisation : statut open access, champs texte, métadonnées propres à HAL."""

from collections.abc import Mapping, Sequence
from datetime import date

from domain.types import JsonValue, as_strs

# Repositories ouverts reconnus par HAL via `linkExtId_s` qu'on traite
# comme green OA (= dépôt en archive ouverte).
#
# - `arxiv` : preprint server fondateur, contenu intégralement en libre
#   accès.
# - `pubmedcentral` (PMC) : repository biomédical archivant les articles
#   accessibles librement (NIH-mandate + dépôts volontaires). Le contenu
#   n'est pas uniformément sous licence OA (certains articles "free to
#   read" sans droits de réutilisation, embargos), mais la lecture est
#   ouverte → traité comme green (= accès lecture libre via repo).
#
# Ne sont PAS dans cette liste :
# - `openaccess` : lien vers DOI éditeur, statut réel gold/hybrid/
#   bronze indéterminable depuis HAL seul.
# - `istex` : plateforme CNRS d'accès aux contenus payants, l'inclusion
#   ne garantit pas l'OA réel (et empiriquement ces docs ont aussi un
#   fileMain_s, donc capturés en green par la règle file_main).
GREEN_LINK_EXT_IDS = frozenset({"arxiv", "pubmedcentral"})


def derive_hal_oa_status(
    open_access_bool: bool | None,
    file_main: str | None,
    link_ext_id: str | None,
    embargo_until: date | None = None,
) -> str | None:
    """Mapping HAL → enum oa_status canonique.

    `openAccess_bool=true` recouvre plusieurs réalités ; l'arbitrage se fait sur `fileMain_s`, `linkExtId_s` et l'embargo :
      - file_main présent + embargo actif (`embargo_until` renseigné) → 'embargoed' (fichier déposé, accès légalement différé ; la levée à l'échéance est portée par une règle de correction `oa_status`, pas ici)
      - file_main présent → 'green' (dépôt effectif en HAL)
      - link_ext_id ∈ GREEN_LINK_EXT_IDS (arxiv, pubmedcentral) → 'green'
      - link_ext_id == 'openaccess' → 'hybrid' (lien vers le DOI éditeur, voie non nuancée ; défaut conservatif, arbitré vers 'gold' en aval par `best_oa_status` si une autre source le confirme)
      - open_access_bool=False → 'closed'
      - open_access_bool=True sans autre signal (istex, etc.) → None (délégation à OpenAlex/Unpaywall)
      - open_access_bool=None → None
    """
    if file_main and embargo_until is not None:
        return "embargoed"
    if file_main:
        return "green"
    if link_ext_id in GREEN_LINK_EXT_IDS:
        return "green"
    if link_ext_id == "openaccess":
        return "hybrid"
    if open_access_bool is None:
        return None
    if not open_access_bool:
        return "closed"
    return None


def hal_text_field(value: JsonValue) -> str | None:
    """Chaîne portée par un champ HAL, qui arrive en texte ou en liste de textes (convention Solr).

    Les champs de l'index HAL sont multivalués par construction : un titre unique y arrive tout de même en liste. La première valeur fait foi.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        premier = value[0] if value else None
        if premier is None:
            return None
        return premier if isinstance(premier, str) else str(premier)
    return str(value)


def extract_hal_source_extras(doc: Mapping[str, JsonValue]) -> dict[str, JsonValue] | None:
    """Ce que HAL dit de la publication d'une communication et de la licence du fichier déposé, ou `None` si le dépôt n'en dit rien.

    `proceedings` reprend l'indicateur « avec actes » (`proceedings_s`, saisi par le déposant), `series` les collections (`serie_s`), `source_title` le titre de la source (`source_s`), souvent celui des actes. `licence` reprend l'URL de la licence du fichier déposé (`licence_s`).
    """
    source_extras: dict[str, JsonValue] = {}
    proceedings = hal_text_field(doc.get("proceedings_s"))
    if proceedings in ("0", "1"):
        source_extras["proceedings"] = proceedings == "1"
    series = [s.strip() for s in as_strs(doc.get("serie_s")) if s.strip()]
    if series:
        source_extras["series"] = list(dict.fromkeys(series))
    if source_title := (hal_text_field(doc.get("source_s")) or "").strip():
        source_extras["source_title"] = source_title
    if licence := (hal_text_field(doc.get("licence_s")) or "").strip():
        source_extras["licence"] = licence
    return source_extras or None
