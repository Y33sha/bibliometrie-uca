# Chantier — Preprints et versions d'une publication

## Contexte

Un preprint forme une publication distincte, reliée à l'article par `is_preprint_of`. Une version converge avec l'article seulement sous un même préfixe DOI : une copie déposée de la version publiée rejoint l'article, un preprint arXiv reste à part.

OpenAlex suit un autre modèle : un work réunit le preprint et l'article, le preprint y est une localisation `submittedVersion`. Les localisations OpenAlex (`source_record_locations`) suivent ce modèle : la copie arXiv figure parmi les localisations de l'article, alors que l'enregistrement DataCite arXiv forme sa propre publication.

Mesures du 2026-10-25, sur une base proche de la production :

- 1 468 preprints du périmètre ont leur article en base (1 488 relations `is_preprint_of`). Une liste ou une statistique sans filtre de type compte les deux.
- 2 352 des 4 357 enregistrements DataCite arXiv sont typés `article`, d'après leur type brut. Ils étaient rattachés à ArXiv.org par leur préfixe DOI, ce qui les typait `preprint` (`JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT`). Le rattachement de revue par préfixe DOI a été retiré (`e612fed85`), et les espaces de noms DOI qui le remplacent excluent les serveurs de preprints. 184 des 1 148 publications à DOI arXiv ont un autre type que `preprint`.
- Sur 6 080 localisations arXiv en `submittedVersion` d'une publication autre qu'un preprint, 5 051 désignent un preprint qui n'a pas de publication propre.
- 189 paires de publications partagent un identifiant arXiv sans être typées preprint. Dans 135 paires, l'une des deux a un DOI arXiv. Les autres réunissent une communication et un article (27), un erratum ou un addendum et son article (6), un jeu de données et son article (5), deux publications de même type (16). Parmi ces dernières, des copies d'entrepôt restent séparées de leur article (Apollo `10.17863`, DESY `10.3204`), et des identifiants arXiv sont attribués à tort.

## Décisions

- La question est distincte du modèle des conteneurs : les localisations se rangent par enregistrement source, et le type d'une plateforme vient d'une liste fermée, quel que soit le modèle retenu ici.

## Phasage

### Phase 1 — Modèle

- [ ] Choix entre preprint publication distincte et preprint version déposée de l'article.

### Phase 2 — Type des preprints arXiv

- [ ] Type `preprint` d'après le préfixe DOI du serveur (liste fermée du chantier [Modèle des conteneurs](archived/2026-10-25_DATA_modele-des-conteneurs.md)), ou convergence avec l'article, selon le modèle retenu. 184 publications.

### Phase 3 — Statistiques

- [ ] Exclusion des preprints des statistiques ou non, selon le modèle retenu.

## Questions ouvertes

- **Preprint : publication distincte ou version déposée ?** Adopter le modèle d'OpenAlex ferait converger les versions quel que soit le préfixe DOI, et remplacerait `is_preprint_of` par la version des localisations. Un preprint jamais publié resterait une publication de type preprint. La version des localisations d'entrepôt est peu fiable chez OpenAlex comme chez Unpaywall : 200 949 localisations d'entrepôt sur 258 875 sont en `submittedVersion`, y compris dans Cairn, qui héberge des versions publiées.
