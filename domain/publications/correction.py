"""Correction des métadonnées canoniques.

Expose `effective_metadata`, fonction pure qui applique des règles de correction cross-table sur les valeurs d'une `SourcePublication`, en s'appuyant sur les entités référentielles fournies (journal, publisher).

Pourquoi pas dans `aggregation.py` : l'agrégation arbitre entre sources, la correction applique des règles cross-table (qui peuvent dépendre de `journal.journal_type`, de `publisher.publisher_type`, etc.). Les deux concerns sont séparés pour rester lisibles et testables indépendamment.

Pourquoi pas dans le normalizer (à l'ingestion) : `source_publications` est inviolable — trace fidèle de ce que chaque source a renvoyé. Toute mutation à l'ingestion fait perdre la réversibilité d'une règle. Les corrections s'appliquent sur le canonique via `refresh_from_sources` (qui ré-applique les règles à chaque appel) et sur la SP entrante au moment du matching dans `match_or_create_publications` (pour que les queries de dedup metadata matchent sur les valeurs corrigées).

Cascade interne (ordre déterministe, dicté par les dépendances entre champs) :
1. `journal_id` — une correction du journal change `journal.journal_type` / `journal.oa_model` / `journal.apc_amount`, qui sont les inputs des règles suivantes.
2. `doc_type` — consomme le journal corrigé, les helpers titre/DOI.
3. `oa_status` — consomme le journal corrigé.

Convention de nommage des règles (membres de `MetadataCorrectionRule`) : `INPUT_CONDITION_TO_OUTPUT`. Exemples : `JOURNAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER`, `TITLE_ERRATUM_TO_ERRATUM`, `THESES_FR_URL_TO_THESIS`. Le déclencheur en premier, l'effet ensuite.

Forme d'une règle individuelle : fonction pure `apply_<rule>(sp, ...) -> Correction[T] | None`. `None` quand la règle ne s'applique pas, sinon un `Correction` qui porte la valeur corrigée ET le nom de la règle. La cascade collecte les corrections et alimente l'audit `publications.meta.<field>_corrected_by`.

Audit : introduit à la 1re règle figée (cf. Phase 3 du chantier `METIER_metadata-correction`). Permet la lisibilité des corrections appliquées et le re-run ciblé par règle.

Phase 1 du chantier : aucune règle. Le module pose le contrat, les callers (`application.publications.refresh_from_sources`, `application.pipeline.publications.match_or_create_publications.process_document`) sont branchés pour ne pas avoir à modifier leur surface quand la 1re règle landera.
"""

from enum import StrEnum
from typing import NamedTuple

from domain.journals.journal import Journal
from domain.publishers.publisher import Publisher
from domain.source_publications.source_publication import SourcePublication


class MetadataCorrectionRule(StrEnum):
    """Identifiants des règles de correction figées. Une règle = un membre.

    Convention de nommage : `INPUT_CONDITION_TO_OUTPUT`. Le membre est inscrit dans `publications.meta.<field>_corrected_by` au moment où la règle est appliquée — c'est la trace d'audit consultable pour le re-run ciblé et l'affichage UI.

    Phase 1 : aucune règle figée. Les premiers membres arrivent en Phase 2 (theses.fr / dumas) et Phase 3 (1re règle admin-sensible).
    """


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
        """True si aucune correction n'est portée — la fast-path des callers en Phase 1 (stub) et pour la majorité des SPs en régime."""
        return self.journal_id is None and self.doc_type is None and self.oa_status is None


def effective_metadata(
    sp: SourcePublication,
    *,
    journal: Journal | None = None,
    publisher: Publisher | None = None,
) -> CorrectedFields:
    """Applique la cascade de corrections sur les champs d'une `SourcePublication`. Retourne un `CorrectedFields` (vide si aucune règle ne s'applique).

    Fonction pure : aucune I/O, aucun effet de bord. Les entités référentielles (`journal`, `publisher`) sont passées par le caller, qui est responsable de leur fetch en amont.

    Les paramètres `journal` et `publisher` sont keyword-only pour permettre l'ajout futur d'autres entités (`doi_prefix`, …) sans casser les callers.

    Phase 1 : stub no-op qui retourne toujours un `CorrectedFields` vide. Le branchement chez les callers est en place pour que l'arrivée de la 1re règle (Phase 2) ne demande aucune modification de surface.
    """
    return CorrectedFields()
