"""Toute écriture d'administration laisse une trace nominative.

Le dossier de sécurité énonce que les décisions humaines sont consignées. La règle qui décide lesquelles n'était écrite nulle part, et la table des événements couvrait les fusions et les structures sans couvrir les adresses, la configuration ni la plupart des modifications d'attributs.

La règle tient ici : **toute écriture de l'API d'administration est consignée**, la connexion et la déconnexion mises à part — elles ont leur propre plafonnement, et le middleware les laisse passer avant toute garde. Un point d'entrée qu'on ajoute sans trancher son cas fait échouer l'intégration.

Trois confrontations, qu'aucune ne suffit à elle seule :

1. le registre ci-dessous couvre la surface d'écriture du contrat OpenAPI, exactement — ni point d'entrée oublié, ni entrée devenue sans objet ;
2. chaque type d'événement qu'il nomme s'émet réellement quelque part dans la couche applicative, ce qui empêche de déclarer une trace qui n'existe pas ;
3. chaque type d'événement émis par la couche applicative est nommé par au moins un point d'entrée, ce qui signale un vocabulaire devenu mort.

L'énumération part du contrat publié, comme celle de la garde d'authentification : un point d'entrée soustrait au contrat échapperait aux deux.
"""

from __future__ import annotations

import re

import pytest

from infrastructure import PROJECT_ROOT
from interfaces.api.app import app

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

AUDITE: dict[tuple[str, str], str] = {
    ("POST", "/api/addresses/batch-country"): "address.batch_country_set",
    ("POST", "/api/addresses/batch-review"): "address.batch_link_reviewed",
    ("POST", "/api/addresses/{addr_id}/country"): "address.country_set",
    ("POST", "/api/addresses/{addr_id}/review"): "address.link_reviewed",
    ("POST", "/api/authorships/orphans/assign"): "authorship.assigned",
    ("POST", "/api/authorships/orphans/batch-assign"): "authorship.batch_assigned",
    ("PATCH", "/api/authorships/{authorship_id}/exclude"): "authorship.rejected",
    ("PUT", "/api/config/{key}"): "config.updated",
    ("PUT", "/api/journals/{journal_id}"): "journal.updated",
    ("POST", "/api/journals/{journal_id}/merge"): "journal.merged",
    ("POST", "/api/perimeters"): "perimeter.created",
    ("PUT", "/api/perimeters/{perimeter_id}"): "perimeter.updated",
    ("DELETE", "/api/perimeters/{perimeter_id}"): "perimeter.deleted",
    ("PATCH", "/api/persons/identifiers/{ident_id}/reassign"): "person_identifier.reassigned",
    ("PATCH", "/api/persons/identifiers/{ident_id}/status"): "person_identifier.status_changed",
    ("POST", "/api/persons/mark-distinct"): "person.marked_distinct",
    ("POST", "/api/persons/{person_id}/detach-authorships"): "authorship.rejected",
    ("POST", "/api/persons/{person_id}/identifiers"): "person_identifier.added",
    ("POST", "/api/persons/{person_id}/merge"): "person.merged",
    ("PATCH", "/api/persons/{person_id}/name"): "person.name_updated",
    ("PATCH", "/api/persons/{person_id}/name-forms/status"): "person_name_form.status_changed",
    ("PATCH", "/api/persons/{person_id}/reject"): "person.rejected",
    ("POST", "/api/publications/duplicates/mark-distinct"): "publication.marked_distinct",
    ("POST", "/api/publications/duplicates/merge"): "publication.merged",
    ("PUT", "/api/publishers/{publisher_id}"): "publisher.updated",
    ("POST", "/api/publishers/{publisher_id}/merge"): "publisher.merged",
    ("POST", "/api/structures"): "structure.created",
    ("PUT", "/api/structures/{structure_id}"): "structure.updated",
    ("DELETE", "/api/structures/{structure_id}"): "structure.deleted",
    ("POST", "/api/structures/name-forms"): "structure_name_form.created",
    ("PUT", "/api/structures/name-forms/{form_id}"): "structure_name_form.updated",
    ("DELETE", "/api/structures/name-forms/{form_id}"): "structure_name_form.deleted",
    ("POST", "/api/structures/relations"): "structure_relation.created",
    ("DELETE", "/api/structures/relations/{relation_id}"): "structure_relation.deleted",
}
"""Point d'entrée d'écriture → type d'événement qu'il émet."""

