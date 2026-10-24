# Source_contributions — cycle de vie

*À jour le 2026-10-23.*

Une contribution source est un auteur tel qu'**une** source le porte sur un document : une ligne par position d'auteur dans un [enregistrement source](source_records.md). C'est la pièce qui relie tout le reste. Elle référence les informations du contributeur telles que la source les donne, reçoit une personne de la phase `persons`, puis un rattachement à la [contribution](contributions.md). Cinq phases du pipeline écrivent successivement dans sa ligne ; l'API n'y touche qu'en éditant les personnes.

Aucun objet de domaine ne lui correspond. Ses règles sont réparties selon ce qu'elles concernent : les rôles dans `domain/publications/contribution_roles.py`, l'extraction propre à chaque source dans `domain/sources/`, les identifiants dans `domain/persons/`.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `source_contributions` | La contribution source | `source`, `source_record_id`, `contributor_information_id`, `author_position`, `roles`, `is_corresponding`, `perimeter_evidence`, `in_perimeter`, `raw_author_name`, `countries`, `neutralized_identifiers` |
| `contributor_information` | Informations du contributeur, dédoublonnées | `author_name_normalized`, `identifiers`, `key_hash` (calculé, unique) |
| `source_contribution_addresses` | Lien entre une contribution source et ses adresses | `source_contribution_id`, `address_id` |
| `source_contribution_structures` | Vue matérialisée : contribution source ↔ structure du périmètre, avec l'indice | dérivée des adresses, des ROR, des structures HAL, des structures de thèse et du périmètre |
| `confirmed_source_contributions` | Contribution source épinglée par une décision humaine | `(source_contribution_id, person_id)` |

L'enregistrement source parent est décrit dans [source_records](source_records.md), la contribution consolidée en aval dans [contributions](contributions.md), qui décrit aussi `rejected_contributions`.

`contributor_information_id` et `person_id` répondent à deux questions différentes. Les informations du contributeur — nom normalisé et identifiants — sont un fait que la source fournit, enregistré dès `normalize`. La personne est le résultat de la résolution, attribué plus tard par la phase `persons`. Elles servent de clé pour charger les correspondances de la résolution, et à dédoublonner des contributions sources identiques.

## Écriture par le pipeline

1. **`normalize` — naissance.** Les contributions sources d'un enregistrement source sont réécrites en bloc, avec leur source, leur position, leur rôle, le nom d'auteur brut et leurs informations du contributeur. Celles-ci s'obtiennent en dédoublonnant `contributor_information` sur son empreinte calculée — nom normalisé et identifiants réunis ; les lignes qu'aucune contribution source ne référence sont supprimées en fin de phase. Les adresses sont créées au besoin et reliées à la contribution source, comme ses ROR et ses structures HAL. Un identifiant présent sur plusieurs contributions sources du même enregistrement source reste dans les informations du contributeur, et chacune de ces contributions sources l'inscrit dans `neutralized_identifiers` avec le motif `shared` : la résolution l'ignore pour elles.
2. **`affiliations` — appartenance au périmètre.** La vue matérialisée `source_contribution_structures` est rafraîchie. `perimeter_evidence` reçoit les indices de l'entrée de la contribution source dans le périmètre : structures atteintes dans la vue, identifiants d'une personne qui a une fiche RH. `in_perimeter` est vrai quand la contribution source a au moins un indice.
3. **`persons` — attribution d'une personne.** La cascade de résolution pose `person_id` et retient dans `resolution_mode` par quel moyen : identifiant, nom, ou report depuis une autre source. Les contributions sources épinglées à la main sont reposées en premier, et certaines remises à nul ciblées permettent à la phase de converger quel que soit l'ordre de traitement.
4. **`countries` — pays.** `countries` réunit les pays retenus des adresses de la contribution source, ceux de ses organisations ROR sans adresse et ceux de ses structures HAL. Il est recalculé pour une contribution source de la file `source_contribution_countries_queue`, ou liée à une adresse de `address_countries_queue`. `normalize` met en file les contributions sources qu'il crée ou réécrit. Un changement de pays dans les référentiels ROR et HAL met en file les contributions sources qui citent l'organisation ou la structure.

## Écriture par l'API — édition manuelle

Aucune colonne structurelle n'est écrite par l'API. L'édition manuelle, décrite côté [personnes](persons.md), n'agit que sur le rattachement à une personne.

**Épingler une contribution source** l'inscrit dans `confirmed_source_contributions`. La décision porte sur cette contribution source précisément, et la phase `persons` la repose à chaque passage.

**Détacher une personne d'une publication** met à nul le `person_id` de **toutes** les contributions sources de ce couple, quelle que soit leur source, et inscrit la paire dans `rejected_contributions`.

**Fusionner deux personnes** repointe simplement le `person_id`.

## Lecture par le pipeline

- La phase `persons` lit les contributions sources du périmètre non encore rattachées, avec leurs informations du contributeur, leur nom normalisé et leurs rôles.
- La phase `contributions` consolide les couples personne–publication attestés par les contributions sources rattachées et en recompose les attributs.

## Lecture par l'API

Le détail d'une publication montre les **auteurs tels que chaque source les donne** : pour chaque source, les contributions sources de l'import le plus récent, avec leurs adresses, leurs structures et leurs rôles. La fiche personne, elle, s'appuie sur les contributions consolidées.
