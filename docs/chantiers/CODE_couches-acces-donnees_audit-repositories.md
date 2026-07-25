# Audit des méthodes de repositories — couches d'accès aux données

Phase E du chantier `CODE_couches-acces-donnees` : recensement des méthodes de tous les repositories, avec leurs appelants réels et leur nature. ≈130 méthodes sur 11 repositories.

## Le pattern d'accès réel

Aucun repository n'est appelé directement par un router (à une exception, cf. plus bas). Le chemin d'écriture est uniforme :

    interfaces/api/routers/<X>  →  application/services/<X>/commands.py  (frontière transactionnelle)
                                →  application/services/<X>/core.py       (logique + invariants)
                                →  repository.<méthode>()                 (persistance fine)

Les lectures de l'API passent par des objets `Queries` séparés (`PersonsQueries`, `StructuresQueries`…), **pas** par les repositories. Le pipeline, lui, atteint les repositories soit via ces mêmes services, soit en direct depuis `application/pipeline/`.

Conséquence : **les invariants d'agrégat vivent dans les services `application/`, pas dans les repositories.** Les méthodes de repository sont des briques de persistance (souvent des écritures plates `RETURNING`), et l'« hydratation d'agrégat » est vestigiale — `find_by_id` existe sur la plupart des repositories mais reste inutilisé en production (structure, perimeter, publication). Le motif effectif est **command-service + data-mapper + read-models**, pas l'agrégat-DDD au sens strict. Ce qui confirme, mesuré, l'intuition « repository = fiction » à l'origine du chantier.

## Trois consommateurs, pas deux

Le barème P/A/C supposait deux mondes (pipeline vs admin/API). L'audit en révèle **trois**, et c'est le troisième qui manquait :

### 1. Accès purement pipeline → descendent dans `pipeline/`

Méthodes dont l'unique appelant est `application/pipeline/` :

- **`doi_prefix_repository` en entier** (7 méthodes) — `resolve_ra` et `publishers_journals`. Le repository descend en bloc.
- **`journal_repository`, bloc find-or-create + enrichissement** : `add_journal_name_form`, `find_journal_by_name_form`, `find_journal_by_openalex_id`, `find_journal_by_issn_any`, `find_journals_of_unknown_type`, `find_journal_issn_index`, `enrich_journal`, `create_journal`, `update_journal_apc`, `update_journal_doaj`, `reset_is_in_doaj`, `doaj_last_import_at`.
- **`publisher_repository`, bloc find-or-create** : `add_publisher_name_form`, `find_publisher_by_name_form`, `find_publisher_by_openalex_id`, `set_publisher_openalex_id_if_missing`, `create_publisher`, `match_or_create_by_name_form`.
- **`publication_repository`** : `update_oa_status`, `mark_unpaywall_checked` (phase oa_status), `create` (phase de réconciliation).
- **`authorship_repository`** : `enforce_confirmed_authorships` (phase persons).

### 2. Commandes d'agrégat, pilotées admin/API → restent côté commande

- **Fusions** : `journal.merge_journal_into`, `publisher.merge_publisher_into`, `publication.merge_into`, `person.merge_into` (+ `journal.find_shared_title_journal_pairs`, détection de conflit).
- **Curation de structures** : tout `structure_repository` (create/update/delete × structure/relation/forme, invariants ROR/cycle/short-form, audités).
- **Édition d'agrégat** : `publication.save`/`delete`, `person` (identifiants, formes de nom), `journal.update_journal_fields` / `publisher.update_publisher_fields` (via service).
- **Sous-opérations atomiques de trois commandes admin** (`reject_pair`, `assign_orphan_authorship`, `update_name_form_status`) : le gros d'`authorship_repository` (`reject_authorship`, `pin/unpin`, `assign_orphan_source_authorship`, `insert_authorship_if_missing`, `null_person_id_for_name_form`, `delete_orphan_authorships_for_person`…).

### 3. Déclenché par l'humain, ensembliste — deux natures à ne pas confondre

Des opérations ensemblistes dont l'appelant réel est l'admin/API ou une tâche de fond post-review, jamais une phase du pipeline. Leur *forme* (recompute en masse) ne dit rien de leur *nature* : deux cas opposés s'y cachent.

**3a — L'admin rejoue une chaîne d'ETL.** Le travail ensembliste réexécute, hors run, une logique dont le pipeline est propriétaire.

- `address_repository`, bloc pays : `propagate_countries_across_similar_addresses`, `refresh_source_publications_countries`, `refresh_publications_countries_for_addresses` (ces deux dernières, simples façades sur `queries/pipeline/countries.py`), `batch_add_country_*`. L'admin pose un pays d'adresse, puis rejoue la propagation adresse → publications.
- `authorship_repository`, bloc batch-assign : `create_authorships_from_sources`, `link_source_authorships_to_authorships`, `assign_orphan_source_authorships_to_person`, `recompute_in_perimeter_on_source_authorships`, `propagate_in_perimeter_to_authorships`. La décision d'assigner est une curation admin, mais le recompute qui suit rejoue la construction d'authorships et la propagation d'affiliation du pipeline.

