# Adresses — cycle de vie

*À jour le 2026-09-06.*

Une adresse est le texte d'affiliation qu'une source attache à une signature : « Université Clermont Auvergne, CNRS, LMBP, F-63000 Clermont-Ferrand, France ». Le pipeline la résout en structures et lui attribue un pays. Cette résolution est une des voies d'entrée d'une signature dans le périmètre de l'établissement.

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

Quatre phases écrivent ces tables, dans l'ordre où le pipeline les enchaîne.

| Phase | Ce qu'elle écrit |
|---|---|
| `normalize` | `addresses`, `source_authorship_addresses` |
| `affiliations` | `address_structures` |
| `publications` | `addresses.pub_count` |
| `countries` | `addresses.countries`, `addresses.suggested_countries` |

### `normalize` — création des adresses

Les adresses extraites des sources sont dédoublonnées, insérées, puis reliées aux signatures par `pipeline/ingestion/common/signatures.py`.

### `affiliations` — résolution en structures

`pipeline/transformation/structures/address_resolution.py` balaie les adresses et cherche dans leur texte normalisé les formes de noms déclarées par les structures, au moyen d'un automate Aho-Corasick.

La résolution compare l'état détecté à l'état enregistré et n'écrit que l'écart. Un rattachement posé ou confirmé à la main survit.

### `countries` — détection des pays

`pipeline/transformation/structures/countries/countries.py` détecte le pays, du signal le plus sûr au moins sûr :

- le nom de pays en fin d'adresse ;
- le nom de lieu, par automate sur les formes `institution` et `city` — le pays n'est écrit que si un seul code ISO ressort ;
- la suggestion, qui reprend les adresses restées sans pays et alimente `suggested_countries`.

Toute écriture dans `countries` pose `addresses.countries_dirty`, ce qui déclenche la propagation ci-dessous.

## Propagation

Deux chaînes portent une écriture de ces tables jusqu'aux colonnes que consultent les pages : `address_structures` → vue matérialisée → `source_authorships.perimeter_evidence`, et `addresses.countries` → `source_publications.countries` → `publications.countries`.

**Appartenance au périmètre.** Dernière étape d'`affiliations` (`populate`, dans `pipeline/transformation/structures/affiliations.py`) : la vue matérialisée est rafraîchie, puis les indices des signatures (`perimeter_evidence`) sont synchronisés sur elle. Seul l'écart est écrit.

**Pays.** Étape finale de `countries` (`refresh_publication_countries.py`) : les signatures marquées sales — soit par `normalize` à leur création, soit par une adresse dont le pays vient de changer — voient leur publication source recalculée, puis la publication elle-même. Les deux marqueurs sont ensuite remis à zéro.

## Écriture par l'API — édition manuelle

Routeur `interfaces/api/routers/addresses.py`, commandes transactionnelles dans `application/services/addresses/`, adaptateur `PgAddressRepository`.

**Confirmer, rejeter ou réinitialiser un rattachement** (`POST /api/addresses/{id}/review` et `/batch-review`). Le service relève quelles adresses contribuent au périmètre avant l'opération, applique le changement, relève à nouveau après, et rend les seules adresses réellement touchées — ce qui écarte les opérations sans effet. Réinitialiser supprime le lien s'il est purement manuel, et rend son état d'attente à la détection qui subsiste. Quand quelque chose a changé, une tâche de fond recalcule `in_perimeter` sur les signatures concernées et le propage aux contributions.

**Forcer un pays** (`POST /api/addresses/{id}/country` et `/batch-country`), avec propagation aux adresses partageant le même texte normalisé. Une tâche de fond recalcule directement les pays des publications sources puis des publications, sans passer par les marqueurs du pipeline.

## Lecture par le pipeline

La résolution lit `addresses(id, normalized_text)` et `structure_name_forms` ; la détection de pays lit `addresses` et `place_name_forms`. Le recompte de `pub_count`, en fin de phase `publications`, joint la table de liaison aux signatures et à leurs publications sources.

## Lecture par l'API

Routeur `interfaces/api/routers/addresses.py`, port `application/ports/read_models/addresses_queries.py`, adaptateur `PgAddressesQueries` — distinct des modules d'écriture du pipeline. Le référentiel des pays est servi à part, par `interfaces/api/routers/countries.py`.

| Point d'entrée | Ce qu'il sert |
|---|---|
| `GET /api/addresses` | Liste de révision pour une structure : adresses et leurs rattachements, filtrables sur la détection, la validation et le texte |
| `GET /api/addresses/{id}/publications` | Texte brut de l'adresse et publications qui la portent ; chaque rattachement expose son état de validation et s'il vient d'une détection |
| `GET /api/addresses/countries`, `/suggest-countries`, `/countries` | Facettes construites sur `countries`, `suggested_countries` et `pub_count` |
| `GET /api/addresses/stats` | Comptes par état de rattachement pour une structure |

## Points d'attention

**Le recalcul des pays des publications est déclenché depuis les adresses.** Il appartient au pipeline (`pipeline/transformation/structures/countries/countries_queries.py`), qui l'expose à l'API par le port `CountryRecompute` : une édition de pays d'adresse le lance en tâche de fond. L'ajout par lot et la recopie vers les adresses jumelles passent par `PgAddressRepository`.

**`authorship_structures` peut être en retard.** L'édition manuelle rafraîchit `source_authorship_structures` et recalcule les indices des signatures touchées, de leurs authorships et de leurs publications. `authorship_structures` attend le prochain passage du pipeline.
