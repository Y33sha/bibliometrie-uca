# Exemple de publication vue par différentes sources

Titre : *Mixed data k-Anonymization by Consistent Maximal Association and Microaggregation*. DOI : [10.1145/3746252.3761293](https://doi.org/10.1145/3746252.3761293).

Les tableaux montrent cette publication. Les proportions portent sur les 72 396 publications du périmètre présentes dans au moins deux sources, au 2026-10-30.

## Publication

| Source | Titre |
|---|---|
| Crossref | `Mixed data <i>k</i> -Anonymization by Consistent Maximal Association and Microaggregation` |
| ScanR | `Mixed data k -Anonymization by Consistent Maximal Association and Microaggregation` |
| HAL | `Mixed data k -Anonymization by Consistent Maximal Association and Microaggregation` |
| OpenAlex | `Mixed data k -Anonymization by Consistent Maximal Association and Microaggregation` |
| Web of Science | `Mixed data k-Anonymization by Consistent Maximal Association and Microaggregation` |

Les sources donnent le même titre normalisé dans 88,5 % des cas. Ici, l'éditeur a mis le *k* en italique. Crossref transmet la balise. HAL, OpenAlex et ScanR retirent la balise mais gardent l'espace devant le tiret. Web of Science donne la seule chaîne propre.

| Source | Année | Type | Langue | DOI | Résumé |
|---|---|---|---|---|---|
| Crossref | 2025 | `conference_paper` | absente | présent | absent |
| HAL | 2025 | `conference_paper` | `en` | présent | absent |
| OpenAlex | 2025 | `conference_paper` | `en` | présent | 1 083 caractères |
| ScanR | 2025 | `conference_paper` | absente | présent | absent |
| Web of Science | 2025 | `conference_paper` | `English` | présent | 1 084 caractères |

**Année.** Les sources s'accordent dans 89,4 % des cas. Quand elles diffèrent, l'écart est d'une seule année quatre fois sur cinq. Les deux dates en cause sont la mise en ligne et la parution.

**Type de document.** Les sources s'accordent dans 83,2 % des cas, le plus faible taux. Chaque source a sa nomenclature — `proceedings-article` pour Crossref, `COMM` pour HAL, `conference-paper` pour OpenAlex, `proceedings` pour ScanR, `Proceedings Paper` pour Web of Science. On les ramène à un vocabulaire commun, ici `conference_paper`.

**Langue.** Ici, trois sources sur cinq la renseignent, dans deux formats.

## Actes

| Source | Valeur |
|---|---|
| Crossref, ScanR | `Proceedings of the 34th ACM International Conference on Information and Knowledge Management` |
| Web of Science | `PROCEEDINGS OF THE 34TH ACM INTERNATIONAL CONFERENCE ON INFORMATION AND KNOWLEDGE MANAGEMENT, CIKM 2025`, ISBN `9798400720406` |
| OpenAlex | `ACM International Conference on Information and Knowledge Management (CIKM)` |
| HAL | `CIKM '25: The 34th ACM International Conference on Information and Knowledge Management`, sans rattachement |

Les actes sont rattachés à une monographie, par ISBN puis par titre normalisé. Seul Web of Science donne l'ISBN. Il ajoute aussi au titre le sigle et l'année de la conférence. OpenAlex donne le nom de la série de conférences. Trois monographies coexistent donc pour un même volume.

## Éditeur

| Source | Valeur |
|---|---|
| Crossref, HAL | `ACM` |
| ScanR | `ACM Press` |
| Web of Science | `ASSOC COMPUTING MACHINERY` |
| OpenAlex | absent |

Les quatre noms désignent le titulaire du préfixe DOI `10.1145`, nommé `Association for Computing Machinery (ACM)` par Crossref. Chaque nom compatible est fusionné dans ce titulaire.

## Sujets

| Source | Valeur |
|---|---|
| Crossref | aucun |
| HAL | domaine `Statistiques [stat]/Machine Learning [stat.ML]` |
| OpenAlex | `Privacy-Preserving Technologies in Data` (1,0), `Data Quality and Management` (0,0), `Internet Traffic Analysis and Secure E-voting` (0,0) |
| ScanR | mots-clés `Anonymization`, `Maximal` |
| Web of Science | mots-clés d'auteur `Data privacy`, `Mixed-type data`, `k-anonymization`, `Microaggregation` ; catégories `Computer Science, Artificial Intelligence`, `Computer Science, Information Systems`, `Computer Science, Theory & Methods`, `Computer Science` |

Chaque source procède différemment. HAL donne les domaines choisis par le déposant. Web of Science donne les mots-clés fournis par les auteurs, plus ses propres catégories disciplinaires. OpenAlex calcule des topics pondérés par un score. ScanR donne ici deux mots du titre.

## Auteurs

| Source | Forme du nom | Identifiants du premier auteur | Identifiants du deuxième auteur |
|---|---|---|---|
| Crossref | `Julien Ah-Pine` | ORCID `0000-0001-6898-3961` | ORCID `0009-0004-4535-8644` |
| HAL | `Julien Ah-Pine` | idHAL `julien-ah-pine`, ORCID `0000-0001-6898-3961`, compte HAL `15506` | ORCID `0009-0004-4535-8644`, compte HAL `1623465` |
| OpenAlex | `Julien Ah-Pine` | ORCID `0000-0001-6898-3961` | ORCID `0009-0004-4535-8644` |
| ScanR | `Julien Ah-Pine` | IdRef `139791140`, ORCID `0000-0001-6898-3961` | IdRef `253123445`, ORCID `0000-0002-4302-1878` |
| Web of Science | `Ah-Pine, Julien` | aucun | aucun |

Web of Science donne toujours la forme « Nom, Prénom ». On rattache chaque contribution à une personne d'après ces noms et identifiants ([phase `persons`](../pipeline/09-persons.md)).

Les sources attribuent deux identifiants ORCID différents au deuxième auteur.

Part des contributions sources pourvues d'au moins un identifiant : theses.fr 94,7 %, ScanR 47,5 %, Crossref 36,4 %, DataCite 24,6 %, OpenAlex 19,8 %, Web of Science 11,2 %, HAL 6,1 %. Le décompte porte sur toutes les contributions sources, co-auteurs extérieurs compris : les publications à plusieurs centaines d'auteurs pèsent fortement.

## Adresses et structures

| Source | Adresses du premier auteur |
|---|---|
| Crossref | `Université Clermont Auvergne, Clermont Auvergne INP, CNRS, Mines Saint-Etienne, SIGMA Clermont, LIMOS, Clermont-Ferrand, France` |
| OpenAlex | même chaîne que Crossref |
| Web of Science | `Univ Clermont Auvergne, Clermont Auvergne INP, CNRS, Mines St Etienne,SIGMA Clermont,LIMOS, Clermont Ferrand, France` |
| HAL | `Centre d'Études et de Recherches sur le Développement International`, `Centre National de la Recherche Scientifique`, `École des Mines de Saint-Étienne`, `Institut de Recherche pour le Développement`, `Institut Mines-Télécom [Paris]`, `Institut national polytechnique Clermont Auvergne`, `Laboratoire d'Informatique, de Modélisation et d'Optimisation des Systèmes`, `Université Clermont Auvergne` |
| ScanR | aucune |

Crossref, OpenAlex et Web of Science donnent l'adresse imprimée dans l'article, entière ou abrégée. HAL donne des structures de son référentiel, sans adresse ; deux d'entre elles sont sans rapport avec l'article.
