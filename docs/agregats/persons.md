# Personnes — cycle de vie

*À jour le 2026-09-04.*

Une personne est un chercheur unifié à travers les sources : plusieurs signatures, venues de HAL, d'OpenAlex ou du Web of Science sous des graphies différentes, désignent la même personne. Contrairement aux [structures](structures.md), qui sont un référentiel saisi à la main, les personnes sont **construites par le pipeline** — la phase `persons` rattache chaque signature à une personne et en crée au besoin — **puis corrigées par la curation** : fusion, réattribution d'identifiant, rejet, détachement. Le pipeline et l'interface d'administration écrivent donc tous deux.

`domain/persons/` porte les règles pures : la décision de rapprochement (`decide_person_match`), la comparaison des noms (`names_compatible`, `same_person_name`), et des types dédiés qui valident et normalisent chaque identifiant avant écriture.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `persons` | La personne unifiée | `last_name` / `first_name` et leurs formes normalisées, `rejected` |
| `person_identifiers` | Attribution d'un identifiant externe à une personne | `person_id`, `id_type`, `id_value`, `source` (`manual` ou `auto`), `status`, unicité `(id_type, id_value)` |
| `person_name_forms` | Formes de nom sous lesquelles une personne apparaît | clé `(name_form, person_id)`, `sources`, `status` |
| `persons_rh` | Fiche annuaire issue du système d'information | `person_id` unique, suppression refusée tant qu'elle existe, `email`, fonction, département, structure, dates |
| `distinct_persons` | Paires déclarées comme deux personnes différentes | `(person_id_a, person_id_b)`, avec `a < b` |
| `rejected_authorships` | Paires publication–personne écartées durablement | `(publication_id, person_id)` |

Le rattachement d'une signature à une personne est porté par `source_authorships.person_id`, accompagné de `resolution_mode`, qui retient par quel moyen le rapprochement a été fait : identifiant, nom, ou report d'une autre source.

## Écriture par le pipeline

`application/pipeline/persons/phase.py` exécute six étapes dans une transaction unique. La phase lit les signatures du périmètre non encore rattachées, avec leurs identifiants, leur nom normalisé, leurs rôles et leur position dans la publication, ainsi que des index chargés en mémoire au début du traitement. Elle écrit le rattachement des signatures, crée des personnes, inscrit les identifiants rencontrés et régénère les formes de nom.

1. **Appliquer les décisions humaines.** Les rattachements épinglés par la curation sont reposés en premier ; les étapes suivantes ne les défont pas.
2. **Arbitrer les identifiants disputés.** Quand une personne porte un identifiant sans en être la titulaire attribuée, le nom majoritaire — pondéré par le nombre de signatures — emporte le transfert. Seules les attributions non encore confirmées sont transférables. Les signatures qui tenaient leur rattachement de cet identifiant repassent à nul, pour être résolues à nouveau.
3. **Rapprocher.** `decide_person_match` tranche par fiabilité décroissante : ORCID, identifiant de compte HAL, IdRef, nom unique, report depuis une autre source, et création en dernier recours. La cascade fait deux passes sur les mêmes index : la première ne fait que rapprocher, la création est repoussée à la seconde. Une signature qui appellerait une création peut ainsi rejoindre une personne rattachée plus loin dans la même passe, au lieu de créer un doublon selon l'ordre de traitement. Les rôles non-auteurs des thèses — jury, rapporteurs — n'autorisent aucune création.
4. **Détacher ce qui a perdu son appui.** Un rattachement obtenu par report depuis une autre source, dont l'attache d'origine a disparu, repasse à nul.
5. **Régénérer les formes de nom.** Les formes canoniques calculées depuis l'état civil de la personne rejoignent les formes bibliographiques observées dans ses signatures ; seules les différences sont écrites. Une forme canonique naît confirmée, une forme observée naît en attente, et les décisions humaines déjà prises sont conservées.
6. **Purger.** Les rattachements par nom dont la forme désigne maintenant deux personnes ou plus sont détachés, puis les personnes devenues vides sont supprimées — sauf celles qui portent une fiche annuaire.

Les identifiants rencontrés sont inscrits par un point unique, toujours en attente de confirmation et marqués comme automatiques. Un conflit y est consigné sans bloquer, et laissé à l'arbitrage de l'exécution suivante. Ce qu'une exécution inscrit devient ce que la suivante lit : c'est ce qui porte la convergence.

## Écriture par l'API — curation

Routeur `interfaces/api/routers/persons.py`, commandes dans `application/services/persons/commands.py`, adaptateur `PgPersonRepository`. Une commande vaut une transaction.

**Fusionner deux personnes** (`POST /api/persons/{id}/merge`). `merge_into` transfère six tables — signatures, authorships, rejets, identifiants, fiche annuaire si la cible n'en a pas, et formes de nom en réunissant leurs provenances — puis supprime la personne absorbée. La fusion est refusée si les deux portent chacune une fiche annuaire distincte.

