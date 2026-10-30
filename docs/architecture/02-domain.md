# Domain — noyau métier

*À jour le 2026-10-26.*

Le noyau contient les règles métier. Il n'ouvre aucune connexion, ignore la base et le protocole HTTP, et importe seulement la bibliothèque standard. Un contrat d'import-linter le vérifie.

Les tables de chaque entité et leurs écritures sont décrites dans le [modèle de données](../donnees/01-vue-d-ensemble.md). Les docstrings de chaque module, publiées dans la référence du code, décrivent ses règles.

## Entités

| Classe | Module | Entité |
|---|---|---|
| `SourceRecord` | `domain/source_records/` | [enregistrement source](../donnees/02-sources.md) |
| `Publication` | `domain/publications/` | [publication](../donnees/03-publications.md) |
| `Person`, `IdentifierAttribution` | `domain/persons/` | [personne](../donnees/05-persons.md) et attribution d'un identifiant |
| `Structure` | `domain/structures/` | [structure](../donnees/06-structures.md) |
| `Perimeter` | `domain/perimeters/` | [périmètre](../donnees/06-structures.md#périmètres) |
| `Serial` | `domain/serials/` | [publication en série](../donnees/07-publishing.md#publications-en-série) |
| `Publisher` | `domain/publishers/` | [éditeur](../donnees/07-publishing.md#éditeurs) |

## Value objects

Les value objects sont immuables, et égaux quand leur contenu est égal.

- Identifiants de publication : `DOI`, `HALId`, `NNT`, `PMID`, `PMCID`, `ArxivId`
- Identifiants de personne : `ORCID`, `IdHAL`, `IdRef`, `HalPersonId`
- Identifiants de structure : `RorId`, `HalCollection`
- Formes de nom : `PersonNameForm`, `StructureNameForm`

## Chargement des entités

Une entité se charge en objet là où le traitement porte sur une entité à la fois. Les éditions de l'administration chargent, modifient et enregistrent l'entité éditée, par le `find_by_id` de son repository. `refresh_from_sources` recalcule une `Publication` depuis ses enregistrements sources.

Les traitements en masse du pipeline opèrent en SQL sur tout le corpus : résolution des affiliations, des publications et des personnes.

Une entité en référence une autre par son identifiant : `Serial.publisher_id`, `Perimeter.root_structure_ids`. Le chargement d'une entité s'arrête donc à ses propres value objects.
