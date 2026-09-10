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

- **La substitution exige un préfixe égal**, pour `IsVersionOf` comme pour `IsVariantFormOf`. Un traitement propre à `IsVariantFormOf` est écarté : ses 8 cas à préfixe égal relèvent de la version → concept.
- **À préfixe différent, la relation va à la phase `relations`**, au lieu de substituer le DOI. Le preprint et l'article restent deux publications, reliées.
- **Aucune reprise en base.** L'étape de correction repart du DOI d'origine à chaque run et le restitue quand elle ne décide rien. La revue déduite du préfixe se réévalue de la même façon.
- **L'ordre des sous-étapes reste inchangé.** Réservée au préfixe égal, la substitution laisse intact le préfixe dont se déduit la revue.

## Phasage

### 1. Substitution réservée au préfixe égal

- [x] `resolve_cluster_doi_corrections` : substitution seulement quand le DOI d'origine et le DOI cible ont le même préfixe.
- [x] Tests : `IsVersionOf` à préfixe égal substitué, `IsVersionOf` à préfixe différent laissé, idem pour `IsVariantFormOf`, DOI d'origine restitué à une notice déjà substituée.

### 2. Relations de même œuvre à préfixe différent

- [x] `relations.py` : `IsVersionOf` et `IsVariantFormOf` produisent une relation quand les deux DOI diffèrent de préfixe.
- [x] Tests : notice arXiv face à l'article publié donne `is_preprint_of` ; copie de dépôt face à l'article donne `is_related_to`.

Les phases 1 et 2 partent ensemble : sans la seconde, les publications se scindent sans relation entre elles.

### 3. Run et contrôle

- [ ] Nombre de publications scindées, à confronter aux 2 433 et 937 publications concernées.
- [ ] Nombre de relations `is_preprint_of` créées.
- [ ] Notices DataCite arXiv encore typées `article` : environ 2 200 avant le chantier.
- [ ] Revue des publications 2, 7 et 37 dans l'interface.

## Questions ouvertes

- **Copies de dépôt.** Les copies CERN, RWTH et GSI sont typées `article` et reçoivent `is_related_to` face à l'article publié. Un audit dira si elles méritent un autre traitement.
