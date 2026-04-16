# Memo
pg_dump -U lalecoz -d bibliometrie -Fc -f bibliometrie.dump
pg_restore -U lalecoz -d bibliometrie --clean --if-exists bibliometrie.dump
## Pipeline
* [ ] hal-id non trouvé dans hal en cross-import => ajouter une phase qui supprime les hal-id erronés des external_ids
* [ ] algo de déduplication publications: faire un truc + chiadé et l'insérer après phase "création publications".
* [ ] y aura-t-il un cross-import sur le cross-import au run suivant?
* [ ] conserver le json brut dans des fichiers: /data/raw/{source}/{source_id}.json.gz pour l'auditabilité des données brutes
## Robustesse du pipeline sur le long terme
* [ ] quid des changements d'authorships quand réimport avec hash différent? vérifier qu'elles sont bien supprimées avant recréation
* [ ] authorships excluded: info perdue si réimport (grave?)
## Imports csv
* [ ] re-tester le circuit des imports RH, vérifier que la logique de déduplication est la même que pour les personnes générées par le pipeline (modulo l'interdiction de supprimer) => pas urgent, pas d'imports csv à terme en prod
## Chantiers au long cours
* [ ] chercher des moyens d'optimiser la taille de la base: supprimer données qui ne sont plus utiles? ex.: supprimer *_authors et *_structures (sauf hal)? chercher colonnes jamais utilisées. Externaliser dans des fichiers json par publi les authorships sources.
* [ ] audit complet du code pour retrouver tous les trucs hardcodés qu'on pourrait abstraire, ou le SQL à simplifier suite aux fusions des tables sources. 
## Trucs où je me tâte: explorer différents scénarios, évaluer +/-
* [ ] création publishers et journals: avant la phase publications du pipeline, pas en normalisation?
* [ ] auditer le code pour voir où l'interface continue de requêter les sources (sauf trucs source-spécifiques)
* [ ] in_perimeter BOOL: étudier l'intérêt de passer à perimeter_ids INT[] ?
# Données
## Explorer autres sources possibles
* [ ] pour les publis: CrossRef, ArXiv, Pubmed, Sudoc? (liens personnes-thèses plus complets que theses.fr, j'ai l'impression)
* [ ] pour les jeux de données: DataCite, autres?
* [ ] brevets?
* [ ] divers: ORCID, IdRef, OpenAPC, DOAJ, scraping sites éditeurs pour les adresses manquantes? (soyons fous)
## Entités supplémentaires
* [ ] sujets / mots-clés: exploiter
## Qualité des données
* [ ] Mettre en place le process pour détecter les publications disparues et les nettoyer de la base (ou les archiver?).
* [ ] hal_authors importés sans id par un script de cross-import: ça ne devrait pas être possible. Auditer.
* [ ] publis OpenAlex avec date correspondant au dépôt dans HAL: ex. 8651 => si dates différentes, utiliser l'autre. Si OA cite HAL comme source, prendre métadonnées HAL
* [ ] depuis que la déduplication automatique par identité de métadonnées a été abandonnée: passer en revue les cas concernés, auditer, re-dupliquer?
* [ ] thèses d'autres établissements liés à nos labos: enlever de la page thèses? (où se trouve la métadonnée établissement?) => ou cacher si pas de source theses.fr?
* [ ] investiguer les 388k doublons de position WoS (source_authorships, même publi, même position)
### Problèmes spécifiques HAL
* [ ] fichiers HAL sous embargo: est-ce qu'à la fin de l'embargo le statut va se mettre à jour tout seul? (est-ce que le hash change au réimport quand l'embargo prend fin?) - je pense que oui; trouver un exemple d'embargo qui se termine prochainement et voir ce qui se passe.
* [ ] https://hal.science/hal-03874894 => lien OA vers *autre* archive ouverte que HAL: en tenir compte pour le statut green
* [ ] DOI identique mais type différent: garde-fou mis en place pour ouvrages + chapitres, voir si pertinent pour conf + posters, ou autres cas: article + peer_review/erratum/preprint?
* [ ] trous dans la numérotation des auteurs: diagnostiquer et résoudre
* à quoi sert VRAIMENT la colonne collections du staging_hal?
* [ ] embargos (HAL, theses.fr): afficher dates (existent-elles dans le retour api)?
* [ ] Publications rattachées au mauvais compte HAL: cf Marc Andre: trouver moyen de rejeter le compte et garder les publis (authorship ok, author pas ok => vérifier que ce ne sera pas ré-écrasé)
### Chantier "Types de documents"
* [ ] types parfois non fiables sur OpenAlex: https://openalex.org/works/W4225722715 (utiliser Unpaywall aussi pour corriger type doc?)
* [ ] publications de type "article" avec source OpenAlex et revue inconnue: généralement des préprints sur des archives en ligne: diagnostiquer et corriger + source theses.fr => corriger type
* [ ] enum type doc à revoir: correction/erratum/corrigendum; compte-rendu (= autre sur HAL); review (= book review ou revue de la littérature?); posters (ne pas fusionner avec conf si même DOI?); preprints en accès gold selon OpenAlex (?); data papers?
* [ ] types wos composites: étudier, voir s'il s'agit de types/sous-types
* "prépublication, document de travail" dans HAL apparaît comme other
### Chantier des méga-authorships et alignement inter-sources
* [ ] publications > 50 auteurs: désalignement des positions entre HAL/OpenAlex/WoS → faux conflits en cascade. Approche envisagée: table `authorship_alignments` (publication_id, hal_authorship_id, oa_authorship_id, wos_authorship_id) + algorithme d'alignement par matching de noms (person_id commun → sûr, sinon Levenshtein/token overlap)
* [ ] en attendant, le mode "conflit de sources" dans la dédup personnes exclut les publis > 50 auteurs (constante `MAX_AUTHORS_CONFLICT`)
* [ ] vérifier pourquoi Openalex contient parfois beaucoup plus d'auteurs : ex. 21105 (OpenAlex semble résoudre les noms d'équipes en listes de noms de personnes, mais je ne sais pas comment)
### Chantier Journals/Publishers
* [ ] contrôler données journal/doc_type via DOI? => DOI peut permettre de dédoublonner journals
* [ ] utiliser DOAJ pour enrichir données journals et s'en servir pour contrôler oa_status?
* [ ] source theConversation: pas closed (statut oa erroné), et pas vraiment "article"; détecter les sources qui s'apparentent à de la vulgarisation, les taguer dans la table journals?
# Interface
## Admin
### Adresses
* [ ] interface de repérage des adresses: ajouter filtres sur la base des autres structures reconnues dans l'adresse
* [ ] pays des adresses: aller plus loin dans l'automatisation de la détection (GeoNames? index n-gram des adresses avec pays associés et degré de certitude?)
* [ ] interface pour gérer les noms de pays? (actuellement table statique, rien n'y écrit)
### Personnes (admin)
* [ ] quoi faire des entités fausses? a minima, rejeter leurs authorships et s'assurer qu'elles n'apparaissent pas dans orphan-authorships
* [ ] si source erronée: rejeter authorship source + recalculer affiliations de l'authorship à partir des sources non rejetées / caveat: Clarifier la sémantique de `excluded` sur les authorships sources: est-ce l'authorship qui est fausse, ou son affiliation? (allons plus loin: pourrait-on déclarer fausses certaines colonnes et pas d'autres? via un champ jsonb par exemple)
### Publishers / Journals
* [ ] Tri facettes
* [ ] publishers: distinguer types d'entités (établissements d'enseignement, sociétés savantes, éditeurs commerciaux)
## Publique
### Personnes (public)
#### Urgent
* [ ] filtre "publications avec authorship UCA": certains ont 500 publications mais une seule en tant qu'auteur UCA, ça aiderait à les retrouver pour les vérifier
* [ ] ajouter dashboard personne
#### Autres
* [ ] publications: indiquer si premier/dernier auteur ; + rôles autres que auteur?
* [ ] signaler publis HAL non correctement reliées au compte HAL (dans la page problèmes-hal?)
### Structures (public)
* [ ] Onglet adresses des pages personnes/id et laboratoire/id: afficher nombre de publications liées à chaque adresse; créer possibilité de consulter la liste?; normaliser adresses pour diminuer le nombre de variantes liées à des différences de ponctuation?
### Publications
* [ ] filtre langue? (y a-t-il un code langue unique trans-sources? sinon, faire une table langues)
* [ ] ajouter DOI dans les facettes sources
* [ ] relations entre publications (est traduction de, est preprint de..., fait partie de..., data paper décrit dataset, dataset référencé dans...)
* [ ] ajouter filtre corresponding_is_uca?
* [ ] avoir des groupes de pays (UE, continents) pour la recherche par facettes
## Général (interface)
* [ ] Toujours mémoriser filtres et les rétablir au rechargement
* [ ] Rendre tous les filtres sticky
* [ ] Rendre tous les tableaux triables
* [ ] différencier interfaces à usage interne vs externe (users, roles)
* [ ] accessibilité, responsivité de l'interface
* [ ] tableaux personnes remplacer les identifiants par des icônes (hal orcid idref)
* [ ] étoffer tests frontend
* [ ] export csv tableaux thèses
## Détails d'affichage
* [ ] titres 30% minimum de la largeur du tableau; diminuer taille titre revue
* [ ] dropdown titres revues: tronquer, sinon parfois plus large que la page
* [ ] décomptes sur les onglets: ne pas tenir compte des facettes en place
* [ ] décomptes facettes: toujours aligné à droite
* [ ] ordre des sources pour les thèses: harmoniser page laboratoire avec page thèses
# Trucs pour plus tard
* compte fractionnaire des publications?
* collaborations nationales et internationales: identification structures? compliqué, je pense que pour ça il vaut mieux réutiliser les sources directement
* creuser le format de données CERIF, voir si c'est pertinent pour mon besoin
* [ ] OpenAlex et WOS: mapping structures UCA pour pouvoir comparer sources/vérité?
# Cas particuliers, bizarreries à élucider, à examiner plus tard
* openalex répète des auteurs : publi 77832
* [ ] 79637: authorship source rejetée => la rejeter de l'authorship vérité
* erreur de parsing OA: publication 113652
* thèses CHELTER: 3 ou 4?