"""Correction des métadonnées canoniques.

Expose `effective_metadata`, fonction pure qui applique des règles de correction sur les valeurs d'une `SourcePublication`, à partir de la SP elle-même et d'entités référentielles fournies par le caller (journal, publisher).

Distincte de l'agrégation (`aggregation.py` arbitre entre sources) et du normalizer (qui ne mute pas `source_publications`, trace inviolable des sources). Les corrections s'appliquent sur le canonique via `refresh_from_sources` et sur la SP entrante au moment du matching, pour que la dédup matche sur les valeurs corrigées.

Cascade déterministe, dans l'ordre des dépendances entre champs : `journal_id` (une correction du journal devient l'input des règles suivantes), puis `doc_type`, puis `oa_status`.

Chaque règle est une fonction pure renvoyant `Correction | None` : la valeur corrigée et le membre de `MetadataCorrectionRule` qui l'a produite. Le caller inscrit ce membre dans `publications.meta.<field>_corrected_by` pour tracer la correction.
"""

from enum import StrEnum
from typing import NamedTuple

from domain.journals.journal import Journal
from domain.publishers.publisher import Publisher
from domain.source_publications.source_publication import SourcePublication


class MetadataCorrectionRule(StrEnum):
    """Identifiants des règles de correction figées. Une règle = un membre.

    Convention de nommage : `INPUT_CONDITION_TO_OUTPUT`. Le membre est inscrit dans `publications.meta.<field>_corrected_by` au moment où la règle est appliquée — c'est la trace d'audit consultable pour le re-run ciblé et l'affichage UI.
    """

    THESES_FR_URL_TO_THESIS = "THESES_FR_URL_TO_THESIS"
    DUMAS_URL_TO_MEMOIR = "DUMAS_URL_TO_MEMOIR"


class Correction[T](NamedTuple):
    """Une valeur corrigée + la règle qui l'a produite."""

    value: T
    rule: MetadataCorrectionRule


class CorrectedFields(NamedTuple):
    """Résultat de `effective_metadata` : pour chaque champ, soit `None` (pas de correction), soit un `Correction` (valeur corrigée + règle d'origine).

    Ordre des champs aligné sur la cascade interne (journal_id d'abord, oa_status en dernier).
    """

    journal_id: Correction[int] | None = None
    doc_type: Correction[str] | None = None
    oa_status: Correction[str] | None = None

    def is_empty(self) -> bool:
        """True si aucune correction n'est portée — la fast-path des callers pour la majorité des SPs en régime."""
        return self.journal_id is None and self.doc_type is None and self.oa_status is None


# ── Règles individuelles ───────────────────────────────────────────

_THESES_FR_URL_MARKER = "theses.fr/"
_DUMAS_URL_MARKER = "dumas."


def _correct_doc_type(sp: SourcePublication) -> Correction[str] | None:
    """Corrige le `doc_type` à partir de la source réelle du document, détectée sur ses URLs.

    Deux règles, dans l'ordre d'autorité :
    1. theses.fr fait autorité sur les thèses françaises : toute URL theses.fr ⇒ `thesis`, quel que soit le `doc_type` brut (OpenAlex classe parfois ces thèses en `article` ou `dissertation`).
    2. DUMAS héberge des mémoires de master qu'OpenAlex classe à tort en `dissertation` : `dissertation` brut + URL dumas ⇒ `memoir`.

    Le déclencheur est l'URL (pas la source de la SP) : les règles restent source-agnostiques, conformément au contrat d'`effective_metadata`. Renvoie `None` si aucune ne s'applique.
    """
    urls = sp.urls
    if any(_THESES_FR_URL_MARKER in (u or "") for u in urls):
        return Correction("thesis", MetadataCorrectionRule.THESES_FR_URL_TO_THESIS)
    if (sp.doc_type or "").lower() == "dissertation" and any(
        _DUMAS_URL_MARKER in (u or "") for u in urls
    ):
        return Correction("memoir", MetadataCorrectionRule.DUMAS_URL_TO_MEMOIR)
    return None


def effective_metadata(
    sp: SourcePublication,
    *,
    journal: Journal | None = None,
    publisher: Publisher | None = None,
) -> CorrectedFields:
    """Applique la cascade de corrections sur les champs d'une `SourcePublication`. Retourne un `CorrectedFields` (vide si aucune règle ne s'applique).

    Fonction pure : aucune I/O, aucun effet de bord. Les entités référentielles (`journal`, `publisher`) sont passées par le caller, qui est responsable de leur fetch en amont.

    Les paramètres `journal` et `publisher` sont keyword-only pour permettre l'ajout futur d'autres entités (`doi_prefix`, …) sans casser les callers.

    Cascade dans l'ordre des dépendances (`journal_id` → `doc_type` → `oa_status`) ; seul `doc_type` porte des règles à ce stade.
    """
    return CorrectedFields(doc_type=_correct_doc_type(sp))
