# Chantier — Brevets

## Contexte

Le type de document `patent` existe. Les brevets en base viennent des dépôts HAL, repris par ScanR : 88 publications au 2026-11-04.

### API de propriété industrielle de l'INPI

- Base : `https://api-gateway.inpi.fr/services/apidiffusion/api/brevets/`. Documentation technique v1.0 du 2021-10-11, publiée sur inpi.fr.
- Couverture : demandes FR depuis 1902, demandes EP et WO depuis 1978. Mise à jour chaque vendredi.
- Connexion par compte technique (`INPI_API_USERNAME`, `INPI_API_PASSWORD`). `/auth/login` renvoie un jeton d'accès valable 5 minutes et un jeton de rafraîchissement. Chaque requête renvoie le jeton XSRF à relire dans les cookies.
- Recherche (`POST search`) en syntaxe INPI : nom ou SIREN du déposant, titulaire, inventeur, département du déposant (FR seulement), dates, CIB ou CPC. 500 résultats par page au plus, position de départ limitée à 500.
- Résultat de recherche : numéro de publication, titre, dates de dépôt et de publication, CIB, inventeurs, déposants.
- Détail d'une demande en XML (`GET notice/{numéro}`) : déposants et titulaires avec SIREN et adresse, inventeurs avec ville et code postal, identifiant de famille DOCDB, statut juridique, articles cités avec leur DOI.

Une famille de brevets réunit les demandes déposées auprès de plusieurs offices (FR, EP, WO, US…) pour une même invention. La famille DOCDB de l'Office européen des brevets réunit les demandes de priorités identiques.

### Sondages du 2026-11-02

| Requête | Demandes |
|---|---|
| SIREN de l'UCA | 50 |
| Déposant « université clermont auvergne » | 298 |
| Déposant « université blaise pascal » | 178 |
| Déposant « université » et « auvergne » | 312 |
| Département du déposant : 63 | 5 960 |

- Le SIREN du déposant est renseigné pour une partie des demandes FR, jamais pour les demandes WO.
- Les demandes EP et WO abrègent les noms des déposants : `UNIV CLERMONT AUVERGNE`, `CENTRE NAT RECH SCIENT`.
- L'adresse de l'inventeur est son adresse personnelle. Les demandes EP donnent seulement son pays.
- Un brevet nomme ses déposants, jamais le laboratoire.
- Le quota est de 100 requêtes par heure. La réponse 429 donne le délai d'attente dans `X-Rate-Limit-Retry-After-Seconds`.

### Open data du ministère de l'Enseignement supérieur et de la Recherche

Le portail `data.enseignementsup-recherche.gouv.fr` publie `deposants-des-brevets`, `demandes-de-brevets` et `fr-esr-familles-brevets`, mis à jour en mai 2026. Ces jeux sont tirés de PATSTAT, la base de l'Office européen des brevets. Ils couvrent les demandes déposées depuis 2010 dont une personne est localisée en France, auprès de tous les offices. Les déposants sont résolus en SIREN et en identifiant Paysage. Les inventeurs sont absents. Accès libre, sans compte.

### ScanR

L'index `scanr-patents` du cluster Elasticsearch de ScanR contient les familles des jeux du ministère. Une famille y réunit :

- les déposants, résolus en identifiants Paysage, SIREN et ROR ;
- les inventeurs, avec leur IdRef quand ScanR l'a trouvé, sans adresse ;
- les demandes de chaque office : numéros, dates de dépôt, de publication et de délivrance, lien Espacenet ;
- les articles cités par le brevet, avec leur DOI et les affiliations de leurs auteurs ;
- la classification CPC.

### HAL

Le champ `number_s` d'un dépôt HAL de type brevet contient son numéro en texte libre : numéro de publication ou de demande, parfois plusieurs, ou une référence interne. Exemples : `WO/2019/229378`, `N°FR3053353`, `EP 4 235 469 A1`, `DI-RV-22-0027`. Le moissonnage HAL demande ce champ.

### Inventaire du 2026-11-04

Familles dont un établissement du périmètre est déposant : UCA, Université Blaise Pascal, Université d'Auvergne, Clermont Auvergne INP, SIGMA Clermont, IFMA, ENSCCF.

| Source | Familles |
|---|---|
| INPI | 231, premier dépôt de 1982 à 2025 |
| ScanR | 156, premier dépôt depuis 2010 |
| HAL | 38 |

