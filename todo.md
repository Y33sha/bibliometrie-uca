# Sources de données

## APC
* [x] trouver APC par revue
* [ ] intégrer données APC DPCG
* [ ] estimer APC par structure (gold+hybride avec auteur correspondant sauf Elsevier)

## Web of Science
API Expanded non fiable. Import via fichiers tab-delimited téléchargés manuellement.
* [x] Import staging : scrape_wos.py --parse-only (fichiers dans extraction/wos/downloads/)
* [ ] Normalisation, peuplement des tables structures, auteurs, authorships, gestion des adresses, etc.

## OpenAlex
* [x] inclure publis affiliées CHU et INP dans le script d'import OpenAlex
* [ ] re-fetch individuel des docts OpenAlex plafonnés à 100 authorships dans l'import automatique
* [ ] re-fetch à partir des DOI HAL

## HAL
* [x] inclure collections HAL CHU-CLERMONTFERRAND et CLERMONT-AUVERGNE-INP
* [ ] fetch documents HAL référencés par OpenAlex mais absents des collections UCA
* [ ] documents > 2000 auteurs: relancer le script pour peupler la table authorships
* [ ] problème des documents où l'affiliation de l'authorship n'est pas résolue: cf https://hal.science/hal-04987032
* [ ] retraitement pour les authorships sans auteur_id (prendre strings?)
* [ ] revue Openalex 'HAL (Le Centre pour la Communication Scientifique Directe)' => parfois absents de HAL! Auditer docts source OpenAlex, ref HAL, HAL non trouvé => supprimer

## ORCID
* [ ] moissoner crossref via ORCID pour trouver publis absentes de HAL, OpenAlex et WoS?
* [ ] exploitation de l'API ORCID pour moissonner par affiliation?

## Unpaywall
* [ ] Finir l'audit Unpaywall vs OpenAlex

## Workflow
* [ ] nouveaux imports: comment prendre en compte fusions de comptes auteurs ayant eu lieu entre-temps (par ex. sur HAL)? / + ré-importer et écraser publis déjà présentes et modifiées entre-temps (stocker hash puis comparer?)
* [ ] automatiser imports réguliers (1/semaine?)


# Développement

## Signatures
* [ ] page feedback: à mettre à jour pour tenir compte de la migration (script "relancer la détection": cassé, à réparer)
* [ ] interface de repérage: filtres sur la base des autres structures reconnues
* [ ] validation des adresses (forme correcte): à mettre en place si pertinent
* [ ] publis sans adresses (HAL) => scraper les sites éditeurs pour trouver adresses?
* [ ] supprimer formes de noms redondantes

## Personnes
* [x] moissonner ORCID liés aux comptes HAL (processing/harvest_hal_orcids.py — 12125 ORCID récupérés) => quelle place dans le pipeline?
* [x] déduplication automatisée par labo (merge_lab_duplicates.py — homonymes + interversions nom/prénom)
* [x] publications: indiquer si auteur correspondant / premier auteur
* [x] permettre confirmation orcid
* [ ] gestion des formes de noms?
* [ ] correction des noms
* [ ] ajouter IdRef?
* [ ] ajouter quelques visus (%OA)
* [ ] authorships OpenAlex pourries (ex. Pierre Mathieu): trouver un moyen de les déclarer inutilisables / ou cesser totalement d'utiliser les authorships OpenAlex? étudier les options
* [ ] Publications rattachées au mauvais compte HAL: cf Marc Andre: trouver moyen de rejeter le compte et garder les publis
* [ ] afficher quand compte HAL relié ou non à l'ORCID
* [ ] rendre personnes RH infusionnables


## Structures
* [x] créer page détails (laboratories/[id])
* [x] authorships orphelines: interface pour les visualiser et les rattacher à des personnes
* [x] filtres à facettes dynamiques avec comptage sur la page labo
* [ ] onglet dashboard
* [ ] signatures: afficher nombre de publis + dates; trier par publis décroissantes; idem sur page personne
* [ ] afficher identifiants (AuréHAL, OpenAlex, WoS) avec liens

## Publications
* [x] diagnostiquer le lag (tester requêtes)
* [x] idem page stats (revues): requête très lente
* [x] créer page détails (publications/[id])
* [x] filtre Source: 3 options par source (absent, présent, tous)
* [x] dans les filtres: ajouter option "aucun labo"
* [x] type "preprint": apparaît "autre" dans les extractions OpenAlex (https://openalex.org/works/W4407574839); voir ce qu'il en est dans les extractions HAL (le compte de préprints est zéro)
* [x] Open Access diamond?
* [ ] ajouter filtre corresponding_is_uca?
* [ ] publications de type "article" avec source OpenAlex et revue inconnue: généralement des préprints sur des archives en ligne: diagnostiquer et  corriger + source theses.fr => corriger type
* [ ] lien Publications -> Dashboard?
* [ ] merge manuel + suggestion de candidats
* [ ] pb des auteurs openalex liés à une personne mais non listés dans les auteurs d'une publi: http://172.22.130.105/bibliometrie/publications/12380
* [ ] preprints en accès gold?

## Pages supplémentaires, étudier pertinence
* [ ] sujets
* [ ] éditeurs
* [ ] revues (avec liens doaj; apc)


# Interface
* [x] Export csv tableaux
* [x] Export png graphiques
* [x] Légende dans export png
* [x] Filtres à facettes dynamiques avec comptage
* [x] lien retour: seulement si historique existe
* [x] sources: arrangées verticalement dans un dropdown
* [ ] Toujours mémoriser filtres et les rétablir au rechargement
* [ ] Rendre les filtres sticky
* [ ] Rendre tous les tableaux triables
* [ ] labo: filtres personnes
* [ ] afficher todo et nouveautés?
* [ ] interface pour afficher le staging (pour vérif)

# Trucs pour plus tard
* compte fractionnaire?
* collaborations nationales et internationales?