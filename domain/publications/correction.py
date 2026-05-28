"""Correction des métadonnées canoniques.

Expose `effective_metadata`, fonction pure qui applique des règles de correction sur les valeurs d'une publication source, à partir d'une vue de lecture `SourcePublicationWithJournalView` qui porte les champs de la SP **plus** des champs joints depuis `journals` (`journal_type`, `oa_model`, `apc_amount`). C'est cette vue qui rend la fonction capable d'appliquer aussi bien les règles SP-intrinsèques (URL) que les règles journal-dépendantes, sans threader de repo.

Distincte de l'agrégation (`aggregation.py` arbitre entre sources) et du normalizer (qui ne mute pas `source_publications`, trace inviolable des sources). Les corrections s'appliquent sur le canonique via `refresh_from_sources` et sur la SP entrante au moment du matching, pour que la dédup matche sur les valeurs corrigées.

Cascade déterministe, dans l'ordre des dépendances entre champs : `journal_id` (une correction du journal devient l'input des règles suivantes), puis `doc_type`, puis `oa_status`.

Chaque règle est une fonction pure renvoyant `Correction | None` : la valeur corrigée et le membre de `MetadataCorrectionRule` qui l'a produite. Le caller inscrit ce membre dans `publications.meta.<field>_corrected_by` pour tracer la correction.
"""

from enum import StrEnum
from typing import NamedTuple

from domain.source_publications.views import SourcePublicationWithJournalView


class MetadataCorrectionRule(StrEnum):
    """Identifiants des règles de correction figées. Une règle = un membre.

    Convention de nommage : `INPUT_CONDITION_TO_OUTPUT`. Le membre est inscrit dans `publications.meta.<field>_corrected_by` au moment où la règle est appliquée — c'est la trace d'audit consultable pour le re-run ciblé et l'affichage UI.
    """

    THESES_FR_URL_TO_THESIS = "THESES_FR_URL_TO_THESIS"
    DUMAS_URL_TO_MEMOIR = "DUMAS_URL_TO_MEMOIR"
    JOURNAL_TYPE_MEDIA_TO_MEDIA = "JOURNAL_TYPE_MEDIA_TO_MEDIA"


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


def _correct_doc_type(sp: SourcePublicationWithJournalView) -> Correction[str] | None:
    """Corrige le `doc_type` selon une cascade prioritaire.

    Ordre :
    1. theses.fr fait autorité sur les thèses françaises : toute URL theses.fr ⇒ `thesis`, quel que soit le `doc_type` brut (OpenAlex classe parfois ces thèses en `article` ou `dissertation`).
    2. DUMAS héberge des mémoires de master qu'OpenAlex classe à tort en `dissertation` : `dissertation` brut + URL dumas ⇒ `memoir`.
    3. Journal de type `media` ⇒ `media` : une publication rattachée à une revue typée media (typage manuel côté admin) est une intervention média.

    Les deux premières règles sont SP-intrinsèques (lisent `sp.urls`/`sp.doc_type`) ; la troisième est journal-dépendante (lit `sp.journal_type`, champ joint sur la vue). Renvoie `None` si aucune ne s'applique.
    """
    urls = sp.urls
    if any(_THESES_FR_URL_MARKER in (u or "") for u in urls):
        return Correction("thesis", MetadataCorrectionRule.THESES_FR_URL_TO_THESIS)
    if (sp.doc_type or "").lower() == "dissertation" and any(
        _DUMAS_URL_MARKER in (u or "") for u in urls
    ):
        return Correction("memoir", MetadataCorrectionRule.DUMAS_URL_TO_MEMOIR)
    if sp.journal_type == "media":
        return Correction("media", MetadataCorrectionRule.JOURNAL_TYPE_MEDIA_TO_MEDIA)
    return None


def effective_metadata(sp: SourcePublicationWithJournalView) -> CorrectedFields:
    """Applique la cascade de corrections sur les champs d'une `SourcePublicationWithJournalView`. Retourne un `CorrectedFields` (vide si aucune règle ne s'applique).

    Fonction pure : aucune I/O, aucun effet de bord. Les données journal/publisher consommées par les règles arrivent par la vue (champs joints à la lecture), pas via des entités passées en paramètre — c'est ce qui permet à la fonction de servir aussi bien la dédup (sur la SP entrante) que le refresh (sur les sources d'une publication).

    Cascade dans l'ordre des dépendances (`journal_id` → `doc_type` → `oa_status`) ; seul `doc_type` porte des règles à ce stade.
    """
    return CorrectedFields(doc_type=_correct_doc_type(sp))
