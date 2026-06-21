# Relations entre publications

Phase `relations` : peuple la table `publication_relations`, qui relie des publications **distinctes** — et non des doublons, ceux-là étant déjà fusionnés en amont. Une relation rattache une publication à une œuvre apparentée : un preprint à sa version publiée, un supplément de données à son article, un chapitre à son ouvrage, un erratum à l'article qu'il corrige, un data paper au jeu de données qu'il décrit.

La phase tourne après `publications` : les `source_publications` sont rattachées à leur publication canonique, ce qui permet de résoudre les cibles vers des publications du référentiel.

## Deux signaux

La table est reconstruite à chaque run, à partir de deux signaux indépendants.

**Relations déclarées par les sources.** DataCite et Crossref publient des relations typées entre DOI (preprint, supplément, partie, correction, traduction…). La phase les lit dans les métadonnées des `source_publications` et les traduit vers un vocabulaire de types unifié. Elle écarte ce qui sort du périmètre : les citations (qui relèvent du graphe bibliographique), les versions d'une même œuvre (traitées en déduplication, phase `metadata_correction`) et les rapports d'évaluation.

**Clés de confirmation partagées.** Deux publications qui partagent une clé d'identité (HAL id, arXiv, PMID, NNT) mais portent des DOI distincts n'ont pas fusionné — la règle « deux DOI distincts ne désignent jamais le même document » l'interdit. Elles n'en sont pas moins apparentées : c'est typiquement un preprint et sa version publiée. Le type de la relation se déduit du couple de types (preprint + article → preprint ↔ version publiée). Quand le couple ne permet pas de conclure, la relation est posée sans type précis, en attendant d'être qualifiée.

## Direction et réciprocité

Chaque relation est orientée et porte un type qui en exprime le sens (« est le preprint de », « complète », « corrige »). Chaque type a son inverse, ce qui permet de lire la relation depuis l'une ou l'autre extrémité : la fiche d'une publication présente aussi bien les œuvres qu'elle désigne que celles qui la désignent.

## Rapatriement des cibles

Les DOI cibles encore absents du corpus rejoignent l'ensemble interrogé par les [imports croisés](02-extract.md#cross-imports) : une œuvre liée accessible dans une source finit par entrer, et la relation se résout alors vers sa publication.

> **Évolutions envisagées**
> - Rapprocher par le titre les œuvres dépendantes (erratum, rétractation, données, preprint) restées sans relation, lorsqu'aucune clé ni relation déclarée ne les rattache à leur publication d'origine.
