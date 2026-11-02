"""Lecture des payloads HAL par la normalisation : annexes, champs texte, domaines, métadonnées propres à HAL."""

import re
from collections.abc import Mapping, Sequence

from domain.source_records.source_extras import SourceExtra
from domain.subjects.subject import Subject, SubjectVocabulary
from domain.types import JsonValue, as_strs

# Types HAL d'une communication orale ou affichée : son annexe (diaporama, poster, résumé) donne accès à son contenu.
_COMMUNICATION_TYPES = frozenset({"COMM", "POSTER", "PRESCONF"})

# Code d'un domaine CCSD : des segments alphanumériques séparés par des points (`sdv.bbm.bm`), le tiret admis dans un segment (`info.info-oh`).
_DOMAIN_CODE = re.compile(r"^[a-z0-9]+(?:[-.][a-z0-9]+)*$")

# Annotation d'un libellé de domaine : `Informatique [cs]`, `Autre [cs.OH]`.
_DOMAIN_ANNOTATION = re.compile(r"\s*\[[^]]*\]")

# Libellés des feuilles fourre-tout du référentiel CCSD (`chim.othe`, `spi.other`…), qui réuniraient des feuilles sans rapport. Leur parent suffit.
_GENERIC_DOMAIN_LABELS = frozenset({"autre", "autres"})


def hal_annex(doc: Mapping[str, JsonValue]) -> str | None:
    """Renvoie l'adresse de la première annexe d'un dépôt HAL sans fichier principal, sinon `None`."""
    if hal_text_field(doc.get("fileMain_s")):
        return None
    annexes = as_strs(doc.get("fileAnnexes_s"))
    return annexes[0] if annexes else None


def communication_annex(doc: Mapping[str, JsonValue]) -> str | None:
    """Renvoie l'annexe d'un dépôt HAL sans fichier principal qui décrit une communication ou un poster (`hal_annex`), sinon `None`. Cette annexe tient lieu de fichier déposé."""
    if hal_text_field(doc.get("docType_s")) not in _COMMUNICATION_TYPES:
        return None
    return hal_annex(doc)


def hal_text_field(value: JsonValue) -> str | None:
    """Renvoie la chaîne d'un champ HAL, reçu en texte ou en liste de textes (convention Solr).

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
    """Renvoie les informations HAL sur la publication d'une communication et sur la licence du fichier déposé, ou `None` à défaut.

    `proceedings` reprend l'indicateur « avec actes » (`proceedings_s`, saisi par le déposant), `series` les collections (`serie_s`), `source_title` le titre de la source (`source_s`), souvent celui des actes. `licence` reprend l'URL de la licence du fichier déposé (`licence_s`). `annex_deposit` marque un dépôt réduit à des annexes (`hal_annex`).
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
    if hal_annex(doc):
        source_extras[SourceExtra.ANNEX_DEPOSIT] = True
    return source_extras or None


def hal_domain_subject(facet_entry: str) -> Subject | None:
    """Renvoie le domaine d'une entrée de `fr_domainAllCodeLabel_fs`, avec ses ancêtres.

    L'entrée contient le code du domaine et le chemin de ses libellés, de la racine au domaine : `sdv.bbm.bm_FacetSep_Sciences du Vivant [q-bio]/Biochimie, Biologie Moléculaire/Biologie moléculaire`. Chaque niveau a pour code un préfixe du code du domaine : `sdv`, `sdv.bbm`, `sdv.bbm.bm`.

    La profondeur du code borne le découpage du chemin : un libellé peut contenir des `/` (« Optique / photonique »). Les annotations entre crochets sont retirées. Un niveau au libellé vide ou générique est écarté avec ses descendants : son parent suffit.

    Une entrée dont le code n'a pas la forme attendue ne donne aucun domaine : dans quelques entrées du référentiel, un chemin de libellés tient lieu de code.
    """
    code, separator, path = facet_entry.partition("_FacetSep_")
    if not separator or not _DOMAIN_CODE.match(code):
        return None
    segments = code.split(".")
    subject: Subject | None = None
    for depth, raw_label in enumerate(path.split("/", len(segments) - 1), start=1):
        label = _DOMAIN_ANNOTATION.sub("", raw_label).strip()
        if not label or label.lower() in _GENERIC_DOMAIN_LABELS:
            break
        subject = Subject(SubjectVocabulary.HAL_DOMAIN, ".".join(segments[:depth]), label, subject)
    return subject
