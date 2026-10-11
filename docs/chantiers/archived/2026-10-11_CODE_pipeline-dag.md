# Chantier — Graphe de dépendances du pipeline

## Contexte

Le pipeline enchaîne 16 phases dans un ordre fixe, déclaré dans `application/pipeline/phase_order.py`. Chaque phase regroupe des sous-étapes. Le découpage en phases sert la lecture. Il impose aussi l'ordre d'exécution : une sous-étape attend la fin de toute la phase précédente, même quand elle dépend seulement d'une de ses tables. Plusieurs sous-étapes d'une même phase sont indépendantes les unes des autres.

Les orchestrateurs à graphe de dépendances (Airflow, Dagster, dbt) distinguent deux notions :

- les nœuds, fins, dont l'ordre d'exécution découle des seules dépendances réelles ;
- les groupes, qui servent à afficher, documenter et sélectionner, sans imposer d'ordre.

Sous-étapes et nœuds diffèrent parfois. Une sous-étape peut produire plusieurs sorties sans lien entre elles. Plusieurs sous-étapes peuvent aussi former une seule unité indissociable.

## Décisions

- **Les nœuds se déterminent à partir du code.** L'inventaire part de la granularité la plus fine (fonctions et requêtes qui écrivent), puis regroupe.
- **Un nœud est la plus petite unité de calcul telle que :**
  1. ses sorties ne dépendent pas de l'ordre d'exécution. S'il partage une sortie avec d'autres nœuds, l'ordre de leurs écritures ne change pas le résultat. À défaut, le graphe fixe cet ordre et chaque lecteur dépend du dernier écrivain ;
  2. il lit ses entrées en base : il ne reçoit rien en mémoire d'un autre nœud ;
  3. ses sorties sont justes à sa fin : deux sorties qui ne sont justes qu'ensemble appartiennent au même nœud.
- **Le graphe est un contrat vérifié par les tests**, non une documentation.
- **`staging` garde ses écrivains.** Les canaux d'acquisition y écrivent la dernière observation d'un document, dans un ordre indifférent ; `normalize` consomme la table comme une file. `fetch_truncated` reste une phase : compléter les auteurs pendant le moissonnage coûte environ 5 minutes par année moissonnée (mesure sur 2021, `audit_openalex_inline_truncation`). OpenAlex n'expose pas d'indicateur de troncature : le signal reste le compte de 100 auteurs.
- **Colonnes de `source_publications` : sans changement.** La normalisation écrit la valeur de la source, la correction la remplace et range l'original dans `raw_metadata`. Le graphe fixe l'ordre normalisation → correction ; relancer la normalisation relance ce qui en dépend.
- **`publications.oa_status` et `publications.countries` : sans changement.** Pour le statut, la réconciliation calcule une valeur sauf si Unpaywall en a établi une, qui fait autorité. Pour les pays, réconciliation et phase `countries` appliquent la même formule. Dans les deux cas, l'ordre ne change pas le résultat.
- **Le regroupement produit deux listes** : les nœuds du code actuel, et les refactorisations qui permettraient des nœuds plus fins.

## Phasage

### Phase 1 — Inventaire

Inventaire en annexe : [inventaire](2026-10-11_CODE_pipeline-dag_inventaire.md).

- [x] Recenser, pour chaque phase, ses sous-étapes au grain le plus fin.
- [x] Pour chacune, établir :
  - les tables et colonnes lues ;
  - les tables et colonnes écrites, et le mode d'écriture (insertion, mise à jour, suppression, remplacement complet) ;
  - les appels réseau : API interrogée, quota, comportement en cas d'échec ;
  - les lectures de données que la même sous-étape ou une étape plus loin dans l'ordre écrit, donc des données du run précédent ;
  - la sélection du travail : tout le stock, ou un sous-ensemble (marqueurs `*_dirty`, ancienneté, absence d'une valeur) ;
  - les décisions humaines lues ou préservées (arbitrages, statuts confirmés ou rejetés) ;
  - les conditions de déclenchement : mode du run, configuration, délai depuis le dernier passage ;
  - les appels aux services de l'application web ;
  - l'idempotence : deux exécutions de suite donnent-elles le même résultat ?

### Phase 2 — Nœuds

- [x] Fixer le critère qui délimite un nœud.
- [x] Regrouper ou scinder les sous-étapes selon ce critère : section « Nœuds » de l'annexe.

### Phase 3 — Graphe

Déclaration des nœuds et des dépendances : `application/pipeline/graph.py`.

- [x] Déclarer chaque nœud avec les données qu'il lit et écrit, ses appels réseau et ses lectures du run précédent.
- [x] Déduire les dépendances des lectures et écritures ; vérifier qu'aucun nœud ne lit une donnée écrite après lui sans la déclarer lue au run précédent.
- [x] Confronter le graphe au découpage en phases : dépendances fausses, regroupements par domaine possibles.

## Confrontation aux phases

D'après `application/pipeline/graph.py`. Les lectures du run précédent entre phases se rangent en quatre catégories.

**Boucle d'acquisition ciblée, voulue et gardée.** `fetch_missing` lit `candidate_dois` : les DOI des publications du périmètre, établi par `authorships` au run précédent. Les documents d'une publication nouvelle sont cherchés au run suivant ; au premier run sur base vide, la recherche ne fait rien. `resolve_ra`, placé après `affiliations`, résout les préfixes de tous les DOI connus dans le run ; `fetch_missing` n'interroge que les DOI dont le préfixe est résolu.

Le délai coûte peu : environ 70 publications sur 62 000 à la mesure de 2026-07. Les remèdes coûtent plus :
- ajouter les DOI moissonnés dans le run ferait chercher pour rien les DOI des documents moissonnés hors périmètre : 28 243 sur 140 982 en base locale, et 20 % de chaque moisson ;
- juger le périmètre par notice après `affiliations` imposerait de normaliser et de résoudre les affiliations une seconde fois à chaque run.

**Boucles d'apprentissage, voulues.** Les espaces de noms DOI s'apprennent des notices dont la correction a fixé la revue au run précédent. Le typage des actes lit les types bruts rangés par la correction.

**Retards sans conséquence.** `affiliations` marque à réconcilier les notices sans publication d'après le rattachement que la réconciliation précédente a laissé : c'est l'état qu'il doit lire. La fusion des revues choisit sa cible d'après le nombre de publications du run précédent. Les référentiels vides sont supprimés dans `authorships`, après les dernières suppressions de publications : dans le run qui les vide.

**Lectures déclarées par colonne.** Normalisation, correction, recherche des documents manquants et relations déclarent les colonnes qu'elles lisent. Aucun autre retard n'apparaît : les lectures restantes relèvent des verdicts sur les sorties partagées (statut open access, pays, référentiels créés par la normalisation).

**Ordres arbitraires.** `affiliations` et `publishers_journals` ne dépendent pas l'une de l'autre, ni `relations`, `subjects`, `countries` et `oa_status` entre elles.

## Reporté

- Vérification des déclarations contre le code : phase 3 du chantier [Jeu de données commun aux tests du pipeline](../CODE_jeu-de-donnees-commun.md).

## Questions ouvertes