Cible : le SQL ensembliste a sa maison dans le gateway pipeline ; l'admin l'appelle, il ne s'en fabrique pas une copie côté repository.

**3b — L'admin maintient une table dérivée du domaine.** L'opération recalcule un invariant métier matérialisé, directement depuis des tables métier de base. Le domaine en est propriétaire.

- `perimeter.refresh_structures` : recompute `perimeter_structures`, la clôture récursive (`est_tutelle_de`) des racines de chaque périmètre. L'appartenance d'une structure à un périmètre est un concept métier ; sa maintenance après édition d'une racine, d'une relation de tutelle ou suppression d'une structure est un invariant du write-side, pas un ETL.

Cible : la surface autoritative est celle du domaine (les command handlers). Le refresh que le pipeline joue en tête de run est une redondance défensive — un filet contre les mutations hors write-side (migrations, imports) — superflue dès lors que toute écriture concernée passe par le domaine.

La forme SQL ne classe donc pas : c'est la sémantique — rejouer un ETL (3a) vs tenir un invariant du domaine (3b) — qui décide.

### 4. Briques partagées pipeline + admin

`person_repository` : `create`, `insert_identifier`, `add_name_form`, `refresh_name_forms`, `find_identifier` sont co-consommées par la cascade de matching (`pipeline/persons/`) **et** par les commandes API. Elles ne se rangent pas d'un côté ou de l'autre.

### 5. Tables techniques

`config.update_config_value` (clé/valeur, pas d'agrégat) et `audit.record_event` (append de journal transverse, via `emit_event`). Ni pipeline, ni agrégat : des gateways techniques.

## Constats à traiter (quick-wins et pièges)

- **Code mort — vérifié et retiré** : `publication.find_by_doi` (+ la dataclass `PubByDoi`), `authorship.unlink_authorship` (repo + port + service `persons.core.unlink_authorship` + son test), `person.remove_person_source`, `person.is_ambiguous`. Deux méthodes restent : `structure.find_by_id` et `perimeter.find_by_id` sont mortes en production mais servent de read-back aux tests — leur retrait suppose de recâbler ces tests sur le read-model, à traiter à part. `publisher.find_publisher_by_name_form` n'est finalement pas morte (appelée en interne par `match_or_create_by_name_form`).
- **Collisions de noms pipeline/admin** : `link_source_authorships_to_authorships` existe comme méthode d'`AuthorshipRepository` (admin) *et* comme fonction d'`AuthorshipBuildQueries` (`queries/pipeline/authorships/build.py`, pipeline) — opérations distinctes. Idem `get_name_form` (repo structure vs `StructuresQueries`).
- **`perimeter_structures`, deux ports pour une opération** : la clôture s'écrit une seule fois (`refresh_perimeter_structures`, `queries/perimeter.py`), mais elle est exposée par deux ports — `PerimeterStructuresQueries` (pipeline) et `PerimeterRepository.refresh_structures` (admin) — plus une fonction libre. La surface autoritative est celle du domaine (l'admin tient l'invariant à chaque édition) ; la copie que le pipeline joue en tête de run est un filet défensif, probablement superflu en pratique.
- **Le seul contournement API→repo direct** : `interfaces/api/routers/journals.py:185` appelle `update_journal_fields` sans passer par le service (aperçu d'impact dans un SAVEPOINT annulé). Cas particulier, mais c'est l'unique « flat CRUD API » au sens strict.

## Chantiers qui en sortent

1. **Descente pipeline.** `doi_prefix_repository` en bloc → `pipeline/`. `journal`/`publisher` **se scindent** : bloc find-or-create + enrichissement → `pipeline/`, fusion → repository mince. `publication.update_oa_status`/`mark_unpaywall_checked`/`create`, `authorship.enforce_confirmed_authorships` → `pipeline/`.
2. **Ensembliste déclenché par l'humain — deux traitements.** *L'admin rejoue un ETL* (pays, batch-assign d'authorships) : le SQL a sa maison dans le gateway pipeline, l'admin l'appelle. *L'admin maintient une table dérivée du domaine* (clôture de périmètre) : le domaine possède l'opération, la copie pipeline est un filet à retirer une fois la discipline d'écriture garantie.
3. **Ménage.** Retirer le code mort ; désambiguïser les homonymes ; dédoublonner la matérialisation `perimeter_structures` ; router `journals.py:185` par le service.
4. **Nommage.** Assumer que ces « repositories » sont, pour l'essentiel, des data-mappers sous des command-services — le vocabulaire cible (`repositories/` pour les vrais agrégats curés, gateways pour le reste) découle de là.
