# Chantier — Preprints fusionnés avec leur article par substitution de DOI

## Contexte

La phase `metadata_correction` fait converger les formes secondaires d'une œuvre sur son DOI principal. Deux relations DataCite déclenchent cette substitution ([shared_doi.py](../../domain/source_publications/metadata_correction/shared_doi.py)) :

- `IsVersionOf` : version → concept ;
- `IsVariantFormOf` : forme variante → version publiée.

La substitution s'applique à toutes les notices qui partagent le DOI d'origine, quelle que soit leur source. Les notices au même DOI rejoignent ensuite la même publication.

Les notices arXiv de DataCite déclarent `IsVersionOf` vers le DOI de l'article publié. Leur DOI `10.48550/arxiv…` est donc remplacé par celui de l'article, et le preprint fusionne avec l'article dans la même publication. Les copies déposées au CERN (`10.3204`), à RWTH (`10.18154`) ou au GSI (`10.15120`) déclarent `IsVariantFormOf` vers l'article et fusionnent de la même façon.

| Relation | Corrections | Préfixe changé | Publications concernées |
|---|---|---|---|
| `IsVersionOf` | 7 214 | 4 407, dont 4 390 depuis arXiv | 2 433 |
| `IsVariantFormOf` | 1 219 | 1 211 | 937 |

À préfixe égal, la substitution est juste : versions Zenodo (`10.5281`, 2 243 corrections), `10.60692` (485), et 8 formes variantes Zenodo ou PANGAEA.

Exemples de publications fusionnées : 2, 7, 8, 9, 14 (preprint arXiv et article), 37, 89, 96, 131 (copie de dépôt, preprint et article).

La substitution fausse aussi la revue. L'étape qui déduit la revue du préfixe DOI lit le DOI substitué : 1 327 notices DataCite arXiv portent la revue de l'article publié.

La phase `relations` écarte les relations de même œuvre, qu'elle laisse à la déduplication ([relations.py](../../domain/publications/relations.py)). Elle type déjà une relation d'après le couple de types de documents : un preprint face à un article donne `is_preprint_of`.

La revue ArXiv.org porte le type `preprint_server` et le préfixe `10.48550`. La règle `JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT` type donc en `preprint` toute notice qui lui est rattachée.

## Décisions

- **Une version exige un préfixe égal** (`IsVersionOf`). Une copie de repository rejoint la forme publiée quel que soit le préfixe (`IsVariantFormOf`), sauf une notice `preprint`. La correction de DOI et la phase `relations` lisent cette règle dans `meme_oeuvre_declaree`.
- **À préfixe différent, la relation va à la phase `relations`**, au lieu de substituer le DOI. Un preprint qui a sa propre publication est relié à l'article.
- **Une notice sans publication le reste.** Une notice DataCite absente des sources du périmètre ne crée pas de publication : son auteur UCA figure par son seul nom, sans structure ni identifiant. L'article publié couvre le document, et sa notice OpenAlex porte souvent l'identifiant arXiv.
- **Aucune reprise en base.** L'étape de correction repart du DOI d'origine à chaque run et le restitue quand elle ne décide rien. La revue déduite du préfixe se réévalue de la même façon.
- **L'ordre des sous-étapes reste inchangé.** L'étape qui déduit la revue du DOI renseigne seulement les revues absentes, et une copie de repository porte en général celle de l'article.

## Phasage

### 1. Substitution réservée au préfixe égal

- [x] `resolve_cluster_doi_corrections` : substitution seulement quand le DOI d'origine et le DOI cible ont le même préfixe.
- [x] Tests : `IsVersionOf` à préfixe égal substitué, `IsVersionOf` à préfixe différent laissé, DOI d'origine restitué à une notice déjà substituée.

### 2. Relations de même œuvre à préfixe différent

- [x] `relations.py` : `IsVersionOf` et `IsVariantFormOf` produisent une relation quand les deux DOI diffèrent de préfixe.
- [x] Tests : notice arXiv face à l'article publié donne `is_preprint_of`.

Les phases 1 et 2 partent ensemble : sans la seconde, les publications se scindent sans relation entre elles.

### 3. Run et contrôle

- [x] Publications scindées : 3 848 créées au premier run. Restent sans publication 2 237 notices arXiv et 871 copies de repository.
- [x] Relations `is_preprint_of` issues des déclarations DataCite : 765.
- [x] Notices DataCite arXiv typées `article` : aucune. Les 3 572 notices sont typées `preprint` et rattachées à ArXiv.org.
- [x] Publications 2, 7 et 37 : chacune contient les seules notices de l'article. Les copies RWTH forment des publications distinctes, reliées par `is_related_to`.

### 4. Fusions résiduelles

- [x] Publications 57821, 152027, 170655 et 204355 : la notice arXiv partageait la publication de l'article, sans substitution de DOI. Marquées `keys_dirty` puis retraitées, les notices arXiv forment les publications 217991 à 217994.

### 5. Copies de repository fusionnées avec l'article

L'audit des 735 publications de copies CERN, RWTH et GSI montre des notices de repository de l'article publié : même titre aux formules près, année à un an près, rattachement à la revue par l'ISSN. Les copies typées `preprint` sont des working papers.

- [x] `meme_oeuvre_declaree` : une copie `IsVariantFormOf` converge sur la forme publiée quel que soit le préfixe, sauf une notice `preprint`.
- [x] Tests : copie de l'article convergente, copie de preprint distincte et reliée par `is_preprint_of`.
- [x] La règle lit le type de la notice DataCite qui mentionne la cible, et ignore celui des autres notices au même DOI. Une notice qui mentionne plusieurs cibles converge sur la version plutôt que sur la variante.
- [ ] Run et contrôle : les publications de copies rejoignent leur article.

## Questions ouvertes

- **Déclaration erronée.** `10.3204/pubdb-2019-03026`, copie d'un article sur les squarks bottom, déclare `IsVariantFormOf` vers un article sur W±Z. La fusion la rattache à tort : cas à défaire dans l'outil admin de dédoublonnage.
- **Revue « II ».** 51 copies typées `preprint` sont rattachées à une revue intitulée « II ». Origine non recherchée.
