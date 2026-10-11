# Inventaire des sous-étapes du pipeline

Annexe de la fiche [Graphe de dépendances du pipeline](CODE_pipeline-dag.md). Établi par lecture du code au 2026-10-10, sans exécution.

Rubriques de chaque sous-étape :

- **Lit**, **Écrit** : tables et colonnes.
- **Réseau** : API interrogée et comportement en cas d'échec.
- **Run précédent** : données écrites par la sous-étape elle-même ou par une phase plus loin dans l'ordre.
- **Sélection** : tout le stock, ou le critère du sous-ensemble traité.
- **Décisions humaines** : arbitrages et saisies lus, préservés ou écrasés.
- **Déclenchement** : mode, configuration, options.
- **Services** : appels aux services de l'application web (`application/services/`).
- **Idempotence**.

Une rubrique absente vaut « aucun » ou « tout le stock ».

## Étapes de niveau run

`interfaces/cli/run_pipeline.py`.

#### run.lock

- Écrit : verrou consultatif PostgreSQL de session, tenu tout le run.

#### run.start_run

- Écrit : `nextval('pipeline_run_id_seq')`. En cas d'échec, le run n'est pas tracé.

#### run.refresh_perimeter_structures

- Lit : `perimeters(id, root_structure_ids)`, `structure_tutelles`, `structures(id)`.
- Écrit : `perimeter_structures`, remplacement complet (fermeture récursive).
- Décisions humaines : périmètres et tutelles.
- Déclenchement : chaque run, même avec `--only` ou `--from`.
- Remarque : la même fonction tourne encore au début d'`affiliations` et dans les commandes d'administration.

#### run.record_phase

- Écrit : une ligne par phase dans `pipeline_phase_executions`. `status` vaut `ok` seulement sans signal.
- Lu par `extract` en mode `daily`.

## extract

Chaque source tourne dans son propre thread, avec sa connexion et sa transaction, sous un disjoncteur (seuil 5). Toutes les sources écrivent par `upsert_staging`.

#### extract.guard_perimeter

- Lit : `config.perimeter_extraction`, `perimeter_structures`, `perimeters(code)`. Lève une erreur si le périmètre d'extraction est vide.

#### Écriture commune : upsert_staging

- Écrit : `staging(source, source_id, doi, raw_data, raw_hash, authors_truncated, entry_mode, processed, disappeared_at, last_seen_at)`, upsert sur `(source, source_id)`.
  - `raw_data`, `processed=FALSE` et `authors_truncated` changent seulement si `raw_hash` diffère.
  - `doi` existant jamais écrasé. `entry_mode` jamais réécrit.
  - `disappeared_at=NULL` et `last_seen_at=now()` toujours.
- Run précédent : `staging.raw_hash` ; `processed` et `raw_data` vidés par `normalize`.

#### extract.hal

- Lit : `structures(hal_collection)` du périmètre, `config`.
- Réseau : HAL Solr, curseur, 0,5 s entre appels.
- Run précédent : `pipeline_phase_executions` (date du dernier `extract` `daily` à statut `ok`).
- Sélection : `full` = une passe par année ; `daily` = documents modifiés depuis le dernier `extract` `daily` réussi, sinon 30 jours.
- Déclenchement : seule source moissonnée en `daily`.

#### extract.openalex, extract.scanr, extract.theses, extract.datacite, extract.wos

- Lit : `structures.api_ids->'<source>'` du périmètre.
- Réseau : API de chaque source. OpenAlex pose `authors_truncated` quand un document a exactement 100 auteurs. DataCite filtre par mots-clés d'affiliation. theses.fr parcourt tout l'historique, sans borne d'année. WoS gère son quota par des pauses et un arrêt à 100 000 enregistrements.
- Déclenchement : mode `full` seulement. WoS seulement avec `--include-wos`.

## resolve_ra

#### resolve_ra.resolve_prefixes

- Lit : vue `candidate_dois` (voir ci-dessous) et `doi_prefixes`.
- Écrit : `doi_prefixes(prefix, ra)`, insertion seule. `ra='unknown'` si doi.org ne connaît pas le préfixe.
- Réseau : doi.org/ra, lots de 100, disjoncteur (seuil 10). Un lot en erreur 4xx est réessayé au run suivant.
- Run précédent : `publications.in_perimeter` (`authorships`), `source_publications.publication_id` (`publications`), `doi` et `external_ids` (`normalize`, `metadata_correction`), `publication_relations.target_doi` (`relations`).
- Sélection : préfixes absents de `doi_prefixes`. Un préfixe `unknown` n'est jamais redemandé.

La vue `candidate_dois` réunit, pour les publications du périmètre : `source_publications.doi`, les éléments de `external_ids.related_dois`, les `publication_relations.target_doi`, et le DOI arXiv déduit de `external_ids.arxiv_id`.

## fetch_missing

