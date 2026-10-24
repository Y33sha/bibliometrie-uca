# Personnes — cycle de vie

*À jour le 2026-10-12.*

Une personne est un chercheur unifié à travers les sources : plusieurs contributions sources, venues de HAL, d'OpenAlex ou du Web of Science sous des graphies différentes, désignent la même personne. Contrairement aux [structures](structures.md), qui sont un référentiel saisi à la main, les personnes sont **construites par le pipeline** — la phase `persons` rattache chaque contribution source à une personne et en crée au besoin — **puis corrigées à la main** : fusion, réattribution d'identifiant, rejet, détachement. Le pipeline et l'interface d'administration écrivent donc tous deux.

`domain/persons/` contient les règles pures : la décision de résolution (`decide_person_match`), la comparaison des noms (`names_compatible`), et des types dédiés qui valident et normalisent chaque identifiant avant écriture.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `persons` | La personne unifiée | `last_name` / `first_name` et leurs formes normalisées, `rejected` |
| `person_identifiers` | Attribution d'un identifiant externe à une personne | `person_id`, `id_type`, `id_value`, `source` (`manual` ou `auto`), `status`, unicité `(id_type, id_value)` |
| `person_name_forms` | Formes de nom sous lesquelles une personne apparaît | clé `(name_form, person_id)`, `sources`, `status` |
| `hr_records` | Fiche annuaire issue du système d'information | `person_id` unique, suppression refusée tant qu'elle existe, `email`, fonction, département, structure, dates |
| `distinct_persons` | Paires déclarées comme deux personnes différentes | `(person_id_a, person_id_b)`, avec `a < b` |
| `rejected_contributions` | Paires publication–personne écartées durablement | `(publication_id, person_id)` |

`source_contributions.person_id` rattache une contribution source à une personne. `resolution_mode` retient par quel moyen la résolution a été faite : identifiant, nom, ou report d'une autre source.

## Écriture par le pipeline

`pipeline/transformation/persons/persons.py` exécute six étapes. Les quatre premières partagent une transaction. La régénération des formes de nom et la purge ont chacune la leur. La phase lit les contributions sources du périmètre non encore rattachées, avec leurs identifiants, leur nom normalisé, leurs rôles et leur position dans la publication, ainsi que des index chargés en mémoire au début du traitement. Elle écrit le rattachement des contributions sources, crée des personnes, inscrit les identifiants rencontrés et régénère les formes de nom.

1. **Appliquer les décisions humaines.** Les rattachements épinglés à la main sont reposés en premier ; les étapes suivantes ne les défont pas.
2. **Arbitrer les identifiants disputés.** Un ORCID, un IdRef ou un identifiant de compte HAL peut être attribué à une personne alors que des contributions sources où il figure sont rattachées à une autre. Le nom d'auteur majoritaire, parmi toutes les contributions sources où figure cette valeur, tranche. Une attribution confirmée à la main prévaut. Après un transfert, les contributions sources qui tenaient leur rattachement de cet identifiant repassent à nul et sont résolues à nouveau.
3. **Rapprocher.** `decide_person_match` tranche par fiabilité décroissante : ORCID, identifiant de compte HAL, IdRef, nom unique, report depuis une autre source, et création en dernier recours. La cascade fait deux passes sur les mêmes index : la première ne fait que rapprocher, la création est repoussée à la seconde. Une contribution source à rôles de jury de thèse seuls (direction, rapport, jury, présidence), venue de theses.fr ou de ScanR, n'autorise aucune création.
4. **Détacher ce qui a perdu son appui.** Un rattachement obtenu par report depuis une autre source, dont l'attache d'origine a disparu, repasse à nul.
5. **Régénérer les formes de nom.** Les formes calculées depuis l'état civil de la personne rejoignent celles observées dans les membres de ses groupes de contributions sources ; seules les différences sont écrites. Une forme calculée naît confirmée, une forme observée naît en attente, et les décisions humaines déjà prises sont conservées.
6. **Purger.** Les groupes rattachés par le nom dont une forme désigne deux personnes ou plus perdent leur personne. Les personnes sans contribution du périmètre sont supprimées, sauf celles qui ont une fiche annuaire ou une décision humaine.

