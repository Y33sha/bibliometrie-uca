# Source_authorships — cycle de vie

*À jour le 2026-09-06.*

Une signature est un auteur tel qu'**une** source le porte sur un document : une ligne par position d'auteur dans un [enregistrement source](source_publications.md). C'est la pièce qui relie tout le reste. Elle porte une identité d'auteur telle que la source la donne, reçoit une personne de la phase `persons`, puis un rattachement à l'[authorship](authorships.md) consolidée. Cinq phases du pipeline écrivent successivement dans sa ligne ; l'API n'y touche qu'en éditant les personnes.

Aucun objet de domaine ne lui correspond. Ses règles sont réparties selon ce qu'elles concernent : les rôles dans `domain/publications/authorship_roles.py`, l'extraction propre à chaque source dans `domain/sources/`, les identifiants dans `domain/persons/`.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `source_authorships` | La signature | `source`, `source_publication_id`, `identity_id`, `person_id`, `authorship_id`, `author_position`, `roles`, `is_corresponding`, `in_perimeter`, `resolution_mode`, `raw_author_name`, `countries_dirty` |
| `author_identifying_keys` | Identité d'auteur dédoublonnée | `author_name_normalized`, `person_identifiers`, `key_hash` (calculé, unique) |
| `source_authorship_addresses` | Lien entre une signature et ses adresses | `source_authorship_id`, `address_id` |
| `source_authorship_structures` | Vue matérialisée : signature ↔ structure du périmètre | dérivée des adresses, de leurs rattachements et du périmètre |
| `confirmed_authorships` | Signature épinglée par une décision humaine | `(source_authorship_id, person_id)` |

L'enregistrement source parent est décrit dans [source_publications](source_publications.md), l'authorship consolidée en aval dans [authorships](authorships.md), qui porte aussi `rejected_authorships`.

`identity_id` et `person_id` répondent à deux questions différentes. L'identité — nom normalisé et identifiants — est un fait que la source fournit, enregistré dès `normalize`. La personne est le résultat de la résolution, attribué plus tard par la phase `persons`. L'identité sert de clé pour charger les correspondances de la résolution, et à dédoublonner des signatures identiques.

## Écriture par le pipeline

1. **`normalize` — naissance.** Les signatures d'un enregistrement sont réécrites en bloc, avec leur source, leur position, leur rôle, le nom d'auteur brut et leur identité. L'identité est obtenue en dédoublonnant `author_identifying_keys` sur son empreinte calculée — nom normalisé et identifiants réunis ; celles que plus aucune signature ne porte sont supprimées en fin de phase. Les adresses sont créées au besoin et reliées à la signature. Un identifiant porté par deux positions ou plus du même enregistrement est suffixé `_dubious`, ce qui l'écarte de la résolution.
2. **`affiliations` — appartenance au périmètre.** `in_perimeter` devient vrai lorsqu'une adresse de la signature se résout en une structure du périmètre, le rattachement n'étant pas rejeté. La vue matérialisée `source_authorship_structures` est rafraîchie.
3. **`persons` — attribution d'une personne.** La cascade de résolution pose `person_id` et retient dans `resolution_mode` par quel moyen : identifiant, nom, ou report depuis une autre source. Les signatures épinglées à la main sont reposées en premier, et certaines remises à nul ciblées permettent à la phase de converger quel que soit l'ordre de traitement.
4. **`authorships` — rattachement à l'authorship consolidée.** `authorship_id` relie la signature au couple personne–publication qu'elle atteste.
5. **`countries` — pays.** `countries_dirty` déclenche le recalcul des pays de la signature depuis ses adresses.

## Écriture par l'API — édition manuelle

Aucune colonne structurelle n'est écrite par l'API. L'édition manuelle, décrite côté [personnes](persons.md), n'agit que sur le rattachement à une personne.

**Épingler une signature** l'inscrit dans `confirmed_authorships`. La décision porte sur cette signature précisément, et la phase `persons` la repose à chaque passage.

**Détacher une personne d'une publication** met à nul le `person_id` de **toutes** les signatures de ce couple, quelle que soit leur source, et inscrit la paire dans `rejected_authorships`.

**Fusionner deux personnes** repointe simplement le `person_id`.

## Lecture par le pipeline

- La phase `persons` lit les signatures du périmètre non encore rattachées, avec leur identité, leur nom normalisé et leurs rôles.
- La phase `authorships` consolide les couples personne–publication attestés par les signatures rattachées et en recompose les attributs.

## Lecture par l'API

Le détail d'une publication montre les **auteurs tels que chaque source les donne** : pour chaque source, les signatures de l'import le plus récent, avec leurs adresses, leurs structures et leurs rôles. La fiche personne, elle, s'appuie sur les authorships consolidées.
