# Pages publiques

## Statistiques (`/stats`)

Tableaux de bord :
- répartition par [[oa_status|voie *open access*]] par année (graphique exportable en png);
- répartition par éditeur (liste);
- répartition par revue (liste).

Filtrable par:
- année de publication,
- laboratoire,
- voie *open access*,
- paiement d'APC.

Restreint aux publications de type article et *review*.<!--TODO: glossaire? et voir si d'autres types sont pertinents--> Quels que soient les filtres en place, un bouton "Voir les publications" donne accès à la liste complète des publications concernées.

## Publications (`/publications`)

Liste des publications filtrable par :
- type de document,
- année de publication,
- laboratoires,
- accès (ouvert/fermé),
- [[oa_status|voie *open access*]],
- paiement d'[[apc|APC]],
- pays des co-auteurs,
- sources.

Filtre de recherche (interroge le titre et les sujets liés).

Export csv.

Certaines colonnes+facettes sont masquées par défaut: un bouton permet de choisir les colonnes affichées.

## Détails publication (`/publications/{id}`)

Vue détaillée : métadonnées, auteurs, sources contributrices.

Vue alignée des auteurs par source pour détecter d'éventuelles incohérences.<!--TODO: à supprimer de l'UI publique, à réserver à une future page admin.-->

## Thèses (`/theses`)

TODO: à compléter


## Sujets (`/subjects`)

TODO: à compléter


## Liste des personnes (`/persons`)

Liste des personnes avec leurs identifiants (ORCID, idHAL) et affiliations.
Filtrable par:
- présence ou non dans la [base RH](../sources/imports-manuels#donnees-rh),
- données RH (rôle, affiliation),
- identifiants (ORCID, idHAL).


## Détails personne (`/persons/{id}`)

Vue détaillée d'un chercheur. Identifiants, données RH si existent.
3 ou 4 onglets:
- dashboard
- publications
- thèses, si la personne est liée à une ou plusieurs thèses
- adresses (adresses liées à cette personne dans les publications)
<!-- TODO: Distinguer les onglets visibles selon rôle utilisateur: les onglets "identités" et "adresses" sont des outils internes, sans intérêt pour le chercheur -->
<!-- TODO: Onglet adresses des pages personnes/id et laboratoire/id: afficher nombre de publications liées à chaque adresse; créer possibilité de consulter la liste?; normaliser adresses pour diminuer le nombre de variantes liées à des différences de ponctuation? -->

## Liste des laboratoires (`/laboratories`)

Liste des laboratoires avec tutelles, identifiant ROR et lien vers collection HAL.

## Détails laboratoire (`/laboratories/{id}`)

Vue détaillée d'un laboratoire.

Onglets:
- Dashboard (sujets, production, taux d'accès ouvert, collaborations internationales);
- Publications;
- Thèses;
- Personnes: affiche les personnes liées à ce laboratoire via une publication (ne repose pas sur l'affiliation renseignée dans la base RH);
- Adresses (adresses ayant permis la détection de ce laboratoire dans les publications).

## Liste des revues (`/journals`)

Liste des revues avec filtres : recherche par nom, type de revue, présence dans le DOAJ, modèle d'accès ouvert. Triable par nombre de publications.

## Détails revue (`/journals/{id}`)

Vue détaillée d'une revue. Onglets : Dashboard, Publications.

## Liste des éditeurs (`/publishers`)

Liste des éditeurs avec leurs revues associées et leur volume de publications.

## Détails éditeur (`/publishers/{id}`)

Vue détaillée d'un éditeur. Onglets : Dashboard, Revues, Publications.

## Problèmes HAL (`/hal-problems/*`) {#problemes-hal}

Pages dédiées aux problèmes de qualité spécifiques à HAL :

- **Comptes en double** : auteurs HAL ayant plusieurs comptes
- **Publications en double** : documents HAL doublonnés
- **Manques dans les collections** : affiliations manquantes: publications HAL qui devraient être dans une collection HAL mais n'y sont pas
- **Conflits d'affiliation** : publications HAL avec une affiliation UCA suspecte, en contradiction avec les autres sources

## Évolutions en cours

> Deux chantiers actifs touchent à ces pages publiques. À consulter pour le contexte des évolutions à venir.
>
> - [`METIER_publishers-journals.md`](https://github.com/Y33sha/bibliometrie-uca/blob/master/docs/chantiers/METIER_publishers-journals.md) — référentiels éditeurs / revues (les pages `/journals` et `/publishers` sont nées de ce chantier).
> - [`METIER_doc-types.md`](https://github.com/Y33sha/bibliometrie-uca/blob/master/docs/chantiers/METIER_doc-types.md) — taxonomie des types de document utilisée dans les listings et les filtres.