EXEMPTES: dict[tuple[str, str], str] = {
    ("POST", "/api/auth/login"): "Ouverture de session : plafonnée par adresse, hors garde.",
    ("POST", "/api/auth/logout"): "Fermeture de session : ne touche à aucune donnée.",
    ("POST", "/api/journals/{journal_id}/type-change-impact"): (
        "Calcule l'ampleur d'un changement de type sans l'appliquer : l'écriture est annulée "
        "avec le point de reprise qui l'enveloppe, et rien ne subsiste à consigner."
    ),
}
"""Point d'entrée d'écriture qui ne consigne rien, et la raison qui l'en dispense."""

_EMISSION = re.compile(r'emit_event\(\s*[^)]*?"([a-z_]+\.[a-z_]+)"', re.S)


def _surface_d_ecriture() -> set[tuple[str, str]]:
    """Points d'entrée d'écriture du contrat OpenAPI publié."""
    return {
        (methode.upper(), chemin)
        for chemin, operations in app.openapi()["paths"].items()
        for methode in operations
        if methode.upper() in WRITE_METHODS
    }


def _evenements_emis() -> set[str]:
    """Types d'événements que la couche applicative émet réellement."""
    emis: set[str] = set()
    for source in (PROJECT_ROOT / "application").rglob("*.py"):
        emis.update(_EMISSION.findall(source.read_text(encoding="utf-8")))
    return emis


def test_le_registre_couvre_la_surface_d_ecriture() -> None:
    declares = set(AUDITE) | set(EXEMPTES)
    surface = _surface_d_ecriture()

    non_tranches = surface - declares
    assert not non_tranches, (
        "Points d'entrée d'écriture dont le cas n'est pas tranché : "
        f"{sorted(non_tranches)}. Les consigner, ou les inscrire dans `EXEMPTES` avec la "
        "raison qui les en dispense."
    )


def test_le_registre_ne_nomme_aucun_point_d_entree_disparu() -> None:
    declares = set(AUDITE) | set(EXEMPTES)
    disparus = declares - _surface_d_ecriture()
    assert not disparus, f"Entrées sans point d'entrée correspondant : {sorted(disparus)}."


def test_aucun_point_d_entree_n_est_a_la_fois_audite_et_exempte() -> None:
    assert not set(AUDITE) & set(EXEMPTES)


@pytest.mark.parametrize(("point_d_entree", "evenement"), sorted(AUDITE.items()))
def test_l_evenement_declare_est_emis_par_le_code(
    point_d_entree: tuple[str, str], evenement: str
) -> None:
    assert evenement in _evenements_emis(), (
        f"{point_d_entree[0]} {point_d_entree[1]} déclare émettre `{evenement}`, qu'aucun appel "
        "de la couche applicative ne produit."
    )


CONSEQUENCES: dict[str, str] = {
    "journal.type_requalified": (
        "Ampleur de la requalification des publications, entraînée par un changement de type "
        "de revue : elle suit l'édition, personne ne la décide pour elle-même."
    ),
    "authorship.unrejected": (
        "Rejets levés par une attribution confirmée : ils tombent parce qu'on a attribué, "
        "et l'attribution porte déjà sa propre trace."
    ),
}
"""Types d'événements qui décrivent la conséquence d'une décision, non la décision."""


def test_aucun_evenement_emis_ne_reste_sans_point_d_entree() -> None:
    """Un type d'événement qu'aucun point d'entrée ne nomme, et qui ne suit aucune décision, est un vocabulaire devenu mort."""
    orphelins = _evenements_emis() - set(AUDITE.values()) - set(CONSEQUENCES)
    assert not orphelins, (
        f"Types d'événements émis sans point d'entrée déclaré : {sorted(orphelins)}. "
        "Les rattacher à un point d'entrée, ou les inscrire dans `CONSEQUENCES` avec ce qui "
        "les y range."
    )
