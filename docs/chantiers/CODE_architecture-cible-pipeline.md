# Réflexion — Architecture cible du pipeline

## Contexte

Le pipeline alimente la base de données. L'objectif est un pipeline clair, lisible, maintenable et conforme aux pratiques courantes du domaine.

### Constats (code au 2026-10-10)

- **19 tables ont deux écrivains, l'API et le pipeline** : `publications`, `persons`, `source_authorships`, `journals`, `addresses`… Les tables `structures`, `perimeters`, `structure_name_forms`, `structure_tutelles` et `config` sont écrites par l'API et le seed seulement.
- **Le code circule dans les deux sens entre API et pipeline.** L'API instancie 5 adaptateurs du pipeline. 14 modules du pipeline appellent des services de l'API.
- **Acquisition et transformation s'entremêlent.** `publishers_journals` interroge Crossref, OpenAlex, le Sudoc et le DOAJ au milieu de la résolution. `oa_status` interroge Unpaywall en fin de run.
- **Plusieurs phases lisent des données du run précédent.**
- **72 des 105 modules de `application/pipeline/` passent par des ports.** Pour une suite de transformations de tables en tables, cette séparation entre logique et SQL est artificielle : la logique est souvent le SQL.
- **Les décisions humaines disparaissent avec les entités auxquelles elles se rattachent.** En base locale, sur 761 rejets journalisés, 53 ont disparu avec leur publication et environ 440 avec leur personne.

## Démarche

Six questions, dans cet ordre. Chacune s'appuie sur les précédentes. La mise en pratique et les fiches chantier viennent après.

### 1. Identités stables

Quelles entités gardent leur identifiant d'un run à l'autre, et que devient l'identifiant d'une entité qui disparaît ?

**Constat**
- `publications.id` : la réconciliation reconduit la publication qui a le DOI, sinon celle de la plus petite notice.
- `persons.id` : stable tant que les signatures gardent leur `person_id` ; la phase `persons` supprime les personnes devenues vides.
- Un identifiant absorbé par une fusion disparaît.

**Décisions**
- **La clé interne d'une entité n'a pas à être pérenne.** On accède aux données par l'interface ; un utilisateur de l'API filtre sur des critères, pas sur une clé interne.
- **Pas de redirection sans cas d'usage qui en prouve l'utilité.** Une entité qui disparaît emporte ses identifiants.
- **Une décision humaine s'appuie sur des identifiants naturels quand ils existent** : DOI, ROR, ISSN, membre Crossref, ORCID, IdRef. Sinon, la question 2 fixe son rattachement.
- **Personnes : pas d'identifiant naturel général.** À la fusion de deux personnes, leurs décisions sont reportées sur la personne conservée.
- **Un regroupement recalculé en entier peut renuméroter ses entités.**

### 2. Décisions humaines et données de référence

Comment une intervention humaine survit-elle aux recalculs du pipeline ? Traité par le chantier [Décisions humaines durables](archived/2026-10-11_DATA_decisions-humaines-durables.md).

**Acquis**
- Recensement des décisions, de leur rattachement et des chemins qui les détruisent.
- Une fusion de personnes applique les rejets de la personne absorbée et de la personne absorbante.

**Hypothèses**
- Une décision vise un lien ou un champ, jamais une liste entière.
- Chaque rattachement enregistre son origine : règle, décision humaine, modèle.

**Ouvert**
- Classement des interventions par nature : valeur d'un champ, lien, création d'entité, référentiel tenu à la main.
- Mécanisme pour chacune : source prioritaire, contrainte imposée à la résolution, ou verrouillage.
- Identifiant auquel rattacher une décision pour qu'elle survive aux fusions et aux dissolutions.
- Cycle de vie des entités : fusion, suppression des entités vides, sort des décisions qui s'y rattachent.
- Fusions automatiques (revues, publications) : veto humain après coup, ou fusion proposée puis validée ?

### 3. Nature de chaque table

