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

### API OPS de l'Office européen des brevets

- Base : `https://ops.epo.org/3.2/rest-services/`. Connexion OAuth par compte (`EPO_OPS_KEY`, `EPO_OPS_SECRET`). Quota hebdomadaire.
- Couverture : demandes et publications de tous les offices.
- Recherche (`published-data/search/biblio`) en syntaxe CQL : déposant (`pa`), numéro de demande (`ap`), numéro de priorité (`pr`), date de publication (`pd`). 100 résultats par requête. Le service de recherche limite le débit selon sa charge, jusqu'à 5 requêtes par minute. L'en-tête `X-Throttling-Control` donne l'état du service.
- Famille (`family/publication/epodoc/{numéro}/biblio`) : famille INPADOC, avec pour chaque membre la demande, la publication et son code de type, les priorités, les déposants, les inventeurs et les titres.
- Les noms des déposants et des inventeurs existent au format original et au format epodoc (`UNIV CLERMONT AUVERGNE [FR]`). Le format original sépare le plus souvent le nom du prénom par une virgule.
- Une priorité jamais publiée se trouve par son numéro de priorité (`pr`).

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

### Sondages du 2026-11-10

- L'index `scanr-patents` compte 1 854 familles de premier dépôt en 2024 et 3 en 2025, contre environ 16 000 par an jusqu'en 2023.
- La recherche OPS sur les noms des établissements du périmètre trouve 246 familles. Elle retrouve les 78 familles ScanR brevets en base dont un déposant est du périmètre. Elle trouve 14 familles déposées en 2024 ou 2025, absentes de ScanR brevets.
- Les 59 demandes FR de l'INPI déposées depuis 2017 par un établissement du périmètre sont présentes dans OPS, sauf le second dépôt FR d'une famille ScanR en base.
- Les inventeurs rattachés par nom à une personne de la base donnent un laboratoire à 13 des 14 familles trouvées dans OPS et absentes de la base : unité du SI RH, à défaut laboratoire de leurs publications.

### Comparaison des sources

| | HAL | ScanR brevets | OPS | INPI |
|---|---|---|---|---|
| Offices couverts | Ceux déclarés par les laboratoires | Tous | Tous | FR, EP, WO |
| Années couvertes | Selon les dépôts des laboratoires | Jusqu'au printemps 2025 | Jusqu'à 18 mois avant la recherche | Jusqu'à 18 mois avant la recherche |
| Familles | Non | Oui | Oui | Non |
| Laboratoire | Oui | Non | Non | Non |
| Déposants | Noms | Identifiants Paysage, SIREN, ROR | Noms | Noms ; SIREN sur une partie des demandes FR |
| Inventeurs | Auteurs du dépôt | Noms ; IdRef pour la moitié | Noms | Noms |
| Défauts constatés | Doublons, numéros faux, souches et références internes, dépôts inégaux selon les laboratoires | Priorités FR manquantes ; une même priorité répartie sur plusieurs familles | Graphies multiples des noms | Demandes non regroupées en familles |

## Décisions

- Le chantier couvre les brevets dont un établissement du périmètre est déposant. Le brevet d'un organisme partenaire se rattache au périmètre seulement par ses inventeurs, sans adresse dans ScanR.
- Source : l'API OPS de l'Office européen des brevets, en remplacement de l'index `scanr-patents` (phase 9).
- Unité : la famille.
- Un brevet est une publication de type `patent`. Il figure dans les listes de publications et a sa propre page de détail.
- Le moissonnage sélectionne les familles par l'identifiant Paysage de leurs déposants, lu dans `structures.api_ids['scanr_patents']`.
- Types d'identifiant `patent_publication_number` et `patent_application_number` : office et numéro, sans le code de type. Le code de type désigne l'étape de publication d'une demande : A1 pour la demande publiée avec son rapport de recherche, B1 pour le brevet délivré.
- ScanR écrit une demande internationale `PCT/FR2011/050432` sous l'office WO, sans `PCT/` ni office de dépôt. Ses numéros de demande WO recoupent donc les numéros de publication WO d'autres familles.
- Les numéros de publication et de demande sont des clés de confirmation à plusieurs valeurs, comme le DOI. Un dépôt HAL de brevet rejoint ainsi sa famille. Un numéro relie seulement un numéro de même type.
- Une famille est une ancre de la réconciliation, comme un DOI. Deux familles déposées le même jour sous le même titre restent deux publications.
- Un numéro français de sept chiffres de `number_s` est une publication s'il commence par 3, ou par une année postérieure à la date du dépôt HAL. Sinon, c'est une demande.
- La date de publication d'un brevet est la date du premier dépôt de la famille. Les autres dates vont dans `source_extras`.
- Un dépôt HAL de brevet sans famille en base cherche sa famille dans ScanR par numéro (`fetch_missing`).
- Le moissonnage écarte les articles cités et les champs dérivés des autres champs : `denormalized_structures`, `co_*`, `title_abs_text`.
- Un brevet entre dans le périmètre quand un de ses déposants est une structure du périmètre : indice d'appartenance au périmètre `patent_applicant`, lié au document comme `thesis_institution`. La vue `source_contribution_structures` donne l'indice à tous les inventeurs de la famille.
- Un inventeur se rattache seulement à une personne existante, par identifiant ou par nom, comme un membre de jury.
- La purge des publications épargne une publication à indice lié au document, même sans contribution rattachée à une personne.
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

