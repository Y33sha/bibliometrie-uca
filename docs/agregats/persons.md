# Personnes — cycle de vie

*À jour le 2026-10-24.*

Une personne est un chercheur unifié à travers les sources : plusieurs contributions sources, venues de HAL, d'OpenAlex ou du Web of Science sous des graphies différentes, désignent la même personne. Contrairement aux [structures](structures.md), qui sont un référentiel saisi à la main, les personnes sont **construites par le pipeline** — la phase `persons` rattache chaque [contribution](contributions.md) à une personne et en crée au besoin — **puis corrigées à la main** : fusion, épinglage, rejet, exclusion. Le pipeline et l'interface d'administration écrivent donc tous deux.

`domain/persons/` contient les règles pures : la décision de la personne d'une contribution (`decide_group`), la comparaison des noms (`names_compatible`), et des types dédiés qui valident et normalisent chaque identifiant avant écriture.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `persons` | La personne unifiée | `last_name` / `first_name` et leurs formes normalisées, `exclusion` |
| `person_identifiers` | Attribution d'un identifiant externe à une personne | `person_id`, `id_type`, `id_value`, `source` (`manual` ou `auto`), `status`, unicité `(id_type, id_value)` |
| `person_name_forms` | Formes de nom sous lesquelles une personne apparaît | clé `(name_form, person_id)`, `sources`, `status` |
| `hr_records` | Fiche annuaire issue du système d'information | `person_id` unique, suppression refusée tant qu'elle existe, `email`, fonction, département, structure, dates |
| `distinct_persons` | Paires déclarées comme deux personnes différentes | `(person_id_a, person_id_b)`, avec `a < b` |
| `rejected_contributions` | Paires enregistrement source–personne écartées durablement | `(source_record_id, person_id)` |
| `confirmed_source_contributions` | Contributions sources épinglées à une personne | `(source_contribution_id, person_id)` |

`contributions.person_id` rattache une contribution à une personne, et `contributions.resolution_mode` dit comment.

## Écriture par le pipeline

`pipeline/transformation/persons/persons.py` exécute quatre tâches, chacune dans sa transaction. Le détail est dans la [phase persons](../pipeline/09-persons.md).

1. **Arbitrer les identifiants.** Un identifiant présent sous le nom d'une autre personne est neutralisé sur sa contribution source. Un identifiant attribué à une personne et présent dans les contributions d'une autre va à la personne qui a la majorité stricte des voix ; une attribution confirmée à la main n'est jamais transférée.
2. **Rattacher les contributions.** Les épinglages s'appliquent d'abord. Les contributions orphelines et celles de la file de redécision reçoivent leur personne par identifiant, puis par nom (`decide_group`). Les contributions du périmètre au nom inconnu fondent une personne.
3. **Régénérer les formes de nom.** Les formes calculées depuis l'état civil de la personne rejoignent celles observées dans ses contributions ; seules les différences sont écrites. Une forme calculée naît confirmée, une forme observée naît en attente, et les décisions humaines déjà prises sont conservées.
4. **Purger.** Les contributions rattachées par une forme de nom qui désigne plusieurs personnes entrent dans la file de redécision. Les personnes sans contribution du périmètre sont supprimées, sauf celles qui ont une fiche annuaire ou une décision humaine.

Les identifiants rencontrés sont attribués en attente de confirmation et marqués comme automatiques.

## Écriture par l'API — édition manuelle

Routeur `interfaces/api/routers/persons.py`, commandes dans `application/services/persons/commands.py`, adaptateur `PgPersonRepository`. Une commande vaut une transaction.

**Fusionner deux personnes** (`POST /api/persons/{id}/merge`). `merge_into` transfère les contributions, les rejets, les épinglages, les paires distinctes, les identifiants et les formes de nom, en réunissant leurs provenances, puis supprime la personne absorbée. Une contribution de l'absorbée dans une publication où la conservée en a déjà une perd sa personne. Sur une publication où la conservée réunit une contribution et un rejet, le rejet l'emporte. La personne qui a une fiche annuaire est toujours la conservée ; la fusion est refusée si les deux en ont une.

**Gérer les identifiants.** Ajout manuel, limité aux types publics ; confirmation, rejet ou retour en attente. Ajouter à une personne un identifiant rejeté chez une autre le lui réattribue, en attente ; un identifiant en attente ou confirmé chez une autre personne est refusé. Un rejet met en file de redécision les contributions que l'identifiant rattachait.

**Agir sur la personne.** Exclusion et retour en arrière, avec recalcul de l'appartenance des publications au périmètre ; renommage, qui régénère les formes calculées.

**Trancher une forme de nom.** La confirmer ou la rejeter ; un rejet met en file de redécision les contributions que cette forme rattachait.

**Détacher des contributions** (`POST /api/persons/{id}/detach-contributions`). Inscrit le rejet durable, retire la personne à ses contributions dans ces publications et nettoie les formes restées sans emploi.

**Déclarer deux personnes distinctes** inscrit la paire dans `distinct_persons`, ce qui l'écarte des files de doublons.

**Importer un ORCID authentifié** pose un statut que rien ne peut dégrader ensuite. L'import s'annonce par un réglage de session borné à sa transaction, seul contexte que le déclencheur Postgres accepte.

Aucun point d'entrée n'écrit `hr_records` : la fiche annuaire vient d'un import, et la fusion la laisse à la personne conservée.

## Lecture par le pipeline

Le rattachement des contributions lit tout en bloc (`pipeline/transformation/persons/groups.py` et `store.py`) :

- les correspondances identifiant → personne pour IdRef, ORCID et compte HAL ;
- les correspondances forme de nom → personnes, les décisions humaines sur les couples forme–personne, et les homonymes par nom de famille ;
- les personnes écartées de chaque publication ;
- les personnes déjà rattachées à une autre contribution de chaque publication.

## Lecture par l'API

Port `PersonsQueries`, adaptateurs dans `infrastructure/read_models/persons/`.

| Usage | Ce qui est servi |
|---|---|
| Fiche personne | Profil, thèses, adresses, tableau de bord et sujets, en croisant les personnes, la fiche annuaire, les identifiants, les contributions et les publications |
| Annuaire, listes, recherche, facettes, statistiques | Listes publiques et d'administration, filtrables par laboratoire |
| Files de doublons | Doublons par nom, conflits d'identifiant, contributions détachables, formes de nom ambiguës, candidates au partage d'une forme |

Toutes les files de doublons écartent les paires déclarées distinctes ; celle des doublons par nom écarte en outre les paires dont les deux personnes ont une fiche annuaire.
