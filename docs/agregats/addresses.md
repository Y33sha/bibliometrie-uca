# Adresses — cycle de vie

*À jour le 2026-10-23.*

Une adresse est le texte d'affiliation qu'une source attache à une contribution source : « Université Clermont Auvergne, CNRS, LMBP, F-63000 Clermont-Ferrand, France ». Le pipeline la résout en structures et lui attribue un pays. Cette résolution est une des voies d'entrée d'une contribution source dans le périmètre de l'établissement.

Aucun objet de domaine ne lui correspond : elle vit comme texte normalisé et lignes SQL.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `addresses` | L'adresse normalisée | `raw_text`, `normalized_text`, `countries CHAR(2)[]`, `publication_count` |
| `address_country_candidates` | Pays proposé pour une adresse par un moyen de détection | `address_id`, `country_code`, `method` |
| `address_structures` | Rattachement d'une adresse à une structure | `address_id`, `structure_id`, `matched_form_id` (NULL : confirmé à la main sans détection), `is_confirmed` (NULL en attente, TRUE confirmé, FALSE rejeté) |
| `source_contribution_addresses` | Table de liaison entre contribution source et adresse | `source_contribution_id`, `address_id` |
| `place_name_forms` | Formes de noms de lieux et code ISO correspondant | `iso_code`, `form_normalized`, `kind` (`country`, `institution`, `city`) |

Une adresse est unique par `md5(normalized_text)`, un rattachement par `(address_id, structure_id)`, un candidat par `(address_id, country_code, method)`. La vue matérialisée `source_contribution_structures` joint la table de liaison aux rattachements et aux structures du périmètre. La vue matérialisée `contribution_structures` en dérive.

## Écriture par le pipeline

| Phase | Ce qu'elle écrit |
|---|---|
| `normalize` | `addresses`, `source_contribution_addresses`, candidats des sources |
| `affiliations` | `address_structures` |
| `publications` | `addresses.publication_count` |
| `countries` | candidats des autres moyens, `addresses.countries` |

### `normalize` — création des adresses

`pipeline/ingestion/common/source_contributions.py` normalise chaque texte (`normalize_text`). Un texte rejoint l'adresse de même forme normalisée. Un texte de forme vide est écarté. Une adresse créée entre dans la file `address_candidates_queue`. Les pays que la source donne pour une affiliation deviennent des candidats du moyen de la source (`source_openalex`, `source_scanr`).

### `affiliations` — résolution en structures

`pipeline/transformation/structures/address_resolution.py` balaie les adresses et cherche dans leur texte normalisé les formes de noms déclarées par les structures, au moyen d'un automate Aho-Corasick.

La résolution compare l'état détecté à l'état enregistré et n'écrit que l'écart. Un rattachement posé ou confirmé à la main survit.

### `countries` — pays des adresses

Tâches de `pipeline/transformation/countries/countries.py` :

- `countries.detect` : nom de pays en fin d'adresse, noms d'institutions et de villes. Pour une adresse de la file `address_candidates_queue`, chaque moyen recalcule ses candidats ;
- `countries.resolve` : la fonction de préséance du domaine (`domain/country_detection.py`) compose `addresses.countries` à partir des candidats, pour les adresses de `address_candidates_queue`. Les adresses dont le pays change entrent dans `address_countries_queue`.

Après une modification de `place_name_forms`, `interfaces/cli/maintenance/redetect_address_countries.py` marque toutes les adresses.

## Propagation

**Appartenance au périmètre** : `address_structures` → vue matérialisée → `source_contributions.perimeter_evidence`. Dernière étape d'`affiliations` (`populate`, dans `pipeline/transformation/structures/affiliations.py`) : la vue matérialisée est rafraîchie, puis les indices des contributions sources (`perimeter_evidence`) sont synchronisés sur elle. Seul l'écart est écrit.

**Pays** : `addresses.countries` → `source_contributions.countries` → `source_records.countries` → `publications.countries`. Étape finale de `countries` (`refresh_publication_countries.py`). Le pays d'une contribution source réunit les pays retenus de ses adresses, ceux de ses organisations ROR sans adresse et ceux de ses structures HAL. Sont recalculées les contributions sources de la file `source_contribution_countries_queue` (marquées par `normalize`, ou par un changement de pays dans les référentiels ROR et HAL) et celles d'une adresse de `address_countries_queue`. Suivent leurs enregistrements sources, puis les publications. Les marquages relevés sont ensuite supprimés des deux files.

## Écriture par l'API — édition manuelle

Routeur `interfaces/api/routers/addresses.py`, commandes transactionnelles dans `application/services/addresses/`, adaptateur `PgAddressRepository`.

**Confirmer, rejeter ou réinitialiser un rattachement** (`POST /api/addresses/{id}/review` et `/batch-review`). Le service relève quelles adresses contribuent au périmètre avant l'opération, applique le changement, relève à nouveau après, et rend les seules adresses réellement touchées — ce qui écarte les opérations sans effet. Réinitialiser supprime le lien s'il est purement manuel, et rend son état d'attente à la détection qui subsiste. Quand quelque chose a changé, une tâche de fond recalcule `in_perimeter` sur les contributions sources concernées et le propage aux contributions.

**Saisir un pays** (`POST /api/addresses/{id}/country` et `/batch-country`). La saisie s'enregistre en candidats `manual`, qui l'emportent sur les autres moyens, et l'adresse est résolue aussitôt. L'adresse reste dans `address_candidates_queue` : le run suivant refait sa détection. Une saisie vide retire les candidats `manual`. Une tâche de fond recalcule les pays des contributions sources, des enregistrements sources et des publications de l'adresse.

## Lecture par le pipeline

La résolution lit `addresses(id, normalized_text)` et `structure_name_forms`. La détection de pays lit `addresses` et `place_name_forms`. Le recompte de `publication_count`, en fin de phase `publications`, joint la table de liaison aux contributions sources et à leurs enregistrements sources.

## Lecture par l'API

Routeur `interfaces/api/routers/addresses.py`, Lecture `infrastructure/read_models/addresses/`, classe `AddressesQueries` — distinct des modules d'écriture du pipeline. Le référentiel des pays est servi à part, par `interfaces/api/routers/countries.py`.

| Point d'entrée | Ce qu'il sert |
|---|---|
| `GET /api/addresses` | Liste de révision pour une structure : adresses et leurs rattachements, filtrables sur la détection, la validation et le texte |
| `GET /api/addresses/{id}/publications` | Texte brut de l'adresse et publications qui la citent ; chaque rattachement expose son état de validation et s'il vient d'une détection |
| `GET /api/addresses/countries` | Liste d'attribution des pays : pays retenus, pays trouvés par chaque moyen, facette des pays retenus |
| `GET /api/addresses/stats` | Comptes par état de rattachement pour une structure |

Le filtre des adresses par pays est un seul fragment SQL (`address_country_conditions`, dans `infrastructure/sql_fragments.py`), partagé par la liste d'attribution et l'ajout de pays par lot.

## Points d'attention

**Le recalcul des pays des publications est déclenché depuis les adresses.** Il appartient au pipeline (`pipeline/transformation/countries/refresh_publication_countries.py`), qui l'expose à l'API par le port `CountryRecompute` : une saisie de pays d'adresse le lance en tâche de fond.

**`contribution_structures` peut être en retard.** L'édition manuelle rafraîchit `source_contribution_structures` et recalcule les indices des contributions sources touchées, de leurs contributions et de leurs publications. `contribution_structures` attend le prochain passage du pipeline.
