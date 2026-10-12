# Inventaire — étapes exécutées, nœuds du graphe, journal

Annexe du chantier [Exécution du pipeline par nœuds](CODE_execution-par-noeuds.md). Code au 2026-10-12.

Notation du journal : ▶ titre de section ; ├─ └─ ligne d'étape ou barre de progression. Les barres s'affichent seulement dans un terminal interactif.

## Avant les phases

| Nœud | Étape | Journal |
|---|---|---|
| `perimeter_structures` | `refresh_perimeter_structures`, dans `run.py`, même avec `--only` ou `--from` | aucun |

## extract

| Nœud | Étape | Journal |
|---|---|---|
| — | garde : périmètre d'extraction vide | erreur |
| `extract.hal` (mode daily) | HAL seul, notices modifiées depuis le dernier run | ligne « Mode incrémental… », sans section |
| `extract.<source>` (mode full) | une source par thread, sources de la politique du mode | ▶ Extraction des sources ; ├─ barre par source ; │ bilan par source |

Les avertissements de source non configurée ou indisponible s'affichent après la fin de tous les threads.

## fetch_missing

| Nœud | Étape | Journal |
|---|---|---|
| `fetch_missing.hal_by_id` | si HAL est retenu | ▶ Recherche dans HAL des documents avec hal-id trouvés ailleurs ; └─ barre ou Rien à faire |
| `fetch_missing.hal_by_nnt` | si HAL est retenu, en mode full | ▶ Recherche dans HAL des thèses avec NNT trouvées ailleurs ; └─ barre ou Rien à faire |
| `fetch_missing.doi.<source>` | en parallèle, sources configurées | ▶ Recherche par DOI des documents manquants dans chaque source ; ├─ barre par source |

## fetch_stale

| Nœud | Étape | Journal |
|---|---|---|
| `fetch_stale.<source>` | une source après l'autre, en mode full | ├─ barre par source, sans section ; └─ Sautée en mode daily |

## fetch_truncated

| Nœud | Étape | Journal |
|---|---|---|
| `fetch_truncated.refetch_openalex` | si OpenAlex est retenu | ▶ N documents de 100 auteurs, potentiellement tronqués ; └─ barre |

## normalize

| Nœud | Étape | Journal |
|---|---|---|
| `normalize.<source>` | une source après l'autre, ordre de `SOURCE_PRIORITY` | ▶ Normalisation ; ├─ barre par source ; │ documents incomplets |
| `normalize.prune_disappeared` | toujours, toutes sources | « N documents supprimés (disparus de leur source) », sans branche |
| `normalize.cleanup_orphan_identities` | sauf si rien n'a été traité | ▶ Maintenance des tables ; └─ Terminé en… |
| — | `VACUUM` du staging, dans la même section | (même ligne) |

## affiliations

| Nœud | Étape | Journal |
|---|---|---|
| — | import du dump ROR, si une version plus récente existe (réseau : Zenodo) | ▶ Référentiel ROR ; └─ version déjà importée, importée, ou dump inaccessible |
| — | seconde matérialisation de `perimeter_structures`, garde du périmètre vide | aucun |
| `affiliations.resolve_addresses` | structures reconnues dans les adresses | ▶ Identification des structures dans les adresses institutionnelles ; ├─ barre ; └─ bilan |
| `affiliations.populate` | vue `source_authorship_structures`, `in_perimeter` des signatures | ▶ Rattachement des structures aux auteurs des documents ; └─ Terminé en… |

## resolve_ra

| Nœud | Étape | Journal |
|---|---|---|
| `resolve_ra.resolve_prefixes` | préfixes DOI inconnus, interrogés sur doi.org | « N préfixes DOI à résoudre », une ligne par préfixe, sans section |

## publishers_journals

| Nœud | Étape | Journal |
|---|---|---|
| `resolve_crossref_publishers` | éditeurs des préfixes DOI Crossref | ▶ Éditeurs ; ├─ Éditeurs des préfixes DOI Crossref : … |
| `resolve_datacite_publishers` | éditeurs des préfixes DOI DataCite | └─ Éditeurs des préfixes DOI DataCite : … |
| `enrich_journals_from_openalex` | type et APC des revues (OpenAlex) | ▶ Revues ; ├─ Type des revues sur OpenAlex : … |
| `check_journals_in_sudoc` | ISSN vérifiés au Sudoc | ├─ Vérification des ISSN dans le Sudoc : … |
| `merge_duplicate_journals` | cinq règles de fusion | ├─ Fusion des revues en double : … |
| `type_proceedings_journals` | recueils d'actes | ├─ Typage des recueils d'actes : … |
| `learn_journal_doi_namespaces` | espaces de noms DOI, recalcul complet | ├─ Espaces de noms DOI : … |
| `enrich_journals_from_doaj` | import du DOAJ, périodique | └─ Import du DOAJ : … |
| `merge_duplicate_monographs` | fusion des monographies | ▶ Monographies ; ├─ Fusion des monographies en double : … |
| `link_monographs_to_collections` | rattachement aux collections | ├─ Rattachement aux collections : … |
| `type_proceedings_volumes` | nature des monographies | └─ Nature des monographies : … |