Configuration commune : `fetch_missing_retry_after_days`, `fetch_missing_max_per_source`. Les échecs vont dans `failed_lookups` : définitifs quand l'identifiant est natif de la source, sinon réessayés après le délai.

#### fetch_missing.hal_by_id

- Lit : `external_ids.hal_id` des notices OpenAlex et ScanR de publications du périmètre, absentes de `staging` HAL et de `failed_lookups`.
- Écrit : `staging` (`entry_mode='fetch_missing_hal'`), `failed_lookups`.
- Réseau : HAL, 5 workers, disjoncteur. HAL indisponible laisse l'identifiant candidat au run suivant.
- Run précédent : `external_ids`, `publication_id`, `in_perimeter`.

#### fetch_missing.hal_by_nnt

- Lit : NNT des notices theses.fr de publications du périmètre sans notice HAL.
- Écrit : `staging`, `failed_lookups`.
- Run précédent : `publications.doc_type`, `in_perimeter`.
- Déclenchement : mode `full`.
- Remarque : une thèse trouvée sans `halId_s` n'est pas enregistrée et sera redemandée à chaque run `full`.

#### fetch_missing.doi.<source>

- Lit : `candidate_dois` hors DOI déjà présents dans la source cible, hors `failed_lookups` en attente. Pour Crossref et DataCite, filtre sur `doi_prefixes.ra`.
- Écrit : `staging` (`entry_mode='fetch_missing_doi'`), `failed_lookups`.
- Réseau : une API par source cible, un thread chacune, disjoncteur (seuil 10). Une erreur transitoire laisse le DOI candidat.
- Run précédent : `candidate_dois`, `doi_prefixes.ra`.
- Sélection : tronquée à `fetch_missing_max_per_source`, par ordre alphabétique des DOI.

## fetch_stale

Mode `full` seulement. Sources traitées une par une, chacune sous disjoncteur (seuil 10).

#### fetch_stale.<source>

- Lit : `staging(last_seen_at, disappeared_at)`, `source_publications.pub_year` pour le filtre d'années.
- Écrit : document trouvé → `upsert_staging` ; document absent → `staging.disappeared_at=now()`.
- Réseau : réinterrogation par identifiant natif. Une erreur transitoire laisse le document candidat.
- Run précédent : `source_publications.pub_year` (`normalize`).
- Sélection : `last_seen_at` plus ancien que `fetch_stale_after_days` (90 jours par défaut).

## fetch_truncated

#### fetch_truncated.refetch_openalex

- Lit : `staging` OpenAlex où `authors_truncated`.
- Écrit : plus de 100 auteurs → `raw_data`, `processed=FALSE`, `authors_truncated=FALSE` ; sinon, ou document inconnu d'OpenAlex, `authors_truncated=FALSE` seulement.
- Réseau : OpenAlex `/works/<id>`, disjoncteur. Un document supprimé d'OpenAlex (404) perd son marqueur ; OpenAlex indisponible, le marqueur reste.

## normalize

Une transaction par source, un savepoint par document. Une erreur sur un document le laisse `processed=FALSE`.

#### normalize.select_pending

- Lit : `staging` où `processed=FALSE`.
- Déclenchement : toutes les sources de `--sources`, quel que soit le mode.

#### normalize.reject

- Écrit : suppression des `source_publications` d'un document sans titre ou sans année, avec cascade sur `source_authorships`, `source_authorship_addresses`, `source_authorship_rors`, `confirmed_authorships`. `keys_dirty=true` sur les notices sœurs.

#### normalize.mark_done

- Écrit : `staging.processed=TRUE`, `raw_data='{}'`. Avec `--raw-store`, archive le contenu brut sur disque.

#### normalize.upsert_source_publication

- Écrit : `source_publications`, toutes les colonnes de la source. `raw_metadata='{}'`, `keys_dirty=true` à chaque passage.
- Remarque : remet à zéro les corrections de `metadata_correction`, qui doit donc tourner après chaque `normalize`.

#### normalize.publishers, normalize.journals, normalize.monographs

- Lit : `publishers`, `publisher_name_forms`, `journals`, `journal_issns`, `journal_name_forms`, `monographs`.
- Écrit : création à la volée ; colonnes vides complétées par `COALESCE`, donc la première source écrit la valeur.
- Run précédent : fusions, types et suppressions de `publishers_journals`.
- Services : `find_or_create_publisher`, `find_or_create_journal`, `find_or_create_monograph`.

#### normalize.signatures

