"""Lecture des enregistrements sources HAL par la normalisation : statut open access, champs texte, métadonnées propres à HAL."""

from collections.abc import Mapping, Sequence
from datetime import date

from domain.source_records.source_extras import SourceExtra
from domain.types import JsonValue, as_strs

# Archives ouvertes que HAL reconnaît dans `linkExtId_s`, tenues pour du green open access :
# - `arxiv` : serveur de preprints, entièrement en open access ;
# - `pubmedcentral` : archive biomédicale ; ses articles sont tous en lecture libre, sans être tous sous licence ouverte.
# `openaccess`, lien vers le DOI de l'éditeur, reste hors de la liste : HAL seul ne dit pas si l'accès est gold, hybrid ou bronze.
# `istex` aussi : la plateforme donne accès à des contenus payants. Ses documents ont en général un `fileMain_s`, tenu pour green.
GREEN_LINK_EXT_IDS = frozenset({"arxiv", "pubmedcentral"})


def derive_hal_oa_status(
    open_access_bool: bool | None,
    file_main: str | None,
    link_ext_id: str | None,
    embargo_until: date | None = None,
) -> str | None:
    """Statut open access d'un dépôt HAL.

    `openAccess_bool` vrai recouvre plusieurs cas, que départagent le fichier déposé, `linkExtId_s` et l'embargo :

    - fichier déposé sous embargo actif → `embargoed` ; une règle de correction de `oa_status` lève l'embargo à son échéance ;
    - fichier déposé → `green` ;
    - lien vers arXiv ou PubMed Central (`GREEN_LINK_EXT_IDS`) → `green` ;
    - lien `openaccess` vers le DOI de l'éditeur → `hybrid`, que `best_oa_status` remplace par `gold` si une autre source le dit ;
    - `openAccess_bool` faux → `closed` ;
    - `openAccess_bool` vrai sans autre signal, ou absent → `None` : OpenAlex et Unpaywall en décident.
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
    """Chaîne d'un champ HAL, qui arrive en texte ou en liste de textes (convention Solr).

    Les champs de l'index HAL sont multivalués par construction : un titre unique y arrive tout de même en liste. La première valeur fait foi.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        first = value[0] if value else None
        if first is None:
            return None
        return first if isinstance(first, str) else str(first)
    return str(value)


def extract_hal_source_extras(doc: Mapping[str, JsonValue]) -> dict[str, JsonValue] | None:
    """Ce que HAL dit de la publication d'une communication et de la licence du fichier déposé, ou `None` si le dépôt n'en dit rien.

    `proceedings` reprend l'indicateur « avec actes » (`proceedings_s`, saisi par le déposant), `series` les collections (`serie_s`), `source_title` le titre de la source (`source_s`), souvent celui des actes. `licence` reprend l'URL de la licence du fichier déposé (`licence_s`).
    """
    source_extras: dict[str, JsonValue] = {}
    proceedings = hal_text_field(doc.get("proceedings_s"))
    if proceedings in ("0", "1"):
        source_extras[SourceExtra.PROCEEDINGS] = proceedings == "1"
    series = [s.strip() for s in as_strs(doc.get("serie_s")) if s.strip()]
    if series:
        source_extras[SourceExtra.SERIES] = list(dict.fromkeys(series))
    if source_title := (hal_text_field(doc.get("source_s")) or "").strip():
        source_extras[SourceExtra.SOURCE_TITLE] = source_title
    if licence := (hal_text_field(doc.get("licence_s")) or "").strip():
        source_extras[SourceExtra.LICENCE] = licence
    return source_extras or None