Les onze étapes correspondent une à une aux onze nœuds, dans le même ordre.

## metadata_correction

| Nœud | Étape | Journal |
|---|---|---|
| `metadata_correction.journal_by_doi` | revue déduite de l'espace de noms du DOI | ▶ Revues non renseignées, identifiables par le DOI du document ; └─ N rattachements… |
| `metadata_correction.unary` | corrections par document | ▶ Corrections de métadonnées par document ; ├─ examinés ; ├─ corrigés ; └─ Terminé en… |
| `metadata_correction.cluster` | corrections de DOI par confrontation | ▶ Corrections de DOI par confrontation de documents ; ├─ ; ├─ ; └─ |

## publications

| Nœud | Étape | Journal |
|---|---|---|
| `publications.reconcile` | regroupement des notices marquées, puis recalcul des publications | ▶ N documents examinés ; ├─ résolus en… ; └─ Terminé en… ; ▶ Recalcul des métadonnées consolidées ; └─ barre |
| `publications.delete_without_sources` | publications sans notice | ▶ Publications sans source ; └─ N supprimées, si N > 0 |

## persons

| Nœud | Étape | Journal |
|---|---|---|
| `persons.resolve` | épinglages réappliqués | « Épinglages réappliqués… », sans section ni branche, si N > 0 |
| `persons.resolve` | identifiants mal placés et conflits d'attribution | ▶ Identifiants mal placés et conflits d'attribution ; ├─ ; └─ |
| `persons.resolve` | prénoms réduits complétés ; passe d'identification | ▶ Identification des personnes ; ├─ ; ├─ barre ; └─ N identifications, dont… |
| `persons.resolve` | passe de création | ▶ Création de nouvelles personnes ; ├─ ; ├─ barre ; └─ N personnes créées |
| `persons.resolve` | détachement des signatures cross-source sans ancre | aucun |
| `persons.populate_person_name_forms` | formes de nom des personnes | ▶ Rafraîchissement des formes de nom associées aux personnes ; └─ Terminé en… |
| `persons.resolve` | purge : signatures ambiguës, attributions automatiques sans appui, personnes vides | (même ligne) |

## authorships

| Nœud | Étape | Journal |
|---|---|---|
| `authorships.build` | purge complète avec `--rebuild-authorships` ; paires créées et supprimées ; attributs propagés | ▶ Reconstruction complète ; ▶ Liens publication-personne ; ├─ ; └─ ; ▶ Synchronisation des tables |
| `authorships.publications_in_perimeter` | `in_perimeter` des publications | └─ Terminé en… (ligne commune) |
| `authorships.structures` | vues `authorship_structures`, `publication_structures` | (même ligne) |
| `authorships.purge_orphan_publications` | publications sans signature du périmètre, par lots | aucun |
| `authorships.delete_empty_containers` | monographies, revues, éditeurs vides | ▶ Référentiels vides ; ├─ ; ├─ ; └─ |
| `authorships.pub_counts` | décomptes des adresses, revues, éditeurs | ▶ Recalcul des décomptes de publications ; ├─ ; ├─ ; └─ |

## relations, subjects, countries, oa_status

| Nœud | Étape | Journal |
|---|---|---|
| `relations.rebuild` | reconstruction complète de `publication_relations` | ▶ N nouvelles relations entre publications, ou ▶ Relations entre publications ; └─ |
| `subjects.ingest` | sujets des publications nouvelles ou modifiées | ▶ Liens publications-sujets ; ├─ ; └─ barre |
| `subjects.usage` | décomptes, vue des cooccurrences | ▶ Rafraîchissement des décomptes ; ├─ ; └─ |
| `countries.detect` | noms de pays dans les adresses | ▶ Recherche de noms de pays dans les adresses ; ├─ ; └─ |
| `countries.detect` | noms de villes et d'institutions | ▶ Détermination du pays par noms de villes ou d'institutions ; ├─ ; └─ |
| `countries.suggest` | pays par similitude d'adresses | ▶ Détermination du pays par similitude d'adresses ; └─ |
| `countries.refresh_publication_countries` | pays des notices et des publications | ▶ Rafraîchissement des pays associés aux publications ; └─ |
| `oa_status.verify_unpaywall` | statut open access (Unpaywall) | ▶ Vérification du statut open access sur Unpaywall ; ├─ ; ├─ barre ; └─ |
