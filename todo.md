# Sources de données

## APC
* [x] trouver APC par revue
* [ ] intégrer données APC DPCG
* [ ] estimer APC par structure (gold+hybride avec auteur correspondant sauf Elsevier)

## Web of Science
En attente réponse équipe technique.
* [ ] Relancer import: python3 extraction/wos/extract_wos.py --year 2023
* [ ] Normalisation, peuplement des tables structures, auteurs, authorships, gestion des adresses, etc.

## OpenAlex
* [ ] inclure publis affiliées CHU et INP dans le script d'import OpenAlex
* [ ] re-fetch individuel des docts OpenAlex plafonnés à 100 authorships dans l'import automatique
* [ ] re-fetch à partir des DOI HAL

## HAL
* [ ] inclure collections HAL CHU-CLERMONTFERRAND et CLERMONT-AUVERGNE-INP
* [ ] fetch documents HAL référencés par OpenAlex mais absents des collections UCA
* [ ] documents > 2000 auteurs: relancer le script pour peupler la table authorships
* [ ] problème des documents où l'affiliation de l'authorship n'est pas résolue: cf https://hal.science/hal-04987032
* [ ] retraitement pour les authorships sans auteur_id (prendre strings?)

## ORCID
* [ ] moissoner crossref via ORCID pour trouver publis absentes de HAL, OpenAlex et WoS?

## Workflow
* [ ] nouveaux imports: comment prendre en compte fusions de comptes auteurs ayant eu lieu entre-temps (par ex. sur HAL)? / + ré-importer et écraser publis déjà présentes et modifiées entre-temps (stocker hash puis comparer?)
* [ ] automatiser imports réguliers (1/semaine?)


# Développement

## Signatures
* [ ] problème des liens inexistants: il faudrait pouvoir requêter toutes les adresses pour trouver les faux négatifs (ex.: "CNRS-IRD-UCA")
* [ ] page feedback: à mettre à jour pour tenir compte de la migration (script "relancer la détection": cassé, à réparer)
* [ ] "sélectionner tout => confirmer" : vérifier que la migration n'a pas cassé la fonctionnalité
* [ ] affichage des structures liées à une adresse: modifier la couleur selon statut "confirmé" (vert), à confirmer (jaune), rejeté (rouge et rayé)
* [ ] validation des adresses: à mettre en place si pertinent
* [ ] publis sans adresses (HAL) => scraper les sites éditeurs pour trouver adresses?

## Personnes
* [x] moissonner ORCID liés aux comptes HAL (processing/harvest_hal_orcids.py — 12125 ORCID récupérés)
* [x] possibilité d'ajout manuel d'ORCID
* [x] ORCID fautifs liés à OpenAlex: possibilité de rejeter
* [x] admin/authorships: n'afficher que les publis avec authorship UCA
* [x] organiser la page en onglets
* [ ] publications: indiquer si auteur correspondant / premier auteur
* [ ] colonne labos: utiliser info collection HAL (actuellement colonne vide quand HAL seule source); voir comment ça marche sur la page publications
* [ ] ajouter IdRef?
* [ ] ajouter quelques visus (%OA)
* [ ] authorships OpenAlex pourries (ex. Pierre Mathieu): trouver un moyen de les déclarer inutilisables / ou cesser totalement d'utiliser les authorships OpenAlex? étudier les options
* [ ] Publications rattachées au mauvais compte HAL: cf Marc Andre: trouver moyen de rejeter le compte et garder les publis
* [ ] reconnaissance de noms moins stricte (noms composés, tirets, accents) pour la suggestion de matchings personnes-auteurs

## Structures
* [x] créer page détails
* [x] authorships orphelines: interface pour les visualiser et les rattacher à des personnes
* [ ] onglet dashboard
* [ ] signatures: afficher nombre de publis + dates; trier par publis décroissantes; idem sur page personne
* [ ] afficher identifiants (AuréHAL, OpenAlex, WoS) avec liens

## Publications
* [x] diagnostiquer le lag (tester requêtes)
* [x] idem page stats (revues): requête très lente
* [x] créer page détails
* [x] filtre Source: 3 options par source (absent, présent, tous)
* [x] dans les filtres: ajouter option "aucun labo"
* [x] type "preprint": apparaît "autre" dans les extractions OpenAlex (https://openalex.org/works/W4407574839); voir ce qu'il en est dans les extractions HAL (le compte de préprints est zéro)
* [ ] ajouter filtre corresponding_is_uca?
* [ ] publications de type "article" avec source OpenAlex et revue inconnue: généralement des préprints sur des archives en ligne: diagnostiquer et  corriger
* [ ] lien Publications -> Dashboard?

## Pages supplémentaires, étudier pertinence
* [ ] sujets
* [ ] éditeurs
* [ ] revues


# Interface
* [x] Export csv tableaux
* [x] Export png graphiques
* [ ] Légende dans export png
* [ ] Toujours mémoriser filtres et les rétablir au rechargement
* [ ] Rendre tous les tableaux triables
* [ ] lien retour: set default (si accès direct URL) ou cacher?
* [ ] sources: arrangées verticalement dans un dropdown
* [ ] afficher todo et nouveautés?

# Trucs pour plus tard
* compte fractionnaire?
* collaborations nationales et internationales?