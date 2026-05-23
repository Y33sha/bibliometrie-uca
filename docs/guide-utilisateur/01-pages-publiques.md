# Pages publiques

*A mettre à jour.*

## Statistiques (`/stats`)

Tableaux de bord : production par année, par laboratoire, par type de document, taux d'accès ouvert, répartition par éditeur.

## Publications (`/publications`)

Catalogue des publications avec filtres multiples : année, laboratoire, type de document, accès ouvert, source, éditeur, revue.


### Fiche publication (`/publications/{id}`)

Vue détaillée : métadonnées, auteurs, sources contributrices.

Vue alignée des auteurs par source pour détecter d'éventuelles incohérences.

## Thèses (`/theses`)

TODO: à compléter


## Sujets (`/subjects`)

TODO: à compléter


## Annuaire des personnes (`/persons`)

Liste des personnes avec leurs identifiants (ORCID, idHAL) et affiliations.
Filtrable par:
- présence ou non dans la [base RH](../sources/imports-manuels#donnees-rh),
- données RH (rôle, affiliation),
- identifiants (ORCID, idHAL).


### Fiche personne (`/persons/{id}`)

Vue détaillée d'un chercheur. Identifiants, données RH si existent.
3 ou 4 onglets:
- dashboard
- publications
- thèses, si la personne est liée à une ou plusieurs thèses
- adresses (adresses liées à cette personne dans les publications)
<!-- TODO: Distinguer les onglets visibles selon rôle utilisateur: les onglets "identités" et "adresses" sont des outils internes, sans intérêt pour le chercheur -->
<!-- TODO: Onglet adresses des pages personnes/id et laboratoire/id: afficher nombre de publications liées à chaque adresse; créer possibilité de consulter la liste?; normaliser adresses pour diminuer le nombre de variantes liées à des différences de ponctuation? -->

## Annuaire des laboratoires (`/laboratories`)

Liste des laboratoires avec tutelles, identifiant ROR et lien vers collection HAL.

### Fiche laboratoire (`/laboratories/{id}`)

Vue détaillée d'un laboratoire.

Onglets:
- Dashboard (sujets, production, taux d'accès ouvert, collaborations internationales);
- Publications;
- Personnes: affiche les personnes liées à ce laboratoire via une publication (ne repose pas sur l'affiliation renseignée dans la base RH);
- Adresses (adresses ayant permis la détection de ce laboratoire dans les publications).

## Problèmes HAL (`/hal-problems/*`) {#problemes-hal}

Pages dédiées aux problèmes de qualité spécifiques à HAL :

- **Comptes en double** : auteurs HAL ayant plusieurs comptes
- **Publications en double** : documents HAL doublonnés
- **Manques dans les collections** : affiliations manquantes: publications HAL qui devraient être dans une collection HAL mais n'y sont pas
- **Conflits d'affiliation** : publications HAL avec une affiliation UCA suspecte, en contradiction avec les autres sources
