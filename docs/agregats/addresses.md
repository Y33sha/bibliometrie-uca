# Adresses — cycle de vie

*À jour le 2026-09-04.*

Une adresse est le texte d'affiliation qu'une source attache à une signature : « Université Clermont Auvergne, CNRS, LMBP, F-63000 Clermont-Ferrand, France ». Le pipeline la résout en structures et lui attribue un pays. C'est de cette résolution que dépend l'appartenance d'une publication au périmètre de l'établissement.

Aucun objet de domaine ne lui correspond : elle vit comme texte normalisé et lignes SQL.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `addresses` | L'adresse normalisée | `raw_text`, `normalized_text`, `countries CHAR(2)[]`, `suggested_countries`, `countries_dirty`, `pub_count` |
| `address_structures` | Rattachement d'une adresse à une structure | `address_id`, `structure_id`, `matched_form_id` (NULL : confirmé à la main sans détection), `is_confirmed` (NULL en attente, TRUE confirmé, FALSE rejeté) |
| `source_authorship_addresses` | Table de liaison entre signature et adresse | `source_authorship_id`, `address_id` |
| `place_name_forms` | Formes de noms de lieux et code ISO correspondant | `iso_code`, `form_normalized`, `kind` (`country`, `institution`, `city`) |

Une adresse est unique par `md5(raw_text)`, un rattachement par `(address_id, structure_id)`. Deux vues matérialisées en dérivent, interrogées en SQL direct : `source_authorship_structures`, qui joint la table de liaison aux rattachements et aux structures du périmètre, et `authorship_structures`, qui en dérive à son tour.

## Écriture par le pipeline

Trois phases écrivent ces tables, dans cet ordre.

| Phase | Ce qu'elle écrit |
|---|---|
| `normalize` | `addresses`, `source_authorship_addresses` |
| `affiliations` | `address_structures` |
| `countries` | `addresses.countries`, `addresses.suggested_countries` |

### `normalize` — création des adresses

Les adresses extraites des sources sont dédoublonnées, insérées, puis reliées aux signatures par `application/pipeline/normalize/_authorships_batch.py`.

### `affiliations` — résolution en structures

`application/pipeline/affiliations/resolve_addresses.py` balaie les adresses et cherche dans leur texte normalisé les formes de noms déclarées par les structures, au moyen d'un automate Aho-Corasick.

La résolution compare l'état détecté à l'état enregistré et n'écrit que l'écart. Un rattachement posé ou confirmé à la main survit.

### `countries` — détection des pays

`application/pipeline/countries/phase.py` procède par trois moyens : le nom de pays en fin d'adresse, le nom de lieu (automate sur les formes `institution` et `city`, qui n'écrit `countries` que si un seul code ISO ressort), et enfin la suggestion, qui vise les adresses restées sans pays et alimente `suggested_countries`.

Toute écriture dans `countries` pose `addresses.countries_dirty`, ce qui déclenche la propagation ci-dessous.

## Propagation

Deux chaînes portent une écriture de ces tables jusqu'aux colonnes que consultent les pages : `address_structures` → vue matérialisée → `source_authorships.in_perimeter`, et `addresses.countries` → `source_publications.countries` → `publications.countries`.

**Appartenance au périmètre.** Troisième étape d'`affiliations` (`populate_affiliations.py`) : la vue matérialisée est rafraîchie, puis comparée aux signatures actuellement marquées `in_perimeter`. Seul l'écart est écrit. C'est là que les rattachements décident finalement du périmètre.

**Pays.** Étape finale de `countries` (`refresh_publication_countries.py`) : les signatures marquées sales — soit par `normalize` à leur création, soit par une adresse dont le pays vient de changer — voient leur publication source recalculée, puis la publication elle-même. Les deux marqueurs sont ensuite remis à zéro.

## Écriture par l'API — curation

Routeur `interfaces/api/routers/addresses.py`, commandes transactionnelles dans `application/services/addresses/`, adaptateur `PgAddressRepository`.

**Confirmer, rejeter ou réinitialiser un rattachement** (`POST /api/addresses/{id}/review` et `/batch-review`). Le service relève quelles adresses contribuent au périmètre avant l'opération, applique le changement, relève à nouveau après, et rend les seules adresses réellement touchées — ce qui écarte les opérations sans effet. Réinitialiser supprime le lien s'il est purement manuel, et rend son état d'attente à la détection qui subsiste. Quand quelque chose a changé, une tâche de fond recalcule `in_perimeter` sur les signatures concernées et le propage aux contributions.

**Forcer un pays** (`POST /api/addresses/{id}/country` et `/batch-country`), avec propagation aux adresses partageant le même texte normalisé. Une tâche de fond recalcule directement les pays des publications sources puis des publications, sans passer par les marqueurs du pipeline.

## Lecture par le pipeline

- **Comptage.** La phase `publications` recalcule `addresses.pub_count` en joignant la table de liaison aux signatures et à leurs publications sources.
- **Entrées d'appariement.** La résolution lit `addresses(id, normalized_text)` et `structure_name_forms` ; la détection de pays lit `addresses` et `place_name_forms`.

## Lecture par l'API

Routeur `interfaces/api/routers/addresses.py`, port `application/ports/read_models/addresses_queries.py`, adaptateur `PgAddressesQueries` — distinct des modules d'écriture du pipeline. Le référentiel des pays est servi à part, par `interfaces/api/routers/countries.py`.

| Point d'entrée | Ce qu'il sert |
|---|---|
| `GET /api/addresses` | Liste de curation pour une structure : adresses et leurs rattachements, filtrables sur la détection, la validation et le texte |
| `GET /api/addresses/{id}/publications` | Texte brut de l'adresse et publications qui la portent ; chaque rattachement expose son état de validation et s'il vient d'une détection |
| `GET /api/addresses/countries`, `/suggest-countries`, `/countries` | Facettes construites sur `countries`, `suggested_countries` et `pub_count` |
| `GET /api/addresses/stats` | Comptes par état de rattachement pour une structure |

## Points d'attention

**Le recalcul des pays des publications est déclenché depuis les adresses.** Il est cross-table par nature et vit dans `infrastructure/pipeline/countries.py` ; `PgAddressRepository` y délègue après une édition de pays.

**Les vues matérialisées peuvent être en retard.** La curation par l'API recalcule `in_perimeter` depuis les tables de base sans rafraîchir `source_authorship_structures` ni `authorship_structures` : elles attendent le prochain passage du pipeline.