Les identifiants rencontrés sont inscrits par un point unique, toujours en attente de confirmation et marqués comme automatiques. Un conflit y est consigné sans bloquer, et laissé à l'arbitrage de l'exécution suivante.

Ce qu'une exécution inscrit devient ce que la suivante lit, si bien que la convergence demande plusieurs exécutions. Trois remises à nul se décident d'après l'état lu au début de la phase : la contribution source dont l'identifiant a été transféré, le rattachement par nom devenu ambigu, et le report entre sources recalculé. Un homonyme apparu à une exécution se résout donc à la suivante ; deux passages suffisent en pratique.

## Écriture par l'API — édition manuelle

Routeur `interfaces/api/routers/persons.py`, commandes dans `application/services/persons/commands.py`, adaptateur `PgPersonRepository`. Une commande vaut une transaction.

**Fusionner deux personnes** (`POST /api/persons/{id}/merge`). `merge_into` transfère six tables — contributions sources, contributions, rejets, identifiants, fiche annuaire si la cible n'en a pas, et formes de nom en réunissant leurs provenances — puis supprime la personne absorbée. Sur une publication où la personne fusionnée est à la fois contributrice et rejetée, le rejet l'emporte : ses contributions sources y sont détachées et la contribution supprimée. La fusion est refusée si les deux ont chacune une fiche annuaire distincte.

**Gérer les identifiants.** Ajout manuel, limité aux types publics ; suppression ; confirmation, rejet ou retour en attente. Ajouter à une personne un identifiant rejeté chez une autre le lui réattribue, en attente ; un identifiant en attente ou confirmé chez une autre personne est refusé.

**Agir sur la personne.** Rejet et retour en arrière, avec recalcul de l'appartenance des publications au périmètre ; renommage, qui régénère les formes calculées.

**Trancher une forme de nom.** La confirmer ou la rejeter ; un rejet détache aussi les contributions sources de cette forme et supprime les contributions devenues orphelines.

**Détacher des contributions** (`POST /api/persons/{id}/detach-contributions`). Inscrit le rejet durable, détache les contributions sources, supprime la ligne consolidée et nettoie les formes restées sans emploi.

**Déclarer deux personnes distinctes** inscrit la paire dans `distinct_persons`, ce qui l'écarte des files de doublons.

**Importer un ORCID authentifié** pose un statut que rien ne peut dégrader ensuite. L'import s'annonce par un réglage de session borné à sa transaction, seul contexte que le déclencheur Postgres accepte.

Aucun point d'entrée n'écrit `hr_records` : la fiche annuaire vient d'un import, et la fusion se contente de la transférer.

## Lecture par le pipeline

La cascade lit tout en bloc, par `PersonsMatchingQueries` (`pipeline/transformation/persons/matching.py`) :

- les correspondances identifiant → personne pour IdRef, ORCID et compte HAL, avec le nom normalisé joint pour corroborer ;
- les correspondances forme de nom → personnes, et les décisions humaines sur les couples forme–personne ;
- les personnes écartées d'une publication ;
- l'index des rattachements déjà posés par publication et position, sur lequel s'appuie le report d'une source à l'autre.

## Lecture par l'API

Port `PersonsQueries`, adaptateurs dans `infrastructure/read_models/persons/`.

| Usage | Ce qui est servi |
|---|---|
| Fiche personne | Profil, thèses, adresses, tableau de bord et sujets, en croisant les personnes, la fiche annuaire, les identifiants, les contributions sources, les contributions et les publications |
| Annuaire, listes, recherche, facettes, statistiques | Listes publiques et d'administration, filtrables par laboratoire |
| Files de doublons | Doublons par nom, conflits d'identifiant, contributions sources détachables, formes de nom ambiguës, candidates au partage d'une forme |

Toutes les files de doublons écartent les paires déclarées distinctes ; celle des doublons par nom écarte en outre les paires dont les deux personnes ont une fiche annuaire.
