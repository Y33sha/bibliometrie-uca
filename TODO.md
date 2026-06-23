# A régler avant transmission
## Schéma
* [ ] décomposer la table source_authorships en plusieurs tables? (table identités auteurs distinctes (name_forms, identifiers) + table de liaison auteurs-publis-adresses): select count(*) from (select distinct person_id, author_name_normalized, person_identifiers from source_authorships) => 750k, vs 19M de rows actuellement dans source_authorships
## Pipeline de traitement
### Extraction
* [ ] extraction par ORCID: vérifier pertinence (tester différentes sources, auditer le gain)
* [ ] à étudier: cross-import: seulement `in_perimeter`? (ie seulement au run n+1) => éviter de cross-importer des trucs rejetés pendant la phase affiliations
* [ ] analyser les diff de payload pour voir si on peut diminuer le nombre d'UPSERT en filtrant les champs importés (ScanR notamment)
* [ ] scanR: paralléliser les années?
* [ ] refetch_truncated: envisager un flag `authors_truncated`
* [ ] biorxiv, medrxiv: identifiants différents de arxiv? cf publi 2757 (voir si on moissonne ces identifiants; possibilité de récupérer les DOI à partir des identifiants comme dans ArXiv)
* [ ] chercher dans ScanR par hal-id?
### Suite du traitement
* [ ] DOI versionnés: déplacer la correction (suppression de suffixes) depuis `clean_doi` vers `metadata_correction`. `clean_doi` devrait se borner au nettoyage simple.
* [ ] `metadata_correction`: en cas de corrections de champs multiples sur un même doc, les règles s'appliquent indépendamment à partir du brut; étudier les scénarios de corrections multiples où l'output d'une règle pourrait intersecter l'input des suivantes, voir s'il est pertinent de les chaîner ensemble
* [ ] créer circuit pour correction automatisée du `journal_type` (titre terminé par ` eBooks` => plateforme d'ebooks)
* [ ] `metadata_correction`: ajouter correction via `doi_prefix` du journal (contrôle de cohérence entre `doi` et `journal_id`, avant les corrections `journal_type` => `doc_type`)
* [ ] conflation de doc_types différents ou titres différents sous un même DOI => soit DOI erroné, soit métadonnées erronées. Auditer et définir règles de correction
## Code
* [ ] page "affiliations suspectes hal": requête incorrecte, capture beaucoup trop de publis + problème de perf
* [ ] Unit of Work: pertinent? voir transactions multi-repos
* [ ] Audit complet "nommage des variables". S'assurer que le code est structure-agnostique. Eviter abréviations (publication > publi > pub...). Revoir certains noms trop restrictifs (publication->document? journal->container?)
## Doc
* [ ] documenter la duplication de données (vues matérialisées, tables et colonnes dérivées) et leur cycle de vie + quantifier poids vs gain de performance en lecture
* [ ] documenter les process incrémentaux (flag `dirty`) vs recalcul complet, et les arbitrages entre gain de temps et risque de drift; chaque process incrémental doit avoir un mode `--full-rebuild`

# Chantiers qui peuvent continuer en prod (Qualité des données)
* [ ] DUMAS: comment distinguer mémoires et thèses d'exercice?
## Problèmes dans les sources
* [ ] DOI Crossref non trouvés sur Crossref: quel traitement ultérieur? (auditer; tenter corrections pour les cas simples (ponctuation parasite...); nuller les autres pour éviter que ça bloque une déduplication légitime)
## Explorer autres sources possibles
* [ ] pour les publis: ArXiv, Pubmed, Sudoc? (liens personnes-thèses plus complets que theses.fr, j'ai l'impression); Cairn, Persée pour augmenter couverture SHS?
* [ ] divers: ORCID, IdRef
* [ ] OpenAPC: j'ai utilisé les données sur les APC UCA, mais il faudrait partir du dump complet et matcher tous les DOI des publis UCA pour voir quels établissements ont payé les APC quand ce n'est pas l'UCA
## Chantier des signatures institutionnelles
* [ ] Onglet adresses des pages personnes/id et laboratoire/id: afficher nombre de publications liées à chaque adresse; créer possibilité de consulter la liste?; normaliser adresses pour diminuer le nombre de variantes liées à des différences de ponctuation?
* [ ] distinguer adresses correctes/incorrectes pour affichage %age par labo/personne; suppose: 1° de définir une typologie d'erreurs, et leur caractère bloquant ou non; 2° de grouper les signatures par publi pour interroger en pourcentage de publications, non en pourcentage de signatures; 3° de restreindre aux publications *stricto sensu* (ni preprint, ni dataset etc.: définir liste blanche de doc_types à prendre en compte); 4° question des publications sans signature en base (sources HAL/ScanR seulement): exclure du calcul?

# UI
* [ ] mettre en place des slugs pour les URL?
## Admin
* [ ] fusion / dé-fusion manuelle de publications: circuit à créer
* [ ] comportement capricieux de l'UI sur la page `admin/countries` (filtres qui sautent, mise à jour de l'UI à retardement): pistes de Claude: "loadAddresses() est appelé sans await après le POST, donc l'ordre des promesses n'est pas garanti; Race condition FastAPI : dans le pattern engine.begin() via Depends(yield), le commit DB a lieu après que la response soit envoyée au client (doc FastAPI explicite). Donc un GET déclenché immédiatement après le POST peut voir l'état pre-commit. La parade propre serait de commit dans le handler avant return, ou de changer le pattern dep. Investigation pas anodine."
## Publique
### Personnes (public)
* [ ] publications: indiquer si premier/dernier auteur
### Publications
* [ ] Filtres supplémentaires possibles: langue; `has_doi` (crossref, datacite, other, none); `corresponding_is_in_perimeter`; `peer_reviewed`? (suppose de posséder la donnée ou de pouvoir la déduire des sources); licence
* [ ] doc_types: répartir en deux niveaux?
* [ ] colonne éditeur; filtres éditeur + revue?
* [ ] définir des groupes de pays (UE, continents) pour la facette "pays des co-auteurs"
* [ ] thèses d'autres établissements liés à nos labos: enlever de la page thèses (ajouter filtre implicite sur "établissement de soutenance" / ou le faire en amont dès le pipeline?)
* [ ] page détails: séparer l'affichage des relations selon le sens (publication parent: afficher dès le bloc titre; publications dépendantes: mettre liens dans la sidebar)
## Détails d'affichage
* [ ] dashboard éditeur/revue: graphiques sur le modèle des dashboards labo/personne
* [ ] ajouter facettes sur dashboards pour générer dynamiquement les graphiques?
* [ ] page revue: tableau publications, pas besoin de colonne revue
* [ ] noms de containers OpenAlex aberrants ("SPIRE - Sciences Po Institutional REpository") => faire quelque chose

# Cas particuliers, bizarreries à élucider
* [ ] 164107: pourquoi type autre?
* [ ] 165068 type "commmentary"; 86931 type "meeting report" => comment prendre en compte ces types (et empêcher openalex d'imposer le type article)
* [ ] 30172 un recueil de proceedings fusionné avec tous ses chapitres

# Trucs pour plus tard, éventuellement
* stats en compte fractionnaire vs compte entier
* collaborations nationales et internationales: identification des structures partenaires?
* audit trail: uniformiser les types d'action qui génèrent un log ou pas + interface pour les consulter
* règles de correction de métadonnées et règles de déduplication de publications: actuellement logées dans le code; possibilité de les stocker en base et de les rendre configurables via l'UI?
* rendre les extracteurs interruptibles avec ctrl+C sous Windows

# Pas nécessaire de le régler, du moment qu'on le documente
* [ ] re-tester le circuit des imports RH => pas urgent, pas d'imports csv à terme en prod
