# Guide utilisateur — Bibliométrie UCA

## Présentation

L'application fournit un suivi de la production scientifique de l'Université
Clermont Auvergne en intégrant trois sources bibliographiques : HAL, OpenAlex et
Web of Science.

Elle permet de :
- Consulter les publications, les personnes et les laboratoires
- Identifier et corriger les erreurs d'attribution (homonymes, doublons)
- Suivre les indicateurs par année, laboratoire, type de document, accès ouvert

## Pages publiques

### Annuaire des personnes (`/persons`)

Liste des chercheurs avec leurs publications, identifiants (ORCID, idHAL) et
affiliations. Filtrable par laboratoire, source, ORCID, etc.

### Fiche personne (`/persons/{id}`)

Vue détaillée d'un chercheur : identifiants, liste des publications
avec les sources contributrices.

### Annuaire des laboratoires (`/laboratories`)

Liste des laboratoires avec effectifs et publications.

### Fiche laboratoire (`/laboratories/{id}`)

Vue détaillée d'un laboratoire : membres, publications, indicateurs.

### Publications (`/publications`)

Catalogue des publications avec filtres multiples : année, laboratoire, type de
document, accès ouvert, source, éditeur, revue.

### Fiche publication (`/publications/{id}`)

Vue détaillée : métadonnées, auteurs, sources contributrices, informations
d'accès ouvert.

### Statistiques (`/stats`)

Tableaux de bord : production par année, par laboratoire, par type de document,
taux d'accès ouvert, répartition par éditeur.

## Pages d'administration

### Gestion des personnes (`/admin/persons`)

Vue centrale pour le nettoyage du référentiel de personnes :

- **Formes de nom** : chaque personne a des formes de nom normalisées issues des
  sources. Un badge orange indique une forme **ambiguë** (partagée avec une autre
  personne). Cliquer sur une forme ouvre un modal de détachement.
- **Identifiants** : ORCID, idHAL, IdRef avec statut (en attente, confirmé, rejeté).
  Les boutons ✓ et ✗ permettent de confirmer ou rejeter.
- **Fusion** : le bouton "Fusionner" permet de chercher un doublon et de fusionner
  deux personnes. Bloqué si les deux ont une fiche RH.
- **Édition du nom** : le crayon permet de corriger le nom/prénom.
- **Rejet** : marquer une personne comme fausse entité (homonyme non résolu).

### Authorships orphelines (`/admin/orphan-authorships`)

Authorships UCA dont l'auteur n'est pas encore identifié (`person_id = NULL`).
Pour chaque authorship, on peut :

- **Attribuer** à une personne existante (recherche par nom)
- **Créer** une nouvelle personne et lui attribuer l'authorship
- **Traitement par lot** : sélectionner plusieurs authorships et les attribuer
  en une fois

Le dropdown de recherche affiche le département RH ou l'identifiant pour
départager les homonymes.

### Doublons de publications (`/admin/duplicates`)

Paires de publications potentiellement identiques (titre similaire, même année).
Pour chaque paire, on peut :

- **Fusionner** : absorber une publication dans l'autre
- **Marquer comme distinctes** : indiquer que ce n'est pas un doublon
- **Passer** : reporter la décision

### Doublons de personnes (`/admin/duplicates-persons`)

Paires de personnes potentiellement identiques. Même logique que les doublons de
publications, avec en plus l'affichage des identifiants et laboratoires pour
faciliter la décision.

### Gestion des structures (`/admin/structures`)

Référentiel institutionnel : créer, modifier, organiser les structures (labos,
tutelles, partenaires) et leurs relations hiérarchiques.

### Gestion des adresses (`/admin/addresses`)

Validation des adresses d'affiliation résolues automatiquement. Confirmer ou
rejeter les associations adresse → structure.

### Gestion des pays (`/admin/countries`)

Attribution et correction des pays des publications.

### Retours utilisateurs (`/admin/feedback`)

Gestion des signalements remontés par les utilisateurs.

## Problèmes HAL (`/hal-problems/*`)

Pages dédiées aux problèmes de qualité spécifiques à HAL :

- **Conflits d'affiliation** : publications HAL avec des affiliations incohérentes
- **Comptes en double** : auteurs HAL ayant plusieurs comptes
- **Publications en double** : documents HAL doublonnés
- **Collections manquantes** : publications qui devraient être dans une collection
  HAL mais n'y sont pas

## Concepts clés pour les utilisateurs

### Authorship source vs vérité

Une **authorship source** est le lien brut entre un auteur et un document dans
une source donnée (HAL, OpenAlex ou WoS). Une **authorship** est le lien
canonique entre une personne et une publication, construit en agrégeant les
authorships sources.

### Le périmètre UCA

Est considéré "UCA" un auteur affilié à l'UCA ou à l'une de ses unités en
tutelle directe. Le **périmètre élargi** inclut aussi les partenaires (CHU,
INP, VetAgro Sup).

### Formes de nom et matching

Le système identifie les personnes en comparant les noms d'auteurs normalisés
(minuscules, sans accents ni ponctuation). Par exemple, "Nédélec, J.-M." et
"Jean-Marie Nedelec" se normalisent tous les deux en `jean marie nedelec`.

Une forme de nom est **ambiguë** quand elle pointe vers plusieurs personnes
(homonymes). Ces cas nécessitent une intervention manuelle.

### Authorship exclue

Une authorship source peut être **exclue** quand elle est rattachée à la mauvaise
personne (homonyme, erreur de la source). Les authorships exclues sont ignorées
par le pipeline : elles ne génèrent pas d'authorship vérité.
