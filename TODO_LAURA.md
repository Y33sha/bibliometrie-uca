# Workflow
## Automatisation
* [x] programmation cron pour les dumps de sauvegarde: `pg_dump -U lalecoz -d bibliometrie -F c -f bibliometrie.dump`
* [ ] programmation cron pour le pipeline de traitement

## Transmissibilité
* [ ] générer un seed avec les données nécessaires au démarrage *de novo* (structures uca...)

## Pérennité
* [ ] nouveaux imports: comment prendre en compte fusions de comptes auteurs ayant eu lieu entre-temps (par ex. sur HAL)? / + ré-importer et écraser publis déjà présentes et modifiées entre-temps (stocker hash puis comparer?)
* [ ] Comment se met à jour le référentiel structures HAL en cas de changement entre deux imports? faut-il des champs `hash` et `last_seen_at` comme pour les publis?
* [ ] quid des changements d'authorships quand réimport avec hash différent? vérifier qu'elles sont bien supprimées avant recréation
* [ ] authorships excluded: info perdue si réimport (grave?)
* [ ] fichiers HAL sous embargo: est-ce qu'à la fin de l'embargo le statut va se mettre à jour tout seul? (est-ce que le hash change au réimport quand l'embargo prend fin?)
* [ ] Mettre en place le process pour détecter les publications disparues et les nettoyer de la base (ou les archiver?).
* [ ] re-tester le circuit des imports RH, vérifier que la logique de déduplication est la même que pour les personnes générées par le pipeline (modulo l'interdiction de supprimer)
* [ ] Tester que le meta_hash fonctionne effectivement et que les publis de >100 auteurs ne sont pas écrasées au réimport.

## Pipeline
* [ ] dédoublonnage DOI figshare (.v1)
* [x] dédoublonnage documents Zenodo avec DOI distincts (appel API Zenodo si 2 titres identiques?)
* [ ] backfilling wos_organizations: relancer  python scripts/backfill_wos_institutions.py jusqu'à ce qu'il soit fini puis supprimer

# Trucs techniques
* [ ] table perimeters mal torchée: devrait inclure un jsonb avec id structures + bool "with children"
* [ ] chercher des moyens d'optimiser la taille de la base (supprimer données qui ne sont plus utiles? ex.: supprimer staging après normalisation, supprimer données sources des publications hors périmètre?)

# Sémantique
* [ ] harmoniser les noms de routes API avec les url frontend
* [ ] is_uca encode en dur le nom de l'UCA dans les noms de colonnes de la base de données. Pas terrible pour la réutilisabilité. idem: rôles des 2 périmètres uca et uca_wide (is_uca, structure_ids), à rendre configurable; idem, phase uca_flags à renommer pour plus d'abstraction?
* [ ] publications => plutôt des documents

# Sources de données

## Explorer autres sources possibles
* [ ] pour les publis: ArXiv, Pubmed, ScanR, CrossRef
* [ ] pour les jeux de données: DataCite, autres?
* [ ] pour les thèses: theses.fr
* [ ] brevets?
* [ ] divers: ORCID, IdRef, OpenAPC, DOAJ, scraping sites éditeurs pour les adresses manquantes? (soyons fous); figshare, zenodo

## Structure des données sources
* [ ] OpenAlex et WOS: mapping structures UCA: pour remplacer la config manuelle des requêtes API + pouvoir comparer sources/vérité
* [ ] différents rôles auteurs dans les authorships? (auteur, dir., trad.... sera particulièrement utile pour les thèses: rapporteur, jury...)

## Entités supplémentaires
* [ ] sujets / mots-clés: exploiter
* [ ] éditeurs: table `publisher_name_forms` pour dédoublonner (selon sources: Elsevier vs 'Elsevier BV', etc.)
* [ ] revues (avec liens doaj; apc): pb des formes de noms différentes quand ISSN absent (JHEP vs Journal of High Energy Particles...): table `journal_name_forms`

## Qualité des données
* [ ] utiliser DOAJ pour enrichir données journals et s'en servir pour contrôler oa_status?

### Types de documents
* [ ] types parfois non fiables sur OpenAlex: https://openalex.org/works/W4225722715 (utiliser Unpaywall aussi pour corriger type doc?)
* [ ] publications de type "article" avec source OpenAlex et revue inconnue: généralement des préprints sur des archives en ligne: diagnostiquer et corriger + source theses.fr => corriger type
* [ ] enum type doc à revoir: correction/erratum/corrigendum; compte-rendu (= autre sur HAL); review (= book review ou reue de la littérature?); posters (ne pas fusionner avec conf si même DOI?); preprints en accès gold selon OpenAlex (?)
* [ ] source theConversation: pas closed (statut erroné), et pas vraiment "article"; détecter les sources qui s'apparentent à de la vulgarisation, les taguer dans la table journals?

### Problèmes spécifiques HAL
* [ ] problème des documents où l'affiliation de l'authorship n'est pas résolue: cf https://hal.science/hal-04987032
* [ ] revue Openalex 'HAL (Le Centre pour la Communication Scientifique Directe)' => parfois absents de HAL! Auditer docts source OpenAlex, ref HAL, HAL non trouvé => supprimer
* [ ] https://hal.science/hal-03874894 => lien OA vers *autre* archive ouverte que HAL: en tenir compte pour le statut green
* [ ] DOI identique mais type différent: garde-fou mis en place pour ouvrages + chapitres, voir si pertinent pour conf + posters, ou autres cas: article + peer_review/erratum/preprint?
* [ ] trous dans la numérotation des auteurs: diagnostiquer et résoudre
* à quoi sert VRAIMENT la colonne collections du staging_hal?

# Interface

## Admin

### Structures
* [ ] créer formes de noms excluantes? ex. "Zone Ateliers Territoires Uranifères" => reconnaît à tort UMR Territoires à cause du contexte Clermont

### Adresses
* [ ] interface de repérage des adresses: ajouter filtres sur la base des autres structures reconnues dans l'adresse 
* [ ] pays des adresses: automatiser la détection (table country_name_forms, pour commencer)

### Personnes (admin)
* [ ] quoi faire des entités fausses? a minima, rejeter leurs authorships et s'assurer qu'elles n'apparaissent pas dans orphan-authorships
* [ ] s'assurer que les formes de nom avec initiale prennent bien en compte les deux éléments d'un nom composé
* [ ] possibilité de confirmer formes de nom (pour voir du premier coup d'oeil les formes non confirmées)
* [ ] après pipeline, avoir un rapport avec personnes nouvellement créées et nouvelles formes de nom (+ personnes auxquelles elles sont mappées)
* [ ] si source erronée: rejeter authorship source + recalculer affiliations de l'authorship à partir des sources non rejetées / caveat: Clarifier la sémantique de `excluded` sur les authorships sources: est-ce l'authorship qui est fausse, ou son affiliation? (allons plus loin: pourrait-on déclarer fausses certaines colonnes et pas d'autres? via un champ jsonb par exemple)

## Publique

### Personnes (public)
* [ ] publications: indiquer si premier/dernier auteur ; + rôles autres que auteur?
* [ ] ajouter dashboard
* [ ] Publications rattachées au mauvais compte HAL: cf Marc Andre: trouver moyen de rejeter le compte et garder les publis
* [ ] signaler publis HAL non correctement reliées au compte HAL (dans la page problèmes-hal?)

### Structures (public)
* [ ] Onglet adresses des pages personnes/id et laboratoire/id: afficher nombre de publications liées à chaque adresse; créer possibilité de consulter la liste?; normaliser adresses pour diminuer le nombre de variantes liées à des différences de ponctuation?

### Publications
* [ ] ajouter filtre corresponding_is_uca?
* [ ] relations entre publications (est traduction de, est preprint de..., fait partie de...)
* [ ] afficher les abstracts dans la page publications/id
* [ ] avoir des groupes de pays (UE, continents) pour la recherche par facettes
* [ ] pages dédiées pour les datasets, les thèses?
* [ ] filtre langue? (y a-t-il un code langue unique trans-sources?)

### Mega-authorships et alignement inter-sources
* [ ] publications > 50 auteurs: désalignement des positions entre HAL/OpenAlex/WoS → faux conflits en cascade. Approche envisagée: table `authorship_alignments` (publication_id, hal_authorship_id, oa_authorship_id, wos_authorship_id) + algorithme d'alignement par matching de noms (person_id commun → sûr, sinon Levenshtein/token overlap)
* [ ] en attendant, le mode "conflit de sources" dans la dédup personnes exclut les publis > 50 auteurs (constante `MAX_AUTHORS_CONFLICT`)
* [ ] vérifier pourquoi Openalex contient parfois beaucoup plus d'auteurs : ex. 21105 (OpenAlex semble résoudre les noms d'équipes en listes de noms de personnes, mais je ne sais pas comment)

## Général
* [ ] Toujours mémoriser filtres et les rétablir au rechargement
* [ ] Rendre les filtres sticky
* [ ] Rendre tous les tableaux triables
* [ ] interface pour afficher le staging json (pour vérif)
* [ ] différencier interfaces à usage interne vs externe (rôles)

# Trucs pour plus tard
* compte fractionnaire des publications?
* collaborations nationales et internationales: identification structures? compliqué
* [ ] creuser le format de données CERIF, voir si c'est pertinent pour moi

# Cas particuliers, bizarreries à élucider
* openalex répète des auteurs : publi 77832
* claire richard: pourquoi 0 publi UCA sur page admin?
* publi 103567: structures identifiées sur HAL: UCA, Inserm: pourquoi?
* personne 57907: comprendre comment Damien Boyer a pu devenir une de ses formes de nom
* [ ] pb des auteurs openalex liés à une personne mais non listés dans les auteurs d'une publi: publi 12380
* [ ] 79637: authorship source rejetée => la rejeter de l'authorship vérité
* erreur de parsing OA: publication 113652