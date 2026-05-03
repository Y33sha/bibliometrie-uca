- examiner cette publi: 21743 (authors openalex)

# A régler avant transmission
## Pipeline
* [ ] hal-id non trouvé dans hal en cross-import => ajouter une phase qui supprime les hal-id erronés des external_ids
* [ ] conserver le json brut dans des fichiers: /data/raw/{source}/{source_id}.json.gz pour l'auditabilité des données brutes (et pouvoir faire l'économie du stockage des source_authorships hors périmètre)
* [ ] algo de déduplication publications: faire un truc + chiadé et l'insérer après phase "création publications".
* [ ] quid des changements d'authorships quand réimport avec hash différent? vérifier qu'elles sont bien supprimées avant recréation => oui, mais pas authorships canoniques. Pruning dans build_authorships?
* [ ] Mettre en place le process pour détecter les publications disparues et les nettoyer de la base (ou les archiver?). + publis du cross-import: re-fetch régulier pour tenir les données à jour
* [ ] https://hal.science/hal-03102156, https://hal.science/hal-03624131: deux fois le même auteur hal, une fois erroné: que faire? on ne devrait jamais avoir 2 fois le même hal_person_id dans une publi => lever une erreur
* [ ] suggest_countries extrêmement lent: auditer
## Trucs où je me tâte: explorer différents scénarios, évaluer +/-
* [ ] création publishers et journals: avant la phase publications du pipeline, pas en normalisation?
* [ ] cross-import: seulement in_perimeter? (ie seulement au run suivant) => éviter de cross-importer des trucs rejetés pendant la phase affiliations
* [ ] in_perimeter BOOL: étudier l'intérêt de passer à perimeter_ids INT[] ?
* [ ] thèses d'autres établissements liés à nos labos: enlever de la page thèses? (où se trouve la métadonnée établissement?) => ou cacher si pas de source theses.fr?
## Problèmes spécifiques HAL
* [ ] fichiers HAL sous embargo: est-ce qu'à la fin de l'embargo le statut va se mettre à jour tout seul? (est-ce que le hash change au réimport quand l'embargo prend fin?) - je pense que oui; trouver un exemple d'embargo qui se termine prochainement et voir ce qui se passe.
* [ ] embargos (HAL, theses.fr): afficher dates (existent-elles dans le retour api)?
* [ ] https://hal.science/hal-03874894 , https://hal.science/hal-04111614 => lien OA vers *autre* archive ouverte que HAL: en tenir compte pour le statut green
* [ ] DOI identique mais type différent: garde-fou mis en place pour ouvrages + chapitres, voir si pertinent aussi pour conf + posters, ou autres cas: article + peer_review/erratum/preprint?
## Code
* [ ] vérifier si certains ports ne seraient pas mieux placés dans application/ (critère: sont-ils importés par domain/ ou pas?)
* [ ] auditer le code pour voir où l'interface continue de requêter les sources (sauf trucs source-spécifiques): supprimer les requêtes vers source_authorships pouvant être remplacées par des requêtes vers les tables canoniques
* [ ] problème page affiliation-conflicts: requête beaucoup trop lente

# Chantiers qui peuvent continuer en prod (Qualité des données)
## Sujets
* [ ] sujets openalex souvent hors sujet: auditer; créer circuit de curation des sujets? / ajouter seuil de score de pertinence?
## Explorer autres sources possibles
* [ ] pour les publis: ArXiv, Pubmed, Sudoc? (liens personnes-thèses plus complets que theses.fr, j'ai l'impression); récupérer pmid dans api HAL
* [ ] pour les jeux de données: DataCite, autres?
* [ ] brevets? INPI?
* [ ] divers: ORCID, IdRef, DOAJ
## Types de documents: fixer l'enum et le mapping, algo de résolution de conflits
* [ ] publications de type "article" avec source OpenAlex et revue inconnue: généralement des préprints sur des archives en ligne: diagnostiquer et corriger + source theses.fr => corriger type
* [ ] enum type doc à revoir: correction/erratum/corrigendum; compte-rendu (= autre sur HAL); review (= book review ou revue de la littérature?); posters (ne pas fusionner avec conf si même DOI?); preprints en accès gold selon OpenAlex (?); data papers?
* [ ] types wos composites: étudier, voir s'il s'agit de types/sous-types
* [ ] "prépublication, document de travail" dans HAL apparaît comme other
## Journals/Publishers
* [ ] publishers: distinguer types d'entités (établissements d'enseignement, sociétés savantes, éditeurs commerciaux)
* [ ] source theConversation: pas closed (statut oa erroné), et pas vraiment "article"; détecter les sources qui s'apparentent à de la vulgarisation, les taguer dans la table journals?
* [ ] utiliser DOAJ pour enrichir données journals et s'en servir pour contrôler oa_status?
* [ ] contrôler données journal/doc_type via DOI? + DOI peut permettre de dédoublonner journals
## Méga-authorships et alignement inter-sources
* [ ] publications > 50 auteurs: désalignement des positions entre HAL/OpenAlex/WoS → faux conflits en cascade. Approche envisagée: table `authorship_alignments` (publication_id, hal_authorship_id, oa_authorship_id, wos_authorship_id) + algorithme d'alignement par matching de noms (person_id commun → sûr, sinon Levenshtein/token overlap)
* [ ] en attendant, le mode "conflit de sources" dans la dédup personnes exclut les publis > 50 auteurs (constante `MAX_AUTHORS_CONFLICT`)
* [ ] vérifier pourquoi Openalex contient parfois beaucoup plus d'auteurs : ex. 21105 (OpenAlex semble résoudre les noms d'équipes en listes de noms de personnes, mais je ne sais pas comment)
## Chantier des signatures institutionnelles
### Côté backend
* [ ] pays des adresses: aller plus loin dans l'automatisation de la détection (GeoNames? index n-gram des adresses avec pays associés et degré de certitude?)
* [ ] distinguer adresses correctes/incorrectes pour affichage %age par labo/personne
### Côté interface admin
* [ ] interface de repérage des adresses: ajouter filtres sur la base des autres structures reconnues dans l'adresse
* [ ] interface pour gérer les noms de pays? (actuellement table statique, rien n'y écrit)
### Côté interface publique
* [ ] Onglet adresses des pages personnes/id et laboratoire/id: afficher nombre de publications liées à chaque adresse; créer possibilité de consulter la liste?; normaliser adresses pour diminuer le nombre de variantes liées à des différences de ponctuation?

# Détails à régler au fil de l'eau (interface)
## Admin
* [ ] interface pour consulter l'audit trail
### Personnes (admin)
* [ ] quoi faire des entités fausses? a minima, rejeter leurs authorships et s'assurer qu'elles n'apparaissent pas dans orphan-authorships
* [ ] si source erronée: rejeter authorship source + recalculer affiliations de l'authorship à partir des sources non rejetées / caveat: Clarifier la sémantique de `excluded` sur les authorships sources: est-ce l'authorship qui est fausse, ou son affiliation? (allons plus loin: pourrait-on déclarer fausses certaines colonnes et pas d'autres? via un champ jsonb par exemple)
* [ ] date de dernière publication UCA? (permet de filtrer les auteurs "legacy" vs actifs)
### Publishers / Journals
* [ ] Tri facettes
## Publique
### Personnes (public)
* [ ] signaler publis HAL non correctement reliées au compte HAL (dans la page problèmes-hal?)
* [ ] publications: indiquer si premier/dernier auteur
### Publications
* [ ] filtre langue? (y a-t-il un code langue unique trans-sources? sinon, faire une table langues)
* [ ] ajouter DOI dans les facettes sources?
* [ ] relations entre publications (est traduction de, est preprint de..., fait partie de..., data paper décrit dataset, dataset référencé dans...) => quasiment un nouveau chantier données à part entière
* [ ] ajouter filtre corresponding_is_uca?
* [ ] avoir des groupes de pays (UE, continents) pour la recherche par facettes
## Général (interface)
* [ ] Toujours mémoriser filtres et les rétablir au rechargement
* [ ] Rendre tous les filtres sticky
* [ ] Rendre tous les tableaux triables
* [ ] différencier interfaces à usage interne vs externe (users, roles)
* [ ] responsivité minimale de l'interface
* [ ] étoffer tests frontend
## Détails d'affichage
* [ ] décomptes sur les onglets: ne pas tenir compte des facettes en place
* [ ] ordre des sources pour les thèses: harmoniser page laboratoire avec page thèses
* [ ] admin/personnes, formes de nom: modal authorships: source affichée: default wos (ajouter les autres sources, et mettre default None)
* [ ] colonne auteur sur la page thèses
* [ ] sujets: layout différent des autres pages?
* [ ] affichage des caractères &amp;lt;i&amp;gt; (publi 78307)

# Cas particuliers, bizarreries à élucider
* openalex répète des auteurs : publi 77832
* [ ] 79637: authorship source rejetée => la rejeter de l'authorship vérité
* erreur de parsing OA: publication 113652
* thèses CHELTER: 3 ou 4?
* publi 20832: pourquoi pas d'affiliations
* 2020CLFAC007 thèse du CROC, pas récupérée via theses.fr! (158960) => aurait dû être récupéré par API theses.fr ET par cross-import de scanR via le NNT

# Trucs pour plus tard, éventuellement
* stats en compte fractionnaire vs compte entier
* collaborations nationales et internationales: identification structures? compliqué, je pense que pour ça il vaut mieux réutiliser les sources directement: contrôler seulement cohérence entre sources et corriger quand incohérent?

# Pas nécessaire de le régler, du moment qu'on le documente
* [ ] re-tester le circuit des imports RH, vérifier que la logique de déduplication est la même que pour les personnes générées par le pipeline (modulo l'interdiction de supprimer) => pas urgent, pas d'imports csv à terme en prod