- Lit : `source_authorships`, `author_identifying_keys`, `source_publications.authors_hash`.
- Écrit : `source_authorships` (suppressions, mises à jour, insertions selon l'appariement par identité), `author_identifying_keys`, `source_authorship_rors`, `authors_hash`. `countries_dirty=true` sur les signatures écrites.
- Sélection : documents dont l'empreinte du bloc d'auteurs a changé, ou tous avec `--normalize-full`.
- Décisions humaines : une signature conservée garde `person_id` et sa confirmation. Une signature supprimée perd sa confirmation par cascade.

#### normalize.addresses

- Écrit : `addresses(raw_text, normalized_text)`, `source_authorship_addresses`. `addresses.countries` (ScanR) seulement si vide. `addresses.suggested_countries` (OpenAlex) seulement si les deux sont vides.
- Run précédent : sortie de `countries`, qui bloque les valeurs ultérieures des sources.

#### normalize.prune_disappeared

- Écrit : suppression des `source_publications` dont `staging.disappeared_at` est posé, avec cascade. `keys_dirty=true` sur les notices sœurs.

#### normalize.cleanup_orphan_identities, normalize.vacuum_staging

- Écrit : suppression des `author_identifying_keys` sans signature ; `VACUUM` (`VACUUM FULL` en `full`).

## affiliations

#### affiliations.refresh_ror

- Écrit : `ror_organizations`, `ror_relations`, remplacement complet ; `ror_dump_imports`.
- Réseau : Zenodo. En cas d'échec, référentiel inchangé.
- Sélection : seulement si la version du dump a changé.
- Services : `import_ror_dump`.
- Remarque : aucune phase du pipeline ne lit ces tables.

#### affiliations.refresh_perimeter_structures

- Identique à `run.refresh_perimeter_structures`.

#### affiliations.resolve_addresses

- Lit : `structure_name_forms`, `structures.structure_type`, `addresses.normalized_text`.
- Écrit : `address_structures(matched_form_id)`. Supprime les liens automatiques non confirmés devenus caducs.
- Décisions humaines : `is_confirmed` et liens manuels préservés.
- Sélection : tout le stock à chaque run.

#### affiliations.populate

- Écrit : rafraîchit la vue matérialisée `source_authorship_structures`, puis synchronise `source_authorships.in_perimeter` et pose `keys_dirty` sur les notices orphelines qui entrent dans le périmètre.
- Remarque : le périmètre effectif est l'intersection du périmètre d'extraction et du périmètre des personnes.

## publishers_journals

Une transaction par sous-étape. Aucune option du run ne change le comportement.

#### publishers_journals.resolve_publishers

- Lit : `doi_prefixes` sans éditeur et jamais vérifiés, un DOI exemple dans `source_publications`, `publisher_name_forms`.
- Écrit : `doi_prefixes` (métadonnées d'éditeur, `publisher_id`, `publisher_checked_at`), `publishers`, `publisher_name_forms`.
- Réseau : Crossref et DataCite, 3 requêtes simultanées, disjoncteur (seuil 10).
- Sélection : `publisher_checked_at IS NULL`. Un préfixe trouvé ou absent n'est plus interrogé ; un préfixe dont l'API est indisponible est repris au run suivant.
- Services : `match_or_create_publisher`.

#### publishers_journals.enrich_journals_from_openalex

- Lit : `journals` de type `unknown` avec `openalex_id`.
- Écrit : `journals.apc_amount`, `apc_currency`, `journal_type`.
- Réseau : OpenAlex Sources, lots de 50, disjoncteur (seuil 3).
- Sélection : sans date de vérification, une revue qui reste `unknown` est réinterrogée à chaque run.
- Décisions humaines : APC saisis à la main écrasés sur une revue `unknown`.
- Services : `update_journal_apc`.

#### publishers_journals.check_journals_in_sudoc

- Lit : `journals`, `journal_issns`, ISSN des notices (`source_publications.biblio`).
- Écrit : `journal_issns`, remplacement complet par revue ; titre et forme de nom de certaines séries.
- Réseau : Sudoc, 5 requêtes/s, disjoncteur (seuil 3). Une revue en erreur reste à vérifier.
- Run précédent : `sudoc_checked_at=NULL` posé par les fusions du run précédent.
- Sélection : revues avec un ISSN jamais vérifié, un ISSN de notice absent, ou un titre de série en forme de volume.
- Décisions humaines : ISSN saisis à la main revérifiés et modifiables.

#### publishers_journals.merge_duplicate_journals

- Lit : `journal_issns`, `journals(pub_count)`, `source_publications(journal_id, pub_year, doi, publication_id)`.
- Écrit : par fusion, le même chemin qu'une fusion d'administration : `publications`, `source_publications`, `apc_payments`, `journal_name_forms`, `journal_issns`, `journals`, recalcul des `pub_count`, requalification des notices, `refresh_from_sources` des publications. Par cascade, `monographs.journal_id` passe à NULL.
- Run précédent : `journals.pub_count` (`authorships`), `source_publications.publication_id` (`publications`), `journal_id` posé par `metadata_correction`.
- Décisions humaines : aucune table ne permet d'interdire une fusion automatique.
- Services : `merge_journals`, `refresh_from_sources`.
- Idempotence : converge en plusieurs runs, car une fusion remet les ISSN déplacés à vérifier.

#### publishers_journals.type_proceedings_journals

- Lit : `journals`, types bruts des notices, ISSN actifs.
- Écrit : `journals.journal_type='proceedings'`.
- Run précédent : `raw_metadata.doc_type` (`metadata_correction`).
- Décisions humaines : un type saisi à la main est écrasé sur une revue sans ISSN actif dont le titre évoque des actes.

#### publishers_journals.learn_journal_doi_namespaces

- Lit : `source_publications(doi, journal_id)`, `journals.journal_type`.
- Écrit : `journal_doi_namespaces`, remplacement complet.
- Seul lecteur : `metadata_correction.journal_by_doi`.

#### publishers_journals.enrich_journals_from_doaj

- Lit : `journal_issns`, `max(journals.doaj_imported_at)`.
- Écrit : `journals.is_in_doaj` (remise à faux globale puis pose), `doaj_payload`, `doaj_imported_at`.
- Réseau : export CSV du DOAJ, sans reprise ni disjoncteur. Export inaccessible : revues inchangées, source signalée indisponible.
- Déclenchement : dernier import plus ancien que `doaj_refresh_after_days` (30 jours).
- Décisions humaines : `is_in_doaj` saisi à la main écrasé.

#### publishers_journals.merge_duplicate_monographs

- Lit : `monographs` de même titre normalisé.
- Écrit : `source_publications.monograph_id`, `publications.monograph_id`, `monographs`.
- Idempotence : converge en plusieurs runs.

#### publishers_journals.link_monographs_to_collections

- Lit : `monographs`, `source_publications(monograph_id, journal_id)`, `journal_issns.status`.
- Écrit : crée ou retrouve les revues de série (`journals`, `journal_name_forms`, `journal_type` si `unknown`), puis `monographs.journal_id`.
- Run précédent : `monographs.proceedings` (sous-étape suivante), `source_publications.journal_id` (`metadata_correction`).
- Services : `find_or_create_journal`.
- Remarque : le type d'une série est fixé à sa création, d'après la nature de ses volumes à ce moment.

#### publishers_journals.type_proceedings_volumes

- Lit : `monographs`, `journals.journal_type` de la collection, types des notices.
- Écrit : `monographs.proceedings`.
- Run précédent : `raw_metadata.doc_type` (`metadata_correction`).

#### publishers_journals.delete_empty_monographs, delete_empty_journals, delete_empty_publishers

- Écrit : suppression des monographies, revues et éditeurs sans référence, dans cet ordre.
- Run précédent : `publications.journal_id` et `monograph_id` (`publications`).
- Décisions humaines : une revue ou un éditeur édité à la main est supprimé quand plus rien n'y renvoie.

## metadata_correction

Persistance par lots de 5 000. Chaque ligne modifiée reçoit `keys_dirty=true`.

#### metadata_correction.journal_by_doi

- Lit : `journal_doi_namespaces`, `source_publications(journal_id, doi, raw_metadata, doc_type)`.
- Écrit : `source_publications.journal_id`, clé `journal_id` de `raw_metadata`.
- Run précédent : sa propre trace dans `raw_metadata`, `doi` corrigé par `metadata_correction.cluster`.

#### metadata_correction.unary

- Lit : toutes les `source_publications`, `journals(journal_type, oa_model)`, `monographs.proceedings`, `doi_prefixes`, `publishers.publisher_type`, `language_forms`.
- Écrit : `source_publications.doc_type`, `oa_status`, `language`, `external_ids`, clés correspondantes de `raw_metadata`.
- Run précédent : `doi` corrigé par `metadata_correction.cluster`.
- Services : la même correction tourne dans l'application web quand le type d'une revue change.

#### metadata_correction.cluster

- Lit : notices regroupées par DOI brut (relations DataCite, jeux de données, livres et chapitres).
- Écrit : `source_publications.doi`, clé `doi` de `raw_metadata`.

## publications

Aucun appel réseau. Une seule transaction pour la réconciliation.

#### publications.mark_dirty

- Écrit : `keys_dirty=true` sur tout le stock avec `--rebuild-publications`, puis sur les notices sœurs des notices marquées (un seul niveau).

#### publications.reconcile

Sous-étapes indissociables : sélection du voisinage, plan, création, rattachement, détachement, dissolution, rafraîchissement des survivantes, levée des marqueurs.

- Lit : `source_publications` marquées et leurs voisines (même DOI, arXiv, PMID, NNT, identifiant HAL, ou même titre long, type et année), `source_authorships.in_perimeter`, `publications.doi`.
- Écrit : `publications` (création, mise à jour, suppression), `publications_detail`, `source_publications.publication_id`, `apc_payments.publication_id`, `keys_dirty=false`.
- Run précédent : `source_publications.countries` (`countries`), `publications.oa_status` et `unpaywall_checked_at` (`oa_status`), `publication_id` (elle-même).
- Décisions humaines : `rejected_authorships` d'une publication dissoute supprimés par cascade, sans report sur la publication qui la remplace.
- Services : `create_publication`, `refresh_from_sources`.
- Identifiants : la publication qui a le DOI garde son identifiant ; sinon celle de la plus petite notice.
- Remarque : `refresh_from_sources` remet `subjects_ingested_at` à NULL, ce qui déclenche `subjects`.

#### publications.delete_without_sources

- Écrit : suppression des publications sans notice, avec cascade.

## persons

Aucun appel réseau. Une seule transaction. Tout le stock à chaque run.

#### persons.enforce_confirmed_authorships

- Lit : `confirmed_authorships`.
- Écrit : `source_authorships.person_id`.

#### persons.requalify_misplaced_identifiers, persons.transfer_identifiers_by_consensus

- Lit : `author_identifying_keys`, `source_authorships`, `person_identifiers`, `person_name_forms` confirmées, `confirmed_authorships`.
- Écrit : `source_authorships.neutralized_identifiers`, détachement de signatures (`person_id`, `resolution_mode`), `person_identifiers` (transfert des attributions `pending`).
- Run précédent : ses propres neutralisations, recalculées en entier.
- Décisions humaines : statuts `confirmed` et confirmations de signatures protégés.

#### persons.complete_reduced_first_names

- Écrit : `persons` (nom et prénom), `person_name_forms`.
- Services : `update_name`.

#### persons.cascade

Passes de rattachement puis de création, indissociables (index en mémoire partagés).

- Lit : signatures du périmètre sans personne, candidats hors périmètre, `person_identifiers`, `person_name_forms`, `rejected_authorships`, `persons`.
- Écrit : `source_authorships(person_id, resolution_mode)`, `persons`, `person_name_forms`, `person_identifiers`. Journal sur fichier des orphelines.
- Décisions humaines : rejets, statuts de formes de nom et d'identifiants, exclusions, confirmations.
- Services : `create_person`, `link_authorship`, `add_name_form`, `add_identifiers_from_authorships`, `update_name`.
- Identifiants : `persons.id` stable car `source_authorships.person_id` persiste d'un run à l'autre.
- Idempotence : la requête des candidats hors périmètre n'a pas d'`ORDER BY`.

#### persons.detach_stale_cross_source

- Écrit : détache les rattachements inter-sources non confirmés et non réévalués dans le run.

#### persons.populate_person_name_forms

- Écrit : `person_name_forms`, synchronisation complète. Les statuts confirmés et rejetés sont préservés.
- Remarque : rend inutiles les écritures de formes de nom faites plus tôt dans la phase.

#### persons.reorphan_ambiguous_nominal, delete_unsupported_identifier_attributions, delete_empty_persons

- Écrit : détachement des rattachements nominaux ambigus ; suppression des attributions automatiques `pending` sans signature ; suppression des personnes sans signature ni `persons_rh`.
- Décisions humaines : la suppression d'une personne efface par cascade son exclusion, ses identifiants manuels, ses `rejected_authorships` et `distinct_persons`.
- Remarque : `distinct_persons` n'est lu nulle part dans la phase.

## authorships

Aucun appel réseau.

#### authorships.build

Sous-étapes enchaînées dans une transaction : purge (avec `--rebuild-authorships`), insertion des paires manquantes, élagage, propagation des attributs depuis les signatures qui attestent chaque authorship, `publications.in_perimeter`, rafraîchissement des vues matérialisées `authorship_structures` et `publication_structures`.

- Lit : `source_authorships`, `source_publications.publication_id`, `rejected_authorships`, `persons.exclusion`, `source_authorship_structures`.
- Écrit : `authorships`, `publications.in_perimeter`, deux vues matérialisées.
- Décisions humaines : `rejected_authorships` à l'insertion seulement ; `persons.exclusion`.

#### authorships.purge_orphan_publications

- Écrit : suppression des publications sans authorship, avec cascade.

#### authorships.address_pub_count, journal_pub_count, publisher_pub_count

- Écrit : `addresses.pub_count`, `journals.pub_count`, `publishers.pub_count`.

## relations

Aucun appel réseau. Une transaction. Les signaux sont lus, puis la table est remplacée en une écriture : les sous-étapes sont indissociables.

#### relations.rebuild

- Lit : `source_publications(meta, raw_metadata, doi, external_ids, doc_type, publication_id)`, `publications(doc_type, doi, title_normalized, pub_year)`.
- Écrit : `publication_relations`, remplacement complet.
- Run précédent : ses propres lignes, lues avant la purge pour écarter les paires déjà typées. Une relation déclarée converge en deux runs.

## subjects

Aucun appel réseau.

#### subjects.ingest

- Lit : `publications.subjects_ingested_at`, `source_publications.topics`.
- Écrit : `publication_subjects`, `subjects`, `subjects_ingested_at`, puis suppression des sujets sans lien.
- Sélection : `subjects_ingested_at IS NULL`, ou tout avec `--rebuild-subjects`.

#### subjects.usage_counts, subjects.cooccurrences

- Écrit : `subjects.usage_count` ; rafraîchit la vue matérialisée `subject_cooccurrences`.

## countries

Aucun appel réseau.

#### countries.detect_by_country_name, countries.detect_by_place_name

- Lit : `place_name_forms`, `addresses` sans pays.
- Écrit : `addresses.countries`, `countries_dirty=true`.
- Décisions humaines : un pays saisi est préservé ; une remise à vide est annulée par la détection suivante.

#### countries.suggest

- Lit : adresses avec pays (base de comparaison) et adresses sans pays ni suggestion.
- Écrit : `addresses.suggested_countries`, `'{}'` quand rien ne correspond.
- Déclenchement : en `full`, retente aussi les suggestions vides.

#### countries.refresh_publication_countries

- Lit : `source_authorships.countries_dirty`, `addresses.countries_dirty`.
- Écrit : `source_publications.countries`, `publications.countries` (trié), levée des marqueurs.
- Remarque : `publications` écrit aussi `publications.countries`, dans l'ordre de priorité des sources. L'ordre du tableau dépend du dernier écrivain.

## oa_status

#### oa_status.verify_unpaywall

- Lit : `publications(doi, oa_status, unpaywall_checked_at)`, dépôt HAL ouvert dans `source_publications`.
- Écrit : `publications.oa_status`, `unpaywall_checked_at`, par lots de 50.
- Réseau : Unpaywall, 5 requêtes simultanées, disjoncteur. Une publication est marquée vérifiée seulement si Unpaywall a répondu.
- Sélection : non vérifiées depuis `unpaywall_recheck_after_days` (15 jours), plafond `unpaywall_max_per_run`.
- Déclenchement : `POLITE_POOL_EMAIL` présent.

## Nœuds

Application du critère de la fiche aux sous-étapes ci-dessus. Chaque nœud est donné avec ses sorties. La colonne « Écart » nomme ce qui empêche un nœud plus fin, ou ce qui viole le critère dans le code actuel : un autre écrivain de la même sortie, ou un passage en mémoire.

### Acquisition

| Nœud | Sous-étapes | Sorties | Écart |
|---|---|---|---|
| Périmètre matérialisé | `run.refresh_perimeter_structures`, `affiliations.refresh_perimeter_structures` | `perimeter_structures` | Calculé deux fois par run : un nœud dont dépendent l'extraction et `affiliations`. |
| Moissonnage d'une source (un nœud par source) | `extract.<source>` | lignes de `staging` de la source | `staging` a plusieurs écrivains : tous les nœuds d'acquisition, et `normalize` qui pose `processed` et vide `raw_data`. La propriété y va par ligne, non par colonne. |
| Agences d'enregistrement | `resolve_ra.resolve_prefixes` | `doi_prefixes(prefix, ra)` | `resolve_publishers` corrige aussi `ra`. |
| Recherche des documents manquants (un nœud par canal : identifiant HAL, NNT, DOI par source) | `fetch_missing.*` | `staging`, `failed_lookups` | `staging` partagé, comme au moissonnage. |
| Rafraîchissement des documents périmés (un nœud par source) | `fetch_stale.<source>` | `staging(last_seen_at, disappeared_at, raw_data)` | `staging` partagé. |
| Listes d'auteurs tronquées | `fetch_truncated.refetch_openalex` | `staging(raw_data, authors_truncated, processed)` | `staging` partagé. |
| Référentiel ROR | `affiliations.refresh_ror` | `ror_organizations`, `ror_relations`, `ror_dump_imports` | Aucune sortie lue par le pipeline : nœud sans consommateur. |
| Éditeurs des préfixes DOI | `publishers_journals.resolve_publishers` | `doi_prefixes` (éditeur, vérification), `publishers`, `publisher_name_forms` | `publishers` et `publisher_name_forms` sont aussi écrits par `normalize`. |
| Revues dans OpenAlex | `publishers_journals.enrich_journals_from_openalex` | `journals(apc_amount, apc_currency, journal_type)` | `journal_type` a trois autres écrivains (voir Revues). |
| Revues dans le Sudoc | `publishers_journals.check_journals_in_sudoc` | `journal_issns`, `journals.title`, `journal_name_forms` | `journal_issns` est aussi écrit par `normalize` et par la fusion de revues. |
| Revues dans le DOAJ | `publishers_journals.enrich_journals_from_doaj` | `journals(is_in_doaj, doaj_payload, doaj_imported_at)` | `is_in_doaj` est aussi écrit par la fusion de revues. |
| Statut open access | `oa_status.verify_unpaywall` | `publications(oa_status, unpaywall_checked_at)` | `oa_status` est aussi écrit par la réconciliation des publications. |

### Notices et signatures

| Nœud | Sous-étapes | Sorties | Écart |
|---|---|---|---|
| Normalisation d'une source (un nœud par source) | `normalize.<source>` et ses sorties annexes | `source_publications`, `source_authorships`, `source_authorship_addresses`, `source_authorship_rors`, `author_identifying_keys`, `addresses`, création de `publishers`, `journals`, `monographs`, `journal_issns`, `journal_name_forms` | Écrit les colonnes brutes que `metadata_correction` réécrit (`doc_type`, `oa_status`, `language`, `external_ids`, `doi`, `journal_id`). Crée des référentiels que `publishers_journals` fusionne et supprime. Écrit `addresses.countries` et `suggested_countries`, aussi écrits par Pays. |
| Documents disparus | `normalize.prune_disappeared` | suppression de `source_publications` | Même table que la normalisation. |
| Identités sans signature | `normalize.cleanup_orphan_identities` | suppression de `author_identifying_keys` | Même table que la normalisation. |
| Correction des métadonnées | `metadata_correction.journal_by_doi`, `.unary`, `.cluster` | colonnes corrigées de `source_publications`, `raw_metadata` | Mêmes colonnes que la normalisation. `journal_by_doi` lit le `doi` que `cluster` corrige au run précédent. |

### Structures

| Nœud | Sous-étapes | Sorties | Écart |
|---|---|---|---|
| Résolution des adresses | `affiliations.resolve_addresses` | `address_structures(matched_form_id)` | Aucun dans le pipeline (l'admin écrit `is_confirmed`). |
| Signatures du périmètre | `affiliations.populate` | vue `source_authorship_structures`, `source_authorships.in_perimeter` | Pose aussi `keys_dirty`, qu'écrivent la normalisation, la correction et la réconciliation. |

### Revues, monographies, éditeurs

| Nœud | Sous-étapes | Sorties | Écart |
|---|---|---|---|
| Fusion des revues en double | `publishers_journals.merge_duplicate_journals` | suppression et repointage de `journals`, `journal_issns`, `journal_name_forms`, `publications.journal_id`, `source_publications.journal_id`, `apc_payments.journal_id`, `pub_count` | Réécrit des colonnes de nombreux autres nœuds, dont la requalification des notices et le recalcul des publications. |
| Revues de recueils d'actes | `publishers_journals.type_proceedings_journals` | `journals.journal_type` | `journal_type` a quatre écrivains : OpenAlex, ce nœud, les séries de monographies, l'admin. |
| Espaces de noms DOI des revues | `publishers_journals.learn_journal_doi_namespaces` | `journal_doi_namespaces` | Aucun. |
| Fusion des monographies en double | `publishers_journals.merge_duplicate_monographs` | `monographs`, `source_publications.monograph_id`, `publications.monograph_id` | `monograph_id` est aussi écrit par la normalisation et la réconciliation. |
| Collections des monographies | `publishers_journals.link_monographs_to_collections` (séries et rattachement) | revues de série dans `journals`, `monographs.journal_id` | Un seul nœud : le rattachement reçoit les séries en mémoire. Le scinder suppose de relire les séries en base. |
| Volumes d'actes | `publishers_journals.type_proceedings_volumes` | `monographs.proceedings` | Lu par les collections au run suivant : cycle. |
| Référentiels vides | `delete_empty_monographs`, `delete_empty_journals`, `delete_empty_publishers` | suppressions dans `monographs`, `journals`, `publishers` | Trois nœuds enchaînés : une monographie protège sa revue, une revue son éditeur. |

### Publications et personnes

| Nœud | Sous-étapes | Sorties | Écart |
|---|---|---|---|
| Réconciliation des publications | `publications.mark_dirty`, `publications.reconcile` | `publications`, `publications_detail`, `source_publications.publication_id`, `keys_dirty`, `apc_payments.publication_id` | Un seul nœud : plan et application partagent le voisinage en mémoire. Réécrit `oa_status` et `countries`, aussi écrits par Statut open access et Pays. |
| Publications sans notice | `publications.delete_without_sources` | suppression de `publications` | Même table que la réconciliation. |
| Résolution des personnes | `persons.enforce_confirmed_authorships`, `requalify_misplaced_identifiers`, `transfer_identifiers_by_consensus`, `complete_reduced_first_names`, `cascade`, `detach_stale_cross_source`, `reorphan_ambiguous_nominal`, `delete_unsupported_identifier_attributions`, `delete_empty_persons` | `source_authorships(person_id, resolution_mode, neutralized_identifiers)`, `persons`, `person_identifiers` | Un seul nœud : six sous-étapes écrivent `person_id`, et la cascade partage ses index en mémoire. La complétion des prénoms, avant la cascade, écrit des formes de nom que la cascade charge. |
| Formes de nom des personnes | `persons.populate_person_name_forms` | `person_name_forms` | La complétion des prénoms écrit aussi la table, avant la cascade ; ordre fixé par le graphe. |

### Authorships et projections

| Nœud | Sous-étapes | Sorties | Écart |
|---|---|---|---|
| Authorships | `authorships.build` (insertion, élagage, attributs) | `authorships` | Aucun dans le pipeline. |
| Publications du périmètre | `authorships.build` (report) | `publications.in_perimeter` | Aucun dans le pipeline. Séparable des authorships : relit la table. |
| Structures des authorships | rafraîchissement de `authorship_structures` | vue `authorship_structures` | Séparable : relit les tables. |
| Structures des publications | rafraîchissement de `publication_structures` | vue `publication_structures` | Dépend de la précédente. |
| Publications sans authorship | `authorships.purge_orphan_publications` | suppression de `publications` | Même table que la réconciliation. |
| Compteur des adresses | `authorships.address_pub_count` | `addresses.pub_count` | Aucun. Ne dépend ni des authorships ni du périmètre. |
| Compteur des revues | `authorships.journal_pub_count` | `journals.pub_count` | Aussi écrit par la fusion de revues. |
| Compteur des éditeurs | `authorships.publisher_pub_count` | `publishers.pub_count` | Aussi écrit par les fusions de revues et d'éditeurs. |

### Enrichissements

| Nœud | Sous-étapes | Sorties | Écart |
|---|---|---|---|
| Relations | `relations.rebuild` | `publication_relations` | Lit ses propres lignes du run précédent. |
| Sujets des publications | `subjects.ingest` | `publication_subjects`, `subjects`, `subjects_ingested_at` | `subjects_ingested_at` est remis à nul par la réconciliation. |
| Usage des sujets | `subjects.usage_counts` | `subjects.usage_count` | Aucun. |
| Cooccurrences des sujets | rafraîchissement de `subject_cooccurrences` | vue `subject_cooccurrences` | Aucun. |
| Pays détectés | `countries.detect_by_country_name`, `detect_by_place_name` | `addresses(countries, countries_dirty)` | `countries` est aussi écrit par la normalisation (ScanR) et l'admin. |
| Pays suggérés | `countries.suggest` | `addresses.suggested_countries` | Aussi écrit par la normalisation (OpenAlex). |
| Pays des publications | `countries.refresh_publication_countries` | `source_publications.countries`, `publications.countries`, levée des marqueurs | `publications.countries` est aussi écrit par la réconciliation. |

### Verdicts sur les sorties partagées

- **`staging`** : les canaux d'acquisition y écrivent la dernière observation d'un document, dans un ordre indifférent ; `normalize` la consomme comme une file. `fetch_truncated` reste une phase (voir les décisions de la fiche).
- **Colonnes de `source_publications`** : la normalisation écrit la valeur de la source, la correction la remplace et range l'original. Le graphe fixe l'ordre.
- **Référentiels créés par la normalisation** : la normalisation crée et complète les champs vides, `publishers_journals` fusionne et supprime. Le graphe fixe l'ordre ; les formes de nom et les ISSN transférés par une fusion évitent de recréer le doublon.
- **`journal_type`** : ordre fixe dans `publishers_journals`, écritures d'OpenAlex et des séries limitées aux types inconnus. Le type saisi à la main que les règles des actes écrasent relève du chantier sur les décisions humaines.
- **`publications.oa_status`** : la réconciliation calcule une valeur sauf si Unpaywall en a établi une, qui fait autorité.
- **`publications.countries`** : réconciliation et phase `countries` appliquent la même formule.
- **Formes de nom des personnes** : la cascade n'en écrit plus ; la complétion des prénoms qui la précède écrit celles que la cascade charge.
- **Compteurs `pub_count`** : les fusions appliquent la même formule que le recalcul.
- **Suppressions de publications** : trois conditions distinctes, ordre fixe, suppressions idempotentes.
- **Périmètre matérialisé** : un nœud dont dépendent l'extraction et `affiliations`, exécuté une fois par run, et aussi quand l'une de ces phases tourne seule.

## Anomalies relevées

Constatées par les inventaires. Les lignes marquées ✓ sont vérifiées dans le code ; les autres restent à confirmer.

- `publications.reconcile` : une publication peut disparaître sans successeur, avec perte du lien de ses `apc_payments`, quand le DOI d'une de ses notices est corrigé entre deux runs (source ou nouvelle règle de correction). Cas marginal, non constaté en base locale ; laissé en l'état.
- Décisions humaines effacées par cascade ou écrasées par le pipeline : traitées par le chantier [Décisions humaines durables](DATA_decisions-humaines-durables.md).