Chaque table relève d'une catégorie :

- **brut** : ce que les sources ont renvoyé (`staging`) ;
- **décision** : ce qu'un humain a tranché (rejets, confirmations, non-doublons, statuts) ;
- **référentiel tenu à la main** : structures, périmètres, configuration, formes de nom des structures ;
- **état conservé d'un run à l'autre** : ce que le pipeline ne sait pas recalculer, comme les identifiants stables ou les échecs de recherche (`failed_lookups`) ;
- **dérivé recalculable** : tout le reste ;
- **diffusion** : ce que lisent les consommateurs en lecture seule, construit à partir du dérivé et des référentiels. L'API publique d'abord ; d'autres consommateurs ensuite, si la trajectoire se confirme.

**Hypothèse : un schéma PostgreSQL par catégorie.** Le schéma rend visible, à la lecture de la base, la nature d'une table. Les droits (`GRANT`) rendent vérifiable qui écrit quoi : le pipeline écrit le brut, l'état, le dérivé et la diffusion ; l'API écrit les décisions et les référentiels ; les consommateurs en lecture seule lisent la diffusion seulement. Une table dérivée peut alors changer sans toucher les consommateurs.

**Contrat de la résolution** : en entrée, les notices et les signatures sources, plus les décisions ; en sortie, une table de correspondance entre chaque notice ou signature et son entité. Le contrat tient quel que soit l'algorithme.

Une forme possible, celle des modèles par paires (dnet-dedup, Splink). Chaque étape lit en base ce que la précédente a écrit :

1. **paires candidates** : les paires de notices ou de signatures qui concordent, avec leur origine ou leur score ;
2. **décisions** : les confirmations ajoutent des paires, les rejets et les non-doublons en retirent ;
3. **groupes** : composantes connexes sur les paires retenues ;
4. **identifiant** : chaque groupe reçoit un identifiant ;
5. **entité** : construite à partir des membres du groupe.

La table des paires est du dérivé recalculable. C'est la sortie d'un modèle probabiliste comme de règles déterministes.

**Acquis**
- L'inventaire des lectures et écritures de chaque table : [CODE_pipeline-dag_inventaire.md](CODE_pipeline-dag_inventaire.md).

**Ouvert**
- Le classement de chaque table.
- Les tables mixtes, qu'écrivent à la fois le pipeline et l'API : les scinder, ou leur attribuer une catégorie dominante ?
- Forme par paires : les composantes connexes ne respectent pas les interdictions. La réconciliation des publications sépare toujours deux DOI différents, ce que la transitivité des paires ne garantit pas. L'étape 3 devient alors un regroupement sous contraintes, et l'étape 2 reçoit aussi les interdictions issues des règles.
- Forme par paires : les décisions sur les personnes visent des entités (un rejet vise un couple publication-personne, un non-doublon deux personnes), non des paires de signatures. Leur traduction en contraintes sur les signatures dépend de la question 2.
- La cascade des personnes rattache une signature à une personne existante, sans comparer les signatures entre elles : forme de ReCiter, autre que la forme par paires.

### 4. Graphe

Le graphe est un contrat vérifié par les tests. Ses nœuds et son critère sont posés dans le chantier [Graphe de dépendances du pipeline](CODE_pipeline-dag.md).

**Acquis**
- Les nœuds, et un verdict sur chaque sortie partagée par plusieurs nœuds.
- Les lectures du run précédent, recensées par l'inventaire.

**Ouvert**
- Chaque lecture du run précédent : boucle voulue, ou accident d'ordre ? Hypothèse : une boucle unique et déclarée, d'acquisition ciblée (`resolve_ra`, `fetch_missing`) d'après le résultat de la résolution.
- Recalcul complet ou incrémental, nœud par nœud, d'après la nature de ses tables. Dépend de la durée d'un recalcul complet. Le pipeline de Stanford est passé du recalcul complet à l'incrémental.
- `publications.reconcile`, aujourd'hui un seul nœud : le scinder selon les étapes de la forme par paires, si elle est retenue.
- Place des appels réseau. Hypothèse : acquisition séparée de la transformation, qui se rejoue alors sur une copie de la base.
- Phases réduites à des groupes d'affichage.