**Gérer les identifiants.** Ajout manuel, limité aux types publics ; suppression ; confirmation ou rejet ; réattribution, qui ramène l'identifiant en attente.

**Agir sur la personne.** Rejet et retour en arrière, avec recalcul de l'appartenance des publications au périmètre ; renommage, qui régénère les formes canoniques.

**Trancher une forme de nom.** La confirmer ou la rejeter ; un rejet détache aussi les signatures qui la portent et supprime les authorships devenues orphelines.

**Détacher des authorships** (`POST /api/persons/{id}/detach-authorships`). Inscrit le rejet durable, détache les signatures, supprime la ligne consolidée et nettoie les formes restées sans emploi.

**Déclarer deux personnes distinctes** inscrit la paire dans `distinct_persons`, ce qui l'écarte des files de doublons.

**Importer un ORCID authentifié** pose un statut que rien ne peut dégrader ensuite. L'import s'annonce par un réglage de session borné à sa transaction, seul contexte que le déclencheur Postgres accepte.

Aucun point d'entrée n'écrit `persons_rh` : la fiche annuaire vient d'un import, et la fusion se contente de la transférer.

## Lecture par le pipeline

La cascade lit tout en bloc, par `PersonsMatchingQueries` (`infrastructure/pipeline/persons/matching.py`) : les correspondances identifiant vers personne pour IdRef, ORCID et compte HAL, avec le nom normalisé joint pour corroborer ; les correspondances forme de nom vers personnes ; les décisions humaines sur les couples forme–personne ; les personnes écartées d'une publication ; et l'index des rattachements déjà posés par publication et position, sur lequel s'appuie le report d'une source à l'autre.

## Lecture par l'API

Port `PersonsQueries`, adaptateurs dans `infrastructure/read_models/persons/`.

| Usage | Ce qui est servi |
|---|---|
| Fiche personne | Profil, thèses, adresses, tableau de bord et sujets, en croisant les personnes, la fiche annuaire, les identifiants, les signatures, les authorships et les publications |
| Annuaire, listes, recherche, facettes, statistiques | Listes publiques et d'administration, filtrables par laboratoire |
| Files de curation des doublons | Doublons par nom, conflits d'identifiant, signatures détachables, formes de nom ambiguës, candidates au partage d'une forme |

Toutes les files de doublons écartent les paires déclarées distinctes ; celle des doublons par nom écarte en outre les paires dont les deux personnes portent une fiche annuaire.

## Points d'attention

**La convergence demande plusieurs exécutions.** L'indépendance à l'ordre de traitement ne vient pas de la transaction, mais de trois remises à nul décidées d'après l'état lu au début de la phase : les signatures dont l'identifiant a été transféré, les rattachements par nom devenus ambigus, et le recalcul complet des reports entre sources. Un homonyme ou un transfert apparu à une exécution se résout à la suivante ; deux passages suffisent en pratique.

**La phase écrit dans des tables voisines.** Poser le rattachement relève des personnes, mais la phase et la fusion touchent aussi les signatures, les authorships et les rejets, pour que l'opération reste atomique.

**La fiche annuaire protège une donnée sensible.** Une personne qui en porte une ne peut pas être supprimée en silence, et la fusion refuse d'en absorber deux distinctes. Le même garde-fou est répété du côté de la file de doublons, pour éviter de proposer une fusion que le service refuserait.

**Le statut d'ORCID authentifié ne se dégrade pas.** Il est réservé au chercheur qui authentifie lui-même son identifiant, ne peut être posé que par l'import dédié, et un déclencheur Postgres interdit toute autre transition.

## Invariants métier

**Identités.** `person_identifiers` est unique par `(id_type, id_value)` ; `person_name_forms` par `(name_form, person_id)` ; `distinct_persons` est ordonnée pour qu'une paire ne s'inscrive qu'une fois ; `persons_rh` est en relation de un à un.

**Fusion.** Refusée quand les deux personnes portent chacune une fiche annuaire distincte.

**Un identifiant partagé signale une corruption de la source.** Un identifiant porté par deux positions d'auteur ou plus d'un même enregistrement source est suffixé `_dubious` : il est conservé, la marque est réversible, mais il ne sert plus au rapprochement.

**L'ORCID n'est un signal que là où l'auteur l'a déposé.** Il ne sert au rapprochement que depuis Crossref, OpenAlex et HAL. Les ORCID venus du Web of Science ou de ScanR sont enregistrés sans être utilisés pour rapprocher.

**Rejet durable.** Une paire publication–personne écartée n'est jamais recréée par le rapprochement, y compris quand ce retrait lève l'ambiguïté d'une forme partagée.

**Identifiants normalisés avant écriture.** ORCID au format à seize chiffres groupés, IdRef à neuf caractères, IdHAL en abrégé littéral, identifiant de compte HAL entier positif : chacun est validé et normalisé par son type dédié.
