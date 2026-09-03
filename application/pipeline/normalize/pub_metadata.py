"""Métadonnées canoniques d'un document, entre la lecture d'un payload et son écriture.

Chaque source expose son propre schéma ; chaque normalizer en tire les mêmes champs, sous les mêmes types, avant de composer la ligne à écrire. Cet enregistrement est cette étape intermédiaire : ce que toutes les sources disent, une fois dépouillé de la façon dont chacune le dit.

Il remplace le dictionnaire qui tenait ce rôle. Ses clés étaient fixes et ses types connus, mais aucun des deux ne se disait : la lecture d'un champ supposait sa nature, et une source qui aurait posé un texte là où un entier est attendu ne se serait signalée qu'au moment de l'écriture en base.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class PublicationMetadata:
    """Champs canoniques tirés du payload d'une source.

    `embargo_until` ne vient que de HAL, seule source à publier la date de levée d'un embargo ; les autres la laissent absente.
    """

    title: str | None
    pub_year: int | None
    doc_type: str | None
    doi: str | None
    nnt: str | None
    oa_status: str | None
    journal_id: int | None
    container_title: str | None
    language: str | None
    embargo_until: date | None = None
