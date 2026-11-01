# Chantier — Mesures d'impact

## Contexte

**Indicateurs par enregistrement source.** La colonne JSONB `source_records.impact` contient les indicateurs de citation de chaque enregistrement source (`domain/source_records/impact.py`). OpenAlex, Crossref, DataCite, WoS et ScanR donnent un nombre de citations, chacun compté dans sa propre base. Seul OpenAlex donne le FWCI et le percentile de citations normalisé, avec les seuils top 10 % et top 1 %.

**Colonne écrite, jamais lue.** La normalisation écrit `impact`. La consolidation (`refresh_from_sources`, phase `publications`), l'API et le frontend ne la lisent pas. La table `publications` ne contient aucun indicateur de citation.

**Couverture**, mesurée sur la base locale, 76 755 publications du périmètre :

- 68 015 ont un enregistrement source OpenAlex, 54 156 un FWCI.
- Le FWCI couvre 96 % des articles présents dans OpenAlex. Il manque pour les thèses (16 sur 1 991), les preprints (47 sur 1 877) et le type `other` (107 sur 2 530).
- 8 740 publications sont absentes d'OpenAlex. 3 823 d'entre elles ont un nombre de citations d'une autre source.

**Plusieurs enregistrements OpenAlex dans une publication** : 5 543 publications.

- 1 735 réunissent un preprint et sa version publiée. Leurs nombres de citations diffèrent dans 1 243 cas.
- 3 808 sans preprint : thèses (1 097), jeux de données (989), articles (886)…
- 1 425 ont plusieurs FWCI.

**Âge des publications.** Le nombre moyen de citations des publications pourvues d'un FWCI passe de 25,8 (2018) à 0,6 (2026). Le FWCI moyen reste entre 1,16 et 2,04, la part dans le top 10 % entre 12 % et 19 % : ces deux indicateurs se normalisent par année.

**Moteur des statistiques** (`infrastructure/read_models/stats/pivot.py`). Un indicateur agrège une mesure additive sur chaque groupe : nombre de publications, montant des APC. Une dimension empilée ventile chaque barre. Une part (top 10 %) ou une moyenne (FWCI) ne s'additionne pas, donc ne s'empile pas.

**Dashboards.** Les dashboards de structure, de personne, d'éditeur et de revue (`PublicationsDashboard.svelte`) passent par le même moteur. Chiffres clés : publications, part en open access, part de collaborations internationales, thèses. Corpus : famille « Publications », cinq dernières années, année en cours comprise.

## Décisions

- **Colonne JSONB `publications.impact`**, de même forme que `source_records.impact`. Un fragment SQL par indicateur sert au tri, au filtre et aux statistiques.
- **Les indicateurs viennent du premier enregistrement OpenAlex dans l'ordre d'arbitrage** (`arbitration_order`), donc de la version publiée avant le preprint. Ils décrivent ainsi la même œuvre, comptée dans la même base. Une publication absente d'OpenAlex est sans indicateur.
- **La phase `publications` pose les indicateurs** (`refresh_from_sources`). Un réimport (moissonnage, `fetch_stale`) marque l'enregistrement source pour cette phase. Les indicateurs suivent donc les sources.
- **Indicateurs de ratio dans le moteur des statistiques.** Un ratio s'affiche en une valeur par barre, sans ventilation empilée. Son dénominateur compte les publications pourvues de l'indicateur. La couverture s'affiche avec la valeur. Une ligne marque la référence mondiale : 10 % pour le top 10 %, 1 pour le FWCI.
- **Indicateurs de la page Statistiques** : « Nombre de citations », mesure additive ventilée par statut d'accès ; « Part dans le top 10 % » et « FWCI moyen », ratios.
- **Dashboards de structure, d'éditeur et de revue** : chiffres clés « dans le top 10 % » et « FWCI moyen », avec leur couverture. Beeswarm : un point par publication, années en abscisse, citations ou FWCI en ordonnée.
- **Liste des publications** : colonnes « Citations », « FWCI », « Top 10 % » ; tri par citations et par FWCI ; mêmes colonnes à l'export CSV ; filtre « Top 10 % » dans la barre de filtres commune à la page Statistiques.
- **Fiche d'une publication** : les trois indicateurs. Volet d'administration : nombre de citations de chaque enregistrement source.

## Phasage

### 1. Schéma et consolidation

- [ ] Migration : colonne `publications.impact`, contrainte d'objet JSON. Snapshot du schéma.
- [ ] `SourceRecord` contient ses indicateurs, lus par `source_records_of`.
- [ ] Règle d'agrégation (`domain/publications/aggregation.py`) et ses tests ; écriture par `PublicationStore`.
- [ ] Documentation : modèle de données, phase `publications`.
- [ ] Stock : `run_pipeline --only publications --rebuild-publications`.

### 2. Liste et fiche d'une publication

- [ ] Fragment SQL de chaque indicateur, partagé par la liste, les filtres et les statistiques.
- [ ] API : indicateurs dans la liste, la fiche, le volet d'administration et l'export CSV ; tri ; filtre « Top 10 % » et sa facette.
- [ ] Interface : colonnes, tri, filtre ; fiche ; volet.

### 3. Statistiques

- [ ] Moteur : indicateurs de ratio, avec dénominateur et couverture.
- [ ] Indicateurs « Nombre de citations », « Part dans le top 10 % », « FWCI moyen ».
- [ ] Interface : graphique d'un ratio, ligne de référence, couverture.

### 4. Dashboards

- [ ] Chiffres clés des dashboards de structure, d'éditeur et de revue.
- [ ] API : points du beeswarm, une publication par point.
- [ ] Beeswarm des citations ou du FWCI par année.
- [ ] Guide utilisateur : définition, source et couverture de chaque indicateur.

## Questions ouvertes

- **Beeswarm d'une grande structure** : l'établissement compte environ 40 000 publications sur cinq ans, autant de points. Réserver le beeswarm aux laboratoires, ou passer à une densité au-delà d'un seuil ?
- **FWCI moyen ou médian** : quelques publications très citées élèvent la moyenne.
- **Top 1 %** : à afficher ?
- **Part dans le top 10 % ventilée** (par statut d'accès, par type de document), en barres groupées ?
- **Graphe des citations de l'établissement** : stocker les publications citées et citantes ? OpenAlex donne les références de chaque work (`referenced_works`), absentes des champs demandés (`SELECT_FIELDS`). Les références des publications du périmètre suffisent aux citations internes à l'établissement. Les publications citantes extérieures demandent des requêtes supplémentaires (filtre `cites`).
