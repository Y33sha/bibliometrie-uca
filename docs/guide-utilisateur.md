# Guide utilisateur

*A mettre à jour.*

## Pages publiques

### Statistiques (`/stats`)

Tableaux de bord : production par année, par laboratoire, par type de document, taux d'accès ouvert, répartition par éditeur.

### Publications (`/publications`)

Catalogue des publications avec filtres multiples : année, laboratoire, type de document, accès ouvert, source, éditeur, revue.


#### Fiche publication (`/publications/{id}`)

Vue détaillée : métadonnées, auteurs, sources contributrices.

Vue alignée des auteurs par source pour détecter d'éventuelles incohérences.

### Thèses (`/theses`)

TODO: à compléter


### Sujets (`/subjects`)

TODO: à compléter


### Annuaire des personnes (`/persons`)

Liste des personnes avec leurs identifiants (ORCID, idHAL) et affiliations.
Filtrable par:
- présence ou non dans la [base RH](sources#donnees-rh),
- données RH (rôle, affiliation),
- identifiants (ORCID, idHAL).


#### Fiche personne (`/persons/{id}`)

Vue détaillée d'un chercheur. Identifiants, données RH si existent.
3 ou 4 onglets:
- dashboard
- publications
- thèses, si la personne est liée à une ou plusieurs thèses
- adresses (adresses liées à cette personne dans les publications)
<!-- TODO: Distinguer les onglets visibles selon rôle utilisateur: les onglets "identités" et "adresses" sont des outils internes, sans intérêt pour le chercheur -->
<!-- TODO: Onglet adresses des pages personnes/id et laboratoire/id: afficher nombre de publications liées à chaque adresse; créer possibilité de consulter la liste?; normaliser adresses pour diminuer le nombre de variantes liées à des différences de ponctuation? -->

### Annuaire des laboratoires (`/laboratories`)

Liste des laboratoires avec tutelles, identifiant ROR et lien vers collection HAL.

#### Fiche laboratoire (`/laboratories/{id}`)

Vue détaillée d'un laboratoire.

Onglets:
- Dashboard (sujets, production, taux d'accès ouvert, collaborations internationales);
- Publications;
- Personnes: affiche les personnes liées à ce laboratoire via une publication (ne repose pas sur l'affiliation renseignée dans la base RH);
- Adresses (adresses ayant permis la détection de ce laboratoire dans les publications).

### <span id='problemes-hal'></span>Problèmes HAL (`/hal-problems/*`)

Pages dédiées aux problèmes de qualité spécifiques à HAL :

- **Comptes en double** : auteurs HAL ayant plusieurs comptes
- **Publications en double** : documents HAL doublonnés
- **Manques dans les collections** : affiliations manquantes: publications HAL qui devraient être dans une collection HAL mais n'y sont pas
- **Conflits d'affiliation** : publications HAL avec une affiliation UCA suspecte, en contradiction avec les autres sources

## Pages d'administration

### Pipeline

#### <span id="admin-config"></span>Configuration (`/admin/config`)

Paramètres des imports:
- email (polite pool);
- clé API WOS;
- années interrogées (modes weekly et full);
- paramètres de requête par source;
- définition et CRUD des périmètres (`uca`, `uca_wide`);
- périmètres utilisés à différentes étapes du pipeline.

### Logs
TODO: à compléter

### Référentiels
#### <span id="admin-structures"></span>Structures (`/admin/structures`)

Gère le CRUD sur l'ensemble des structures du périmètre UCA + les co-tutelles des laboratoires (ONR, écoles, autres universités) + le CHU.

Pour chaque structure:
- **Détails** (nom, acronyme, identifiant ROR, collection HAL);
- **Relations** (2 relations: tutelle, partenaire);
- **Identification** dans les publications: Gestion des formes de nom (pour l'identification dans les adresses)


#### Gestion des personnes (`/admin/persons`)

Gestion du référentiel de personnes :

- **Édition du nom**.
- **Rejet** : marquer une personne comme fausse entité (mauvais parsing, noms d'équipes de recherche…).
- **Identifiants** : ORCID, idHAL, IdRef avec statut (en attente, confirmé, rejeté). Les boutons ✓ et ✗ permettent de confirmer ou rejeter. Ajout d'identifiants.
- **Formes de nom** : chaque personne a des formes de nom normalisées issues des sources. Un badge orange indique une forme **ambiguë** (partagée avec une autre personne). Cliquer sur une forme ouvre un modal permettant de consulter les authorships liées et de les détacher.
- **Fusion** : le bouton "Fusionner" permet de chercher un doublon et de fusionner deux personnes. Bloqué si les deux ont une fiche RH.

##### Authorships orphelines (`/admin/orphan-authorships`)

Authorships UCA dont l'auteur n'est pas encore identifié (`person_id = NULL`). Pour chaque authorship, on peut :

- **Attribuer** à une personne existante (recherche par nom)
- **Créer** une nouvelle personne et lui attribuer l'authorship
- **Traitement par lot** : sélectionner plusieurs authorships et les attribuer en une fois

Le dropdown de recherche affiche le département RH (si existant) ou l'id interne (sinon) pour départager les homonymes.

#### Éditeurs
TODO: à compléter

#### Revues
TODO: à compléter

### Adresses
#### Contrôle des affiliations des adresses (`/admin/addresses`)

Contrôle des adresses d'affiliation résolues automatiquement par la phase `resolve_addresses` du pipeline.
Confirmer ou rejeter manuellement les associations adresse → structure.

##### Qualité de la détection (`/admin/feedback`)

Fait ressortir les faux positifs et faux négatifs dans la détection de structures dans les adresses:
- **faux négatifs**: affiliations adresse-structure non détectées par le script mais créées manuellement => repérer les formes de nom non détectées, et les ajouter dans admin/structures.
- **faux positifs**: affiliations détectées par le script mais rejetées manuellement => supprimer une forme de nom trop permissive ou lui ajouter un contexte contraignant.

Les corrections seront prises en compte à la prochaine exécution du pipeline (phase `resolve_addresses`).

#### Gestion des liens adresses-pays (`/admin/countries`)

Attribution et correction des pays liés aux adresses.
Les corrections se propagent automatiquement aux publications liées, sans besoin de relancer le pipeline.

### Interfaces de dédoublonnage
#### Doublons de publications (`/admin/duplicates`)

Paires de publications potentiellement identiques (titre normalisé identique, même type, même année).

Pour chaque paire, on peut :

- **Fusionner** : absorber une publication dans l'autre
- **Marquer comme distinctes** : indiquer que ce n'est pas un doublon
- **Passer** : reporter la décision

#### Doublons de personnes (`/admin/person-duplicates`)

Paires de personnes potentiellement identiques. Mêmes opérations que pour les doublons de publications.

Deux modes de détection des candidats au dédoublonnage:
- Par similitude de noms (tolérance aux initiales et aux noms composés vs simples);
- Par conflit entre sources (deux personnes en même position auteur sur la même publication).