- [x] Numéros de `number_s` lus en numéros de publication ou de demande
- [x] `patent_publication_number` en clé de confirmation à plusieurs valeurs
- [x] Usage de `patent_application_number` dans le rattachement, après mesure des recoupements
- [x] Recherche dans ScanR des familles absentes, par numéro (`fetch_missing`)
- [x] Mesure de l'effet sur les publications : 62 dépôts HAL sur 97 rattachés à une famille, 73 familles sur 97 rattachées à une publication
- [x] Famille en ancre de la réconciliation

### Phase 5 — Périmètre et personnes

- [x] Indice de périmètre `patent_applicant` : les 97 familles ont leur publication
- [x] Exception à la purge des publications : les 2 626 thèses à indice `thesis_institution` ont toutes une contribution rattachée à une personne
- [x] Indices des publications liés au document repris des contributions sources, sans relecture du PPN de l'établissement
- [x] Rôle `inventor`, compté comme rôle d'auteur : les brevets sans dépôt HAL ont tous une structure liée
- [x] Mesure du rattachement des inventeurs : 364 sur 521 rattachés à une personne, dont 271 par IdRef, ORCID ou identifiant HAL
- [x] Mesure du rattachement par nom : 93 inventeurs, dont 26 sur des familles sans dépôt HAL ; échantillon cohérent avec les structures des personnes

### Phase 6 — Interface

- [x] Page de détail d'un brevet : demandes par office, déposants, inventeurs, classification CPC
- [x] Revue, éditeur, open access et APC masqués pour un brevet : statut open access `unknown`
- [x] Copie Espacenet de la demande prioritaire en lien d'accès, libellé « Consulter le brevet »

### Phase 7 — Documentation

- [x] Mise à jour de la documentation des sources et des données

### Phase 8 — Brevets absents de ScanR brevets

29 brevets sont sans famille ScanR brevets au 2026-11-06.

- [x] Brevet américain délivré (3) : HAL donne le numéro de délivrance, absent de ScanR. Deux dépôts HAL fusionnés à la main avec leur famille. Le troisième brevet n'a pas de déposant du périmètre.
- [x] Même titre qu'une famille en base (2) : demande prioritaire absente de la famille ScanR, ou date HAL postérieure d'un an au premier dépôt. Fusionnés à la main.
- [ ] Sans numéro de brevet (9) : références internes d'INRAE, souches.
- [x] Numéro FR, EP ou WO absent de ScanR (15) : les 9 demandes déposées en 2024 ou 2025 sont dans OPS. Parmi les 6 plus anciennes, EP23306459 est inconnu d'OPS ; les autres sont hors périmètre ou fusionnées.
- [x] Comparaison des sources : HAL, ScanR brevets, OPS, INPI
- [x] Choix des sources de brevets : OPS remplace ScanR brevets

### Phase 9 — Remplacement de ScanR brevets par OPS

- [ ] Source OPS : valeur de `source_type`, profil, identifiants d'accès (`EPO_OPS_KEY`, `EPO_OPS_SECRET`), débit réglé sur l'en-tête `X-Throttling-Control`
- [ ] Unité et identifiant source de la famille OPS
- [ ] Périmètre : déposants du périmètre reconnus par leur nom
- [ ] Moissonnage : publications cherchées par nom de déposant, puis famille de chaque publication
- [ ] Normalisation : numéros, dates par office, déposants, inventeurs, titres, résumé, classification CPC
- [ ] Recherche des familles absentes par numéro (`fetch_missing`) : numéro de publication, de demande, puis de priorité
- [ ] Rafraîchissement d'une famille (`fetch_stale`)
- [ ] Page de détail : déposants et classification CPC
- [ ] Dépôts HAL de type brevet sans famille OPS
- [ ] Retrait de la source `scanr_patents` : code, enregistrements sources, `structures.api_ids['scanr_patents']`
- [ ] Mesure avant et après : familles du périmètre, inventeurs rattachés à une personne
- [ ] Mise à jour de la documentation

## Questions ouvertes

1. Articles cités par un brevet : relation avec les publications par DOI.
2. Dépôts HAL de type brevet sans famille OPS : déclarations d'invention d'INRAE (`DI-RV-…`), enveloppes Soleau, numéros faux, demandes pas encore publiées.
