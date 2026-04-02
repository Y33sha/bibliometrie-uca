pg_dump -U lalecoz -d publisher_stats -F c -f bibliometrie.dump
* [ ] programmation cron pour les dumps de sauvegarde
* [ ] programmation cron pour les imports

# Sources de données

* [ ] autres sources: ArXiv, Pubmed, ScannR?

## APC
* [ ] exploiter OpenAPC

## OpenAlex
* [x] re-fetch individuel des docts OpenAlex plafonnés à 100 authorships (auteurs UCA au-delà de la pos. 100 sont perdus)
* [ ] importer orcid des openalex authors seulement quand display_name = raw_author_name (et pas d'initiale)
* [ ] type peer_review: les auteurs qui apparaissent sont ceux de l'article

## HAL
* [x] fetch documents HAL référencés par OpenAlex mais absents des collections UCA
* [ ] problème des documents où l'affiliation de l'authorship n'est pas résolue: cf https://hal.science/hal-04987032
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
* [x] publications: indiquer si auteur correspondant / premier auteur
* [ ] correction des noms; création de personnes, interface de gestion des formes de noms
* [ ] ajouter IdRef? => fait pour comptes HAL; chercher les autres; + add_identifiers_from_authorships ne tient compte que d'orcid et idhal
* [ ] ajouter quelques visus (%OA)
* [ ] Publications rattachées au mauvais compte HAL: cf Marc Andre: trouver moyen de rejeter le compte et garder les publis
* [ ] afficher quand compte HAL relié ou non à l'ORCID
* [ ] dans l'onglet "identités", mettre une condition "excluded = false" pour éviter de faire apparaître des comptes HAL erronés
* [ ] forme de nom avec zéro authorship liée: option de supprimer

## Mega-authorships et alignement inter-sources
* [ ] publications > 50 auteurs: désalignement des positions entre HAL/OpenAlex/WoS → faux conflits en cascade. Approche envisagée: table `authorship_alignments` (publication_id, hal_authorship_id, oa_authorship_id, wos_authorship_id) + algorithme d'alignement par matching de noms (person_id commun → sûr, sinon Levenshtein/token overlap)
* [ ] OpenAlex cap 100 authorships: re-fetch individuel via API pour récupérer les auteurs UCA au-delà de la position 100
* [ ] en attendant, le mode "conflit de sources" dans la dédup personnes exclut les publis > 50 auteurs (constante `MAX_AUTHORS_CONFLICT`)

## Structures
* [ ] signatures: afficher nombre de publis + dates; trier par publis décroissantes; idem sur page personne

## Publications
* [ ] ajouter filtre corresponding_is_uca?
* [ ] publications de type "article" avec source OpenAlex et revue inconnue: généralement des préprints sur des archives en ligne: diagnostiquer et corriger + source theses.fr => corriger type
* [ ] lien Publications -> Dashboard?
* [ ] pb des auteurs openalex liés à une personne mais non listés dans les auteurs d'une publi: http://172.22.130.105/bibliometrie/publications/12380
* [ ] preprints en accès gold?
* [ ] authorship supprimée: publi apparaît toujours (julie gardette)
* [ ] source theConversation: pas closed, et pas vraiment "article"; détecter les sources qui s'apparentent à de la vulgarisation, les taguer dans la table journals?
* [ ] si source erronée: rejeter authorship source + recalculer affiliations de l'authorship à partir des sources non rejetées
* [ ] quid des changements d'authorships quand réimport avec hash différent? supprimer avant de recréer?
* [ ] afficher les abstracts?
* [ ] dédoublonner DOI figshare (.v1)
* [ ] fonction pour casser affiliations UCA d'une publication (authorships vérité => déclarer fausses les affiliations au niveau des sources pour éviter qu'elles soient reconstruites)
* [ ] ne pas afficher "non applicable" dans les pays! (ni dans les facettes)
* [ ] avoir des groupes de pays (UE, continents) pour la recherche par facettes
* [ ] 79637: authorship source rejetée => la rejeter de l'authorship vérité

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
* [ ] interface pour afficher le staging json (pour vérif)
* [ ] différencier interfaces à usage interne vs externe? (rôles?)

# Trucs pour plus tard
* compte fractionnaire?
* collaborations nationales et internationales: identification structures

## Bizarreries à élucider
* openalex répète des auteurs : publi 77832
* claire richard: pourquoi 0 publi UCA sur page admin?
* publi 103567: structures identifiées sur HAL: UCA, Inserm: pourquoi?
* personne 57907: comprendre comment Damien Boyer a pu devenir une de ses formes de nom

* checkmark dans dropdrown de la page authorships_orphelines => pb affichage