### 5. Organisation du code

**Hypothèses**
- Un paquet de premier niveau `pipeline/`, hors des couches hexagonales. Les règles pures restent dans `domain/`.
- Acquisition : un module par source, qui regroupe tous ses nœuds (moissonnage, recherche des documents manquants, rafraîchissement).
- Transformation : un module par nœud, qui contient son SQL.
- Fusion des métadonnées d'une publication : un fichier par champ consolidé, qui liste ses règles par ordre de priorité des sources.
- Le graphe dans un seul fichier, lisible de haut en bas : chaque nœud y est un appel de fonction.
- Tests en miroir de l'arborescence, avec un jeu de notices d'exemple.
- Règles d'import vérifiées par `import-linter` : `pipeline/` importe `domain/` et les modules techniques neutres (connexion, réglages, journalisation), jamais `application/` ; seul un adaptateur de l'API importe l'interface publique du pipeline.
- Effet immédiat d'une décision : l'API appelle un recalcul ciblé exposé par le pipeline, par un port de `application/ports/`.

**Ouvert**
- Quelles décisions exigent un effet immédiat ? Les autres attendent le run suivant.
- Point d'entrée en ligne de commande : `interfaces/cli/` ou `pipeline/` ?
- SQL dans le module Python, ou en fichiers `.sql` nommés par ce qu'ils font ?
- Priorités entre sources et seuils : dans le domaine, testés avec le code (`SOURCE_PRIORITY`), ou dans un fichier de configuration modifiable sans toucher au code ?

### 6. Épreuve sur papier

La cible est confrontée à des situations concrètes. Chaque élément de la cible cite les pièges de l'inventaire qu'il supprime. Ce qui ne passe pas l'épreuve sort de la cible.

Situations :
- fusion de revues, faite par l'admin ou par le pipeline ;
- fusion de personnes, dont l'une est rejetée sur une publication de l'autre ;
- DOI d'une notice corrigé entre deux runs ;
- signature rejetée par l'admin, seule signature du périmètre de sa publication ;
- notice OpenAlex de plus de 100 auteurs rapatriée par DOI ;
- panne d'une API au milieu d'un run ;
- nouvelle source ;
- règle de correction modifiée ;
- deux publications regroupées à tort par un DOI commun ;
- cascade des personnes remplacée par Splink.

## Hors de la cible, à décider plus tard

- Algorithme de résolution des personnes : cascade de règles ou modèle probabiliste, et avec lui le recalcul complet de la résolution. Le contrat de la résolution (question 3) doit tenir dans les deux cas.
  - Pour le probabiliste : Splink plutôt qu'un modèle maison.
  - Splink additionne les comparaisons comme si elles étaient indépendantes : revue, sujet et structure, corrélés, sont à regrouper en une seule comparaison.
  - Splink ne prévoit pas les liens imposés ou interdits : les décisions s'appliquent à l'étape 2 du contrat.
- Conception de la résolution, deux idées de ReCiter : enregistrer ce qui a concordé et pas seulement la règle ; réutiliser les confirmations et les rejets d'une personne comme indices pour ses autres signatures.
- Outillage : orchestrateur par *assets* (Dagster), dbt, publication en bloc après contrôle (*Write-Audit-Publish*).

## Mise en pratique

Après les six questions. La refonte avance nœud par nœud. Elle commence par un test de non-régression : sur une copie figée de la base, on compare les tables produites avant et après chaque modification.

## Documents liés

- [benchmark-pipelines.md](benchmark-pipelines.md) : idées relevées dans le code d'autres pipelines de publications (Stanford, CRISalid, ReCiter, OpenAIRE), avec les liens vers les fichiers.
