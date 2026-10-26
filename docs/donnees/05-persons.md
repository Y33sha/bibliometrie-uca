# Personnes

*À jour le 2026-10-26.*

Une personne est un chercheur unifié à travers les sources. La phase `persons` rattache chaque [contribution](04-contributions.md) à une personne, et crée les personnes des contributions du périmètre. L'import du référentiel RH crée aussi des personnes. L'administration corrige le résultat, et le pipeline conserve ses décisions.

Une personne a au moins une contribution du périmètre, une fiche RH ou une décision humaine. La phase `persons` supprime les autres. Les co-auteurs extérieurs au périmètre n'ont donc pas de personne.

## Tables

Schéma PostgreSQL `persons`.

| Table | Contenu | Contrainte |
|---|---|---|
| `persons` | Nom et prénom, leurs formes normalisées, motif d'exclusion (`exclusion`) | |
| `person_identifiers` | Identifiants de la personne : [ORCID](../glossaire.md#orcid), [idHAL](../glossaire.md#idhal), [IdRef](../glossaire.md#idref), compte HAL. `source` vaut `auto` pour le pipeline, `manual` pour l'administration. `status` vaut `pending`, `confirmed`, `rejected` ou `authenticated` | Un identifiant appartient à une seule personne |
| `person_name_forms` | Formes de nom qui désignent la personne, avec leur `status` | Une forme peut désigner plusieurs personnes |
| `hr_records` | Fiche du référentiel RH ([import](../sources/10-imports-manuels.md#extraction-rh)) | Une fiche par personne. La fiche empêche la suppression de la personne |
| `distinct_persons` | Paires de personnes déclarées distinctes | |

## Décisions humaines

Deux tables contiennent les décisions de l'administration sur le rattachement des contributions. Les reconstructions de `contributions` les conservent.

| Table | Décision | Clé |
|---|---|---|
| `rejected_contributions` | La personne est écartée de la publication. Le rejet s'enregistre sur chaque enregistrement source de la publication | `(source_record_id, person_id)` |
| `confirmed_source_contributions` | La contribution source est épinglée à la personne | `source_contribution_id` |

## Écriture

**Pipeline.** La [phase `persons`](../pipeline/09-persons.md) arbitre les identifiants, rattache les contributions, crée les personnes, régénère les formes de nom et purge. Les identifiants lus dans les sources entrent avec le statut `pending`.

**Import RH** (`interfaces/cli/imports/import_persons.py`). Crée la personne et sa fiche RH.

**Import des ORCID authentifiés** (`interfaces/cli/maintenance/import_authenticated_orcids.py`). Seul cet import pose le statut `authenticated`. Ce statut est définitif. Un déclencheur PostgreSQL garantit ces deux règles.

**Administration** (`application/services/persons.py`) :

- **Fusion.** La personne absorbée est supprimée, et son identifiant redirige vers la personne conservée. La personne qui a une fiche RH est toujours conservée. Deux personnes qui ont chacune une fiche RH ne fusionnent pas.
- **Exclusion**, pour le motif `not_a_person` ou `out_of_perimeter`. L'appartenance de ses publications au périmètre est recalculée.
- **Renommage.** Les formes de nom de la personne sont régénérées.
- **Statut d'un identifiant ou d'une forme de nom.** Un rejet renvoie en redécision les contributions que l'identifiant ou la forme rattachait.
- **Détachement.** La personne est écartée des publications choisies (`rejected_contributions`).
- **Déclaration de deux personnes distinctes.** La paire sort des files de doublons.
