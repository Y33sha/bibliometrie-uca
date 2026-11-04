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
- les demandes de chaque office ;
- les articles cités par le brevet, avec leur DOI et les affiliations de leurs auteurs.

### HAL

Le champ `number_s` d'un dépôt HAL de type brevet contient son numéro en texte libre : numéro de publication ou de demande, parfois plusieurs, ou une référence interne. Le moissonnage HAL demande ce champ.

### Inventaire du 2026-11-04

Familles dont un établissement du périmètre est déposant : UCA, Université Blaise Pascal, Université d'Auvergne, Clermont Auvergne INP, SIGMA Clermont, IFMA, ENSCCF.

| Source | Familles |
|---|---|
| INPI | 224, premier dépôt de 1982 à 2025 |
| ScanR | 156, premier dépôt depuis 2010 |
| HAL | 38 |

- Depuis 2010, 146 familles sont présentes à la fois à l'INPI et dans ScanR. 14 des 17 familles présentes seulement à l'INPI sont déposées en 2024 ou 2025.
- Le CNRS est co-déposant de la moitié des familles de l'INPI.
- HAL contient 88 brevets. 65 sont présents dans ScanR, dont 27 sans déposant du périmètre. 9 des 23 autres donnent une référence interne d'INRAE à la place d'un numéro de brevet.
- 90 personnes RH ont le nom et le prénom d'un inventeur des familles de l'INPI domicilié dans le Puy-de-Dôme.

## Décisions

- Le chantier couvre les brevets dont un établissement du périmètre est déposant. Le brevet d'un organisme partenaire se rattache au périmètre seulement par ses inventeurs, sans adresse dans ScanR.

## Phasage

### Phase 1 — Inventaire

- [x] Demandes déposées par l'UCA et les établissements fusionnés en elle, par nom de déposant
- [x] Comptage par famille, par co-déposant, par année
- [x] Comparaison avec les jeux de données du ministère : couverture, présence des inventeurs
- [x] Recherche par nom d'inventeur sur le personnel : bruit dû aux homonymes

### Phase 2 — Modèle

- [ ] Choix de la source, de l'unité et de la place du brevet dans le modèle (questions 1 à 3)

### Phase 3 — Moissonnage

### Phase 4 — Rattachement aux structures et aux personnes

### Phase 5 — Interface

### Phase 6 — Documentation

- [ ] Mise à jour de la documentation des sources et des données

## Questions ouvertes

1. Source : API de l'INPI, ScanR, ou les deux, avec les brevets de HAL.
2. Unité : la demande ou la famille.
3. Place dans le modèle : un type de publication, ou une entité distincte.
4. Articles cités par un brevet : relation avec les publications par DOI.
