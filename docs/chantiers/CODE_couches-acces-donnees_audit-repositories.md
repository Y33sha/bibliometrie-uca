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

### 3. Bulk déclenché par l'humain — la catégorie que le barème ratait

Opérations **ensemblistes** (elles *ressemblent* à du pipeline) mais dont l'appelant réel est l'**admin/API** ou une **tâche de fond post-review**, jamais une phase du pipeline :

- **`address_repository`, bloc pays** : `batch_add_country_by_ids`, `batch_add_country_by_filter`, `propagate_countries_across_similar_addresses`, `refresh_source_publications_countries`, `refresh_publications_countries_for_addresses`. Les `refresh_*` sont même de simples façades sur `queries/pipeline/countries.py`. Déclenché par l'attribution manuelle d'un pays + sa propagation en tâche de fond.
- **`authorship_repository`, bloc batch-assign** : `create_authorships_from_sources`, `link_source_authorships_to_authorships` (pluriel), `assign_orphan_source_authorships_to_person`, `recompute_in_perimeter_on_source_authorships`, `propagate_in_perimeter_to_authorships`. Déclenché par l'assignation par lot depuis l'UI admin + la tâche de fond de propagation d'affiliation.
- **`perimeter.refresh_structures`** : matérialise `perimeter_structures`, appelé par la couche command API.

Ces méthodes n'ont de maison évidente ni en `pipeline/` (ce ne sont pas des phases) ni en « commande d'agrégat » (elles sont ensemblistes, multi-agrégats). Il leur faut une règle propre — c'est le vrai point ouvert de la phase E.

### 4. Briques partagées pipeline + admin

`person_repository` : `create`, `insert_identifier`, `add_name_form`, `refresh_name_forms`, `find_identifier` sont co-consommées par la cascade de matching (`pipeline/persons/`) **et** par les commandes API. Elles ne se rangent pas d'un côté ou de l'autre.

### 5. Tables techniques

`config.update_config_value` (clé/valeur, pas d'agrégat) et `audit.record_event` (append de journal transverse, via `emit_event`). Ni pipeline, ni agrégat : des gateways techniques.

## Constats à traiter (quick-wins et pièges)

- **Code mort** : `publication.find_by_doi`, `authorship.unlink_authorship` (+ son service, testé mais jamais appelé en prod), `person.remove_person_source`, `person.is_ambiguous`, `structure.find_by_id` (prod), `perimeter.find_by_id` (prod), `publisher.find_publisher_by_name_form` (interne seul).
- **Collisions de noms pipeline/admin** : `link_source_authorships_to_authorships` existe comme méthode d'`AuthorshipRepository` (admin) *et* comme fonction d'`AuthorshipBuildQueries` (`queries/pipeline/authorships/build.py`, pipeline) — opérations distinctes. Idem `get_name_form` (repo structure vs `StructuresQueries`).
- **Doublon de matérialisation** : `perimeter_structures` est reconstruite par deux chemins — `perimeter.refresh_structures` (API) et `PerimeterStructuresQueries` (pipeline `affiliations`) — façades du même SQL.
- **Le seul contournement API→repo direct** : `interfaces/api/routers/journals.py:185` appelle `update_journal_fields` sans passer par le service (aperçu d'impact dans un SAVEPOINT annulé). Cas particulier, mais c'est l'unique « flat CRUD API » au sens strict.

## Chantiers qui en sortent

1. **Descente pipeline.** `doi_prefix_repository` en bloc → `pipeline/`. `journal`/`publisher` **se scindent** : bloc find-or-create + enrichissement → `pipeline/`, fusion → repository mince. `publication.update_oa_status`/`mark_unpaywall_checked`/`create`, `authorship.enforce_confirmed_authorships` → `pipeline/`.
2. **La catégorie bulk-admin.** Décider où logent les opérations ensemblistes déclenchées par l'humain (pays, batch-assign, propagation de périmètre). Ni phase pipeline, ni commande d'agrégat.
3. **Ménage.** Retirer le code mort ; désambiguïser les homonymes ; dédoublonner la matérialisation `perimeter_structures` ; router `journals.py:185` par le service.
4. **Nommage.** Assumer que ces « repositories » sont, pour l'essentiel, des data-mappers sous des command-services — le vocabulaire cible (`repositories/` pour les vrais agrégats curés, gateways pour le reste) découle de là.
