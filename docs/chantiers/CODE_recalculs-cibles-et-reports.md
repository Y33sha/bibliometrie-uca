# Chantier — Recalculs ciblés et reports au run suivant

## Contexte

L'API déclenche sept recalculs du pipeline après une édition. Ils sont exportés par `pipeline/public.py` :

- clôture des périmètres, après l'édition d'un périmètre, d'une structure ou d'une tutelle ;
- `in_perimeter` des signatures, après la revue d'une adresse ;
- `in_perimeter` des publications, après l'exclusion d'une personne ;
- construction des authorships, à l'attribution de signatures orphelines ;
- pays des notices et des publications d'un lot d'adresses ;
- requalification des publications d'une revue, et fusion de revues ;
- `pub_count` d'un éditeur fusionné.

Le pipeline reporte aussi des traitements au run suivant. `pipeline/graph.py` déclare 39 lectures de données du run précédent (`previous_run`). D'autres données attendent le run suivant sans lecture à rebours : `fetch_missing` n'est pas récursif, donc un document rapatrié déclenche ses propres recherches au run suivant.

## Décisions

- Un recalcul ciblé se garde seulement s'il produit un effet immédiat attendu dans l'interface.

## Phasage

### Phase 1 — Inventaire

- [x] Pour chaque recalcul ciblé : l'édition qui le déclenche, l'effet visible dans l'interface, le délai sans lui.
- [x] Pour chaque report : la donnée concernée, le retard qu'il introduit.
- [ ] Pour chaque report : le coût de sa suppression.

Code au 2026-10-12. Le mode `daily` rejoue toutes les phases de transformation. Sans recalcul ciblé, une édition attend donc au plus un jour.

#### Recalculs ciblés

| Recalcul | Édition qui le déclenche | Exécution | Effet visible | Rattrapé au run suivant par |
|---|---|---|---|---|
| Clôture des périmètres (`PerimeterQueries`) | création ou modification d'un périmètre, suppression d'une structure, ajout ou retrait d'une tutelle | dans la requête | listes et statistiques filtrées par périmètre : elles lisent `perimeter_structures` | la tête du run (`run.py`), puis `affiliations` |
| `in_perimeter` des signatures (`InPerimeterRecompute`) | confirmation ou rejet d'un lien adresse-structure | tâche de fond | appartenance au périmètre des signatures et des authorships concernées | `affiliations.populate`, puis `authorships` |
| `in_perimeter` des publications d'une personne (`PublicationPerimeterRecompute`) | exclusion d'une personne | dans la requête | publications de la personne retirées des listes du périmètre | `authorships.publications_in_perimeter` |
| Authorships d'orphelines (`AuthorshipsBuild`) | attribution de signatures orphelines à une personne | dans la requête | les publications apparaissent sur la fiche de la personne | `authorships.build` |
| Pays des notices et des publications (`CountryQueries`) | attribution manuelle de pays à des adresses | tâche de fond | pays des publications (facettes, collaborations) | **rien** : voir ci-dessous |
| Requalification d'une revue (`JournalRecompute.requalify_publications`) | changement de `journal_type` d'une revue | dans la requête | `doc_type` des publications de la revue | `metadata_correction.unary`, qui relit toutes les notices |
| `pub_count` d'un éditeur (`PubCountRecompute`) | fusion d'éditeurs | dans la requête | nombre de publications de l'éditeur conservé | `authorships.pub_counts` |

Constats :

- **Pays** : les éditions de l'administration écrivent `addresses.countries` sans poser `countries_dirty`. Or `countries.refresh_publication_countries` recalcule seulement les lignes marquées. Sans le recalcul ciblé, une édition de pays n'atteint jamais les publications.
- **Fusion de revues** (`JournalRecompute.merge_journals`) : c'est l'opération elle-même, partagée avec `publishers_journals.merge_duplicate_journals`, pas un recalcul. Elle reste exposée quelle que soit la décision.

#### Reports au run suivant

`pipeline/graph.py` déclare ses lectures `previous_run` table par table. La plupart relisent l'état que le nœud a lui-même écrit : calcul incrémental, sans retard. Sont dans ce cas `extract` (`staging`, date de la dernière extraction quotidienne), `fetch_stale` et `fetch_truncated` (`staging`), `normalize` (ses tables et les référentiels qu'il complète), `persons`, `subjects`, `countries.suggest`, `affiliations.refresh_ror` et `affiliations.resolve_addresses`.

Restent les lectures d'une donnée qu'un nœud placé plus loin écrit :

| Nœud | Donnée du run précédent | Écrite plus loin par | Retard |
|---|---|---|---|
| `fetch_missing.*` | DOI et identifiants des notices, `publications.in_perimeter`, cibles des relations, agence des préfixes DOI | `normalize`, `authorships`, `relations`, `resolve_ra` | un document rapatrié déclenche ses propres recherches au run suivant ; une chaîne de *n* rebonds prend *n* runs |
| `fetch_stale.*` | `source_publications.pub_year`, qui borne la fenêtre d'années | `normalize` | un document sans notice normalisée est toujours relu |
| `resolve_ra.resolve_prefixes` | `publication_relations.target_doi` | `relations.rebuild` | le préfixe d'une cible de relation est résolu un run plus tard ; la cible est cherchée par `fetch_missing` un run après |
| `publishers_journals.merge_duplicate_journals` | `source_publications.publication_id` (revues des notices d'une même publication) | `publications.reconcile` | deux revues réunies par une publication nouvelle fusionnent un run plus tard |
| `publishers_journals.check_journals_in_sudoc`, `publishers_journals.link_monographs_to_collections` | `source_publications.journal_id` | `metadata_correction.journal_by_doi` | une revue rattachée par l'espace de noms de son DOI est vérifiée un run plus tard |
| `publishers_journals.type_proceedings_journals`, `publishers_journals.type_proceedings_volumes` | `source_publications.doc_type` corrigé, `raw_metadata` | `metadata_correction.unary` | le typage en actes lit le type corrigé au run précédent |
| `publications.reconcile` | `source_publications.countries` | `countries.refresh_publication_countries` | aucun : `countries` réécrit `publications.countries` dans le même run |

Restent à classer, colonne par colonne : les lectures de `publications` déclarées à la table entière par `authorships.*`, `relations.rebuild`, `subjects.ingest` et `countries.refresh_publication_countries`. Les nœuds suivants écrivent d'autres colonnes de `publications` (`in_perimeter`, `subjects_ingested_at`, `countries`, `oa_status`) et suppriment des lignes (`authorships.purge_orphan_publications`).

### Phase 2 — Décisions

- [ ] Garder ou retirer chaque recalcul ciblé.
- [ ] Garder ou supprimer chaque report.

### Phase 3 — Mise en œuvre

- [ ] Retirer les recalculs écartés, leur port et leur export dans `pipeline/public.py`.
- [ ] Supprimer les reports écartés, et mettre à jour leurs déclarations dans `pipeline/graph.py`.

## Questions ouvertes

- Une donnée laissée au run suivant : l'interface signale-t-elle qu'elle attend un recalcul ?