- Depuis 2010, 153 familles sont présentes à la fois à l'INPI et dans ScanR. 14 des 17 familles présentes seulement à l'INPI sont déposées en 2024 ou 2025.
- Le CNRS est co-déposant de la moitié des familles de l'INPI.
- HAL contient 88 brevets. 65 sont présents dans ScanR, dont 27 sans déposant du périmètre. 9 des 23 autres donnent une référence interne d'INRAE à la place d'un numéro de brevet.
- 90 personnes RH ont le nom et le prénom d'un inventeur des familles de l'INPI domicilié dans le Puy-de-Dôme.
- Dans ScanR, les identifiants Paysage des déposants du périmètre sélectionnent 154 familles : `K4lR3` et `FvH4k` (UCA), `n1E6T` (Université Blaise Pascal), `3itX6` (Université d'Auvergne), `cQN1f` (SIGMA Clermont), `S8ntZ` (Clermont Auvergne INP), `UedNx` (ENSCCF).
- 460 de leurs 903 inventeurs ont un IdRef. Sur 301 IdRef distincts, 181 sont en base : 84 confirmés, 97 en attente.

## Décisions

- Le chantier couvre les brevets dont un établissement du périmètre est déposant. Le brevet d'un organisme partenaire se rattache au périmètre seulement par ses inventeurs, sans adresse dans ScanR.
- Source : l'index `scanr-patents`, sous une source `scanr_patents` distincte de ScanR.
- Unité : la famille.
- Un brevet est une publication de type `patent`. Il figure dans les listes de publications et a sa propre page de détail.
- Le moissonnage sélectionne les familles par l'identifiant Paysage de leurs déposants, lu dans `structures.api_ids['scanr_patents']`.
- Types d'identifiant `patent_publication_number` et `patent_application_number` : office et numéro, sans le code de type. Le code de type désigne l'étape de publication d'une demande : A1 pour la demande publiée avec son rapport de recherche, B1 pour le brevet délivré.
- ScanR écrit une demande internationale `PCT/FR2011/050432` sous l'office WO, sans `PCT/` ni office de dépôt. Ses numéros de demande WO recoupent donc les numéros de publication WO d'autres familles.
- Le numéro de publication est une clé de confirmation à plusieurs valeurs, comme le DOI. Un dépôt HAL de brevet rejoint ainsi sa famille.
- La date de publication d'un brevet est la date du premier dépôt de la famille. Les autres dates vont dans `source_extras`.
- Un dépôt HAL de brevet sans famille en base cherche sa famille dans ScanR par numéro (`fetch_missing`).
- Le moissonnage écarte les articles cités et les champs dérivés des autres champs : `denormalized_structures`, `co_*`, `title_abs_text`.
- Un brevet entre dans le périmètre quand un de ses déposants est une structure du périmètre : indice de publication `patent_applicant`.
- Un inventeur entre dans le périmètre seulement par l'indice `hr_record`.
- La purge des publications épargne une publication qui a un indice de publication, même sans contribution rattachée à une personne.
- Rôle de contribution `inventor`, compté comme rôle d'auteur.
- `source_extras` reçoit les demandes, les déposants et la classification CPC.

## Phasage

### Phase 1 — Inventaire

- [x] Demandes déposées par l'UCA et les établissements fusionnés en elle, par nom de déposant
- [x] Comptage par famille, par co-déposant, par année
- [x] Comparaison avec les jeux de données du ministère : couverture, présence des inventeurs
- [x] Recherche par nom d'inventeur sur le personnel : bruit dû aux homonymes

### Phase 2 — Modèle

- [x] Choix de la source, de l'unité et de la place du brevet dans le modèle

### Phase 3 — Moissonnage et normalisation

- [x] Source `scanr_patents` : valeur de `source_type`, profil, adaptateur
- [x] Identifiants Paysage des déposants dans `structures.api_ids['scanr_patents']`, sur l'UCA et sur Clermont Auvergne INP
- [x] Client ScanR paramétré par l'index, partagé par `scanr` et `scanr_patents`
- [x] Moissonnage des familles par déposant
- [x] Normalisation : enregistrement source de type `patent`, numéros en `patent_publication_number` et `patent_application_number`, inventeurs en contributions sources de rôle `inventor`
- [x] Demandes, déposants et classification CPC dans `source_extras`
- [x] Rafraîchissement d'une famille par son identifiant (`fetch_stale`)

### Phase 4 — Rattachement des dépôts HAL

- [ ] Numéros de `number_s` lus en numéros de publication ou de demande
- [ ] `patent_publication_number` en clé de confirmation à plusieurs valeurs
- [ ] Usage de `patent_application_number` dans le rattachement, après mesure des recoupements
- [ ] Recherche dans ScanR des familles absentes, par numéro (`fetch_missing`)
- [ ] Mesure de l'effet sur les publications, puis relance avec `--rebuild-publications`

### Phase 5 — Périmètre et personnes

- [ ] Indice de périmètre `patent_applicant`
- [ ] Exception à la purge des publications, après mesure de l'effet sur les thèses
- [ ] Rôle `inventor`, compté comme rôle d'auteur
- [ ] Mesure du rattachement des inventeurs par IdRef et par alignement avec les auteurs HAL
- [ ] Mesure du rattachement par nom des autres inventeurs aux personnes RH

### Phase 6 — Interface

- [ ] Page de détail d'un brevet : demandes par office, déposants, inventeurs, classification CPC
- [ ] Revue, éditeur, open access et APC masqués pour un brevet

### Phase 7 — Documentation

- [ ] Mise à jour de la documentation des sources et des données

## Questions ouvertes

1. Articles cités par un brevet : relation avec les publications par DOI.
2. Un numéro FR à 7 chiffres de `number_s` peut désigner une demande ou une publication ancienne. ScanR distingue les deux.
