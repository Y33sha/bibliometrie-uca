pg_dump -U lalecoz -d publisher_stats -F c -f bibliometrie.dump
* [ ] automatiser les dumps

# Sources de données

* [ ] autres sources: ArXiv, Pubmed, ScannR?

## APC
* [x] trouver APC par revue
* [x] intégrer données APC DPCG
* [ ] estimer APC par structure (gold+hybride avec auteur correspondant sauf Elsevier)
* [ ] exploiter OpenAPC

## OpenAlex
* [ ] re-fetch individuel des docts OpenAlex plafonnés à 100 authorships (auteurs UCA au-delà de la pos. 100 sont perdus)
* [ ] importer orcid des openalex authors seulement quand display_name = raw_author_name (et pas d'initiale)
* [ ] type peer_review: les auteurs qui apparaissent sont ceux de l'article

## HAL
* [x] inclure collections HAL CHU-CLERMONTFERRAND et CLERMONT-AUVERGNE-INP
* [ ] fetch documents HAL référencés par OpenAlex mais absents des collections UCA
* [ ] documents > 2000 auteurs: relancer le script pour peupler la table authorships
* [ ] problème des documents où l'affiliation de l'authorship n'est pas résolue: cf https://hal.science/hal-04987032
* [ ] retraitement pour les authorships sans auteur_id (prendre strings?)
* [ ] revue Openalex 'HAL (Le Centre pour la Communication Scientifique Directe)' => parfois absents de HAL! Auditer docts source OpenAlex, ref HAL, HAL non trouvé => supprimer
* [ ] https://hal.science/hal-03874894 => lien OA vers autre archive ouverte: en tenir compte pour le statut green
* [ ] DOI identique mais type différent: ne pas fusionner (ouvrages + chapitres, conf + posters, etc.)
* [ ] trous dans la numérotation des auteurs: diagnostiquer et résoudre
* [ ] fichiers sous embargo: est-ce qu'à la fin de l'embargo le statut va se mettre à jour tout seul? (est-ce que le hash change au réimport quand l'embargo prend fin?)

## ORCID
* [ ] moissoner crossref via ORCID pour trouver publis absentes de HAL, OpenAlex et WoS?
* [ ] exploitation de l'API ORCID pour moissonner par affiliation?

## Unpaywall
* [ ] Finir l'audit Unpaywall vs OpenAlex
* [ ] utiliser unpaywall pour interroger type doc?
pb des types non fiables sur OpenAlex: https://openalex.org/works/W4225722715

## Workflow
* [ ] nouveaux imports: comment prendre en compte fusions de comptes auteurs ayant eu lieu entre-temps (par ex. sur HAL)? / + ré-importer et écraser publis déjà présentes et modifiées entre-temps (stocker hash puis comparer?)
* [ ] automatiser imports réguliers (1/semaine?)

# Développement

## Adresses
* [ ] interface de repérage: filtres sur la base des autres structures reconnues
* [ ] validation des adresses (forme correcte): à mettre en place si pertinent
* [ ] publis sans adresses (HAL) => scraper les sites éditeurs pour trouver adresses?
* [ ] supprimer formes de noms redondantes

## Personnes
* [x] moissonner ORCID liés aux comptes HAL (processing/harvest_hal_orcids.py — 12125 ORCID récupérés) => quelle place dans le pipeline?
* [x] déduplication automatisée par labo (merge_lab_duplicates.py — homonymes + interversions nom/prénom)
* [x] publications: indiquer si auteur correspondant / premier auteur
* [x] permettre confirmation orcid
* [x] rendre personnes RH infusionnables
* [x] interface de déduplication des personnes (par nom + par conflit de sources)
* [x] ORCID/idHAL confirmés manuellement: affichés en vert sur les pages publiques
* [x] recalcul des noms normalisés (tirets résiduels corrigés — 1069 personnes)
* [ ] correction des noms; création de personnes, interface de gestion des formes de noms
* [ ] ajouter IdRef? => fait pour comptes HAL; chercher les autres
* [ ] ajouter quelques visus (%OA)
* [ ] Publications rattachées au mauvais compte HAL: cf Marc Andre: trouver moyen de rejeter le compte et garder les publis
* [ ] afficher quand compte HAL relié ou non à l'ORCID

## Mega-authorships et alignement inter-sources
* [ ] publications > 50 auteurs: désalignement des positions entre HAL/OpenAlex/WoS → faux conflits en cascade. Approche envisagée: table `authorship_alignments` (publication_id, hal_authorship_id, oa_authorship_id, wos_authorship_id) + algorithme d'alignement par matching de noms (person_id commun → sûr, sinon Levenshtein/token overlap)
* [ ] OpenAlex cap 100 authorships: re-fetch individuel via API pour récupérer les auteurs UCA au-delà de la position 100
* [ ] en attendant, le mode "conflit de sources" dans la dédup personnes exclut les publis > 50 auteurs (constante `MAX_AUTHORS_CONFLICT`)

## Structures
* [x] créer page détails (laboratories/[id])
* [x] authorships orphelines: interface pour les visualiser et les rattacher à des personnes
* [x] filtres à facettes dynamiques avec comptage sur la page labo
* [ ] onglet dashboard
* [ ] signatures: afficher nombre de publis + dates; trier par publis décroissantes; idem sur page personne
* [ ] afficher identifiants (AuréHAL, OpenAlex, WoS) avec liens
* [ ] ajout de formes de nom ne marche pas (erreur 500)

## Publications
* [ ] ajouter filtre corresponding_is_uca?
* [ ] publications de type "article" avec source OpenAlex et revue inconnue: généralement des préprints sur des archives en ligne: diagnostiquer et corriger + source theses.fr => corriger type
* [ ] lien Publications -> Dashboard?
* [ ] pb des auteurs openalex liés à une personne mais non listés dans les auteurs d'une publi: http://172.22.130.105/bibliometrie/publications/12380
* [ ] preprints en accès gold?
* [ ] authorship supprimée: publi apparaît toujours (julie gardette)
* [ ] source theConversation: pas closed, et pas vraiment "article"; détecter les sources qui s'apparentent à de la vulgarisation, les taguer dans la table journals?
### Types de documents
* [ ] gérer le document type "correction" sur wos, "erratum" sur OA (actuellement, apparaît comme article) (Corrigendum to ...)
* [ ] type peer-review?
* [ ] HAL compte-rendu => "autre"
* [ ] type review (compte-rendu): parfois utilisé pour des revues de la littérature, alors que ça devrait être des articles (?); auditer
* [ ] posters

## Pages supplémentaires, étudier pertinence
* [ ] sujets
* [ ] éditeurs
* [ ] revues (avec liens doaj; apc)


# Interface
* [ ] Toujours mémoriser filtres et les rétablir au rechargement
* [ ] Rendre les filtres sticky
* [ ] Rendre tous les tableaux triables
* [ ] afficher todo et nouveautés?
* [ ] interface pour afficher le staging json (pour vérif)

# Trucs pour plus tard
* compte fractionnaire?
* collaborations nationales et internationales?
