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
- L'adresse de l'inventeur est son adresse personnelle.
- Un brevet nomme ses déposants, jamais le laboratoire. Le CNRS et l'Inserm déposent à leur adresse parisienne. Leurs brevets issus d'un laboratoire de l'UCA, sans l'UCA en co-déposant, se repèrent seulement par les inventeurs.

### Open data du ministère de l'Enseignement supérieur et de la Recherche

Le portail `data.enseignementsup-recherche.gouv.fr` publie `deposants-des-brevets`, `demandes-de-brevets` et `fr-esr-familles-brevets`, mis à jour en mai 2026. Tous les offices sont couverts. Les déposants sont résolus en SIREN et en identifiant Paysage. Accès libre, sans compte.

## Décisions

## Phasage

### Phase 1 — Inventaire

- [ ] Demandes déposées par l'UCA et les établissements fusionnés en elle, par nom de déposant
- [ ] Comptage par famille, par co-déposant, par année
- [ ] Comparaison avec les jeux de données du ministère : couverture, présence des inventeurs
- [ ] Recherche par nom d'inventeur sur un échantillon du personnel, parmi les demandes du CNRS et de l'Inserm : bruit dû aux homonymes

### Phase 2 — Modèle

- [ ] Choix de la source, de l'unité et de la place du brevet dans le modèle (questions 1 à 3)

### Phase 3 — Moissonnage

### Phase 4 — Rattachement aux structures et aux personnes

### Phase 5 — Interface

### Phase 6 — Documentation

- [ ] Mise à jour de la documentation des sources et des données

## Questions ouvertes

1. Source : API de l'INPI, jeux de données du ministère, ou les deux.
2. Unité : la demande ou la famille.
3. Place dans le modèle : un type de publication, ou une entité distincte.
4. Périmètre : demandes d'un déposant du périmètre, demandes d'un inventeur rattaché à une structure du périmètre.
5. Articles cités par un brevet : relation avec les publications par DOI.
