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
- Les sept recalculs ciblés sont gardés : chacun produit un effet immédiat attendu dans l'interface.
- Une écriture de pays par l'administration marque l'adresse `countries_dirty` : le run suivant reprend une propagation échouée en tâche de fond.
- `fetch_missing` garde son report : un jour par rebond. Supprimer ce retard demanderait une seconde passe de transformation, ou une boucle jusqu'à épuisement des recherches. L'appartenance au périmètre, que `fetch_missing` lit, s'obtient au bout d'étapes qui travaillent sur l'ensemble du corpus (affiliations, réconciliation, authorships) : un traitement notice par notice ne suffirait pas.
- `fetch_stale` garde son report : l'année d'un document se lit dans sa notice du run précédent. Seul un document dont l'année a changé dans sa source est filtré à tort, une fois.
- `resolve_ra` garde son report : la cible d'une relation dont le préfixe est inconnu est cherchée dans Crossref ou DataCite un run plus tard. Le cas est rare, et un second passage de `resolve_ra` ne se justifie pas pour si peu.
- La fusion des revues que relie une même publication garde son report : une revue reste en double un jour, quand une publication nouvelle est seule à relier deux entrées. Rejouer la fusion après la réconciliation obligerait à refaire les corrections et les métadonnées des publications touchées.
- La vérification Sudoc et le rattachement des monographies à leur collection gardent leur report : ils voient au run suivant les revues que `journal_by_doi` rattache. Les notices ainsi rattachées ne donnent aucun ISSN à vérifier ; seule la collection d'un volume d'actes peut être posée un jour plus tard.
- Le typage en actes des revues et des volumes garde son report. Il lit le type brut de la source, que la correction ne change pas. Seul le `journal_id` posé par `journal_by_doi` arrive un run plus tard, comme pour la vérification Sudoc.
- Les lectures de `publications` au run précédent sont déclarées colonne par colonne. Seules celles de `fetch_missing` introduisent un retard.

## Phasage

### Phase 1 — Inventaire

- [x] Pour chaque recalcul ciblé : l'édition qui le déclenche, l'effet visible dans l'interface, le délai sans lui.
- [x] Pour chaque report : la donnée concernée, le retard qu'il introduit.
- [x] Pour chaque report : le coût de sa suppression.

Code au 2026-10-12. Le mode `daily` rejoue toutes les phases de transformation. Sans recalcul ciblé, une édition attend donc au plus un jour.

#### Recalculs ciblés

| Recalcul | Édition qui le déclenche | Exécution | Effet visible | Rattrapé au run suivant par |
|---|---|---|---|---|
| Clôture des périmètres (`PerimeterQueries`) | création ou modification d'un périmètre, suppression d'une structure, ajout ou retrait d'une tutelle | dans la requête | listes et statistiques filtrées par périmètre : elles lisent `perimeter_structures` | la tête du run (`run.py`), puis `affiliations` |
| `in_perimeter` des signatures (`InPerimeterRecompute`) | confirmation ou rejet d'un lien adresse-structure | tâche de fond | appartenance au périmètre des signatures et des authorships concernées | `affiliations.populate`, puis `authorships` |
| `in_perimeter` des publications d'une personne (`PublicationPerimeterRecompute`) | exclusion d'une personne | dans la requête | publications de la personne retirées des listes du périmètre | `authorships.publications_in_perimeter` |
| Authorships d'orphelines (`AuthorshipsBuild`) | attribution de signatures orphelines à une personne | dans la requête | les publications apparaissent sur la fiche de la personne | `authorships.build` |
| Pays des notices et des publications (`CountryQueries`) | attribution manuelle de pays à des adresses | tâche de fond | pays des publications (facettes, collaborations) | `countries.refresh_publication_countries`, par le marqueur `countries_dirty` que pose chaque écriture de pays |
| Requalification d'une revue (`JournalRecompute.requalify_publications`) | changement de `journal_type` d'une revue | dans la requête | `doc_type` des publications de la revue | `metadata_correction.unary`, qui relit toutes les notices |
| `pub_count` d'un éditeur (`PubCountRecompute`) | fusion d'éditeurs | dans la requête | nombre de publications de l'éditeur conservé | `authorships.pub_counts` |

La fusion de revues (`JournalRecompute.merge_journals`) est l'opération elle-même, partagée avec `publishers_journals.merge_duplicate_journals`.

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
| `publishers_journals.type_proceedings_journals`, `publishers_journals.type_proceedings_volumes` | `source_publications.journal_id`, type brut de la notice | `metadata_correction.journal_by_doi` | une revue rattachée par l'espace de noms de son DOI est typée un run plus tard ; le type brut est à jour |
| `publications.reconcile` | `source_publications.countries` | `countries.refresh_publication_countries` | aucun : `countries` réécrit `publications.countries` dans le même run |

Lectures de `publications` sans retard :

- `authorships.build`, `authorships.publications_in_perimeter` et `publications.delete_without_sources` lisent des lignes que `authorships.purge_orphan_publications` supprime plus loin dans le même run.
- `publications.reconcile` lit le statut confirmé par Unpaywall (`oa_status`, `unpaywall_checked_at`). Une publication créée dans le run est vérifiée par `oa_status` le même jour.

### Phase 2 — Décisions

- [x] Garder ou retirer chaque recalcul ciblé : tous gardés.
- [x] Garder ou supprimer chaque report : tous gardés.

### Phase 3 — Mise en œuvre

- [x] Déclarer dans `pipeline/graph.py` les lectures du run précédent à la colonne près.

## Questions ouvertes

