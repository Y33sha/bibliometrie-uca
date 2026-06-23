# Chantier — Gestion et dédoublonnage assistés de la base personnes

Commencé le 2026-06-22

## Contexte

La base personnes a dépassé la taille gérable à la main : `admin/persons` est devenue ingérable. Elle contient ~1,6k personnes avec notice RH (`persons_rh`, les enseignants-chercheurs UCA de l'année courante) et ~15k autres, mêlant des entrées légitimes et des parasites sans moyen simple de les trier :

- personnels d'établissements co-tutelles (CNRS, Inserm, INRAE) co-signant sous un labo UCA — légitime ;
- quelques personnels non enseignants-chercheurs — légitime ;
- enseignants-chercheurs partis (retraite, mutation) et anciens doctorants — légitime ;
- chercheurs hébergés temporairement par le passé, ayant co-signé quelques publications UCA ;
- fausses affiliations dues à des erreurs de parsing : signatures concaténées, appliquées en bloc à tous les co-auteurs d'une publication ;
- doublons non corrigés, à fusionner.

Ce volume est impossible à dédupliquer et corriger efficacement à la main. Il faut une aide automatisée : prévention des nouvelles contaminations, correction des erreurs nettes, et suggestions outillées pour les cas qui restent du ressort humain.

Ce chantier prolonge [DATA_identifiants-partages-dubious](archived/2026-06-22_DATA_identifiants-partages-dubious.md), qui a traité la corruption **dense** (un identifiant recopié sur toutes les positions d'auteur d'un même enregistrement source, neutralisé au normalize par le suffixe `_dubious`). Restent ici la corruption **éparse** (un identifiant mal placé, un seul porteur par publication, réparti sur des publications distinctes) et, plus largement, l'outillage de gestion et de dédoublonnage à l'échelle.

## Deux faces : prévenir la contamination, outiller le dédoublonnage

### Prévention — empêcher les identifiants source erronés de contaminer le matching

Trois leviers, librement re-priorisables selon praticité et impact mesuré :

1. **Corroboration par le nom au matching par identifiant.** Un match par ORCID / idref / hal qui pointe une personne dont le nom est incompatible avec la signature est rejeté. Couvre la corruption éparse (« adrien gosselin pali » portant l'ORCID d'« Azomahou ») que le garde par-publication ne voit pas. Levier le plus chirurgical et le moins coûteux (domaine pur, aucune I/O). Deux points d'implémentation établis par l'audit : (a) `decide_match_by_identifier` ne reçoit aujourd'hui que `{id_value: person_id}` — il faut enrichir les maps prefetchées avec le nom de la personne cible ; (b) la comparaison doit se faire **par ensemble de tokens** (à la manière de `_tokens_match` de l'admin, indépendant de l'ordre et tolérant aux initiales), pas par `names_compatible` positionnel : ce dernier rejette à tort « P.M. Llorca » contre « Pierre-Michel Llorca » et les noms de famille multi-mots tronqués par le parser (« Moutou Pitti » réduit à « Pitti »). L'abstention sur signature sans prénom reste utile mais marginale (une poignée de cas dans l'audit) ; le déterminant réel de la précision est la comparaison par tokens.
2. **Restreindre le matching aux identifiants `confirmed`** — option de configuration, `false` par défaut. Les identifiants `pending` (ajoutés automatiquement par le pipeline, non vérifiés) restent no-op tant que non confirmés. Sur une base vide sans identifiants curés, c'est un changement de comportement trop radical (les personnes découvertes par le pipeline n'ont que des `pending` et deviennent non-matchables par identifiant) ; sur une base déjà fournie et curée à la main, c'est une option conservatrice raisonnable. D'où le défaut `false` et l'activation décidée par l'utilisatrice.
3. **Vérification externe via l'API ORCID** — levier potentiellement en phase finale. Un appel par identifiant (pas par signature) récupère le nom canonique associé à l'ORCID — et, si exposés, l'affiliation et le suffixe de l'adresse mail. Confronté au nom de la personne ciblée, c'est un signal de confirmation ou de rejet du couple **identifiant ↔ personne** (pas du lien personne ↔ signature), qui alimente potentiellement le flux de confirmation du levier 2. Pas une garantie absolue (certains profils ne renseignent que le nom ou le prénom, ou ont changé de nom), mais un signal de plus, renforcé si l'affiliation ou le domaine de l'adresse mail corrobore le périmètre UCA. Extensible aux autres référentiels à API (idref).

### Dédoublonnage assisté — deux machineries distinctes

La classification homonymie/doublon/erreur se résout en **deux mécaniques de natures différentes** :

- **Signaux de paire** (deux personnes à comparer) → **fusion** quand c'est un doublon, **laisser tranquille** quand c'est un homonyme légitime. Sources de paires candidates : formes de nom partagées / compatibles (le générateur de paires actuel), et **même valeur d'identifiant brut portée par des `source_authorships` à `person_id` distincts** (souvent doublon, parfois erreur). Le tri s'appuie sur des recouvrements chiffrés : co-auteurs, labos, sujets, revues — réseaux disjoints pointent vers l'homonymie légitime, réseaux communs vers le doublon.
- **Signaux mono-personne** (une seule personne, mal accrochée) → **détachement**. Deux détecteurs : (1) **même `person_id` sur ≥2 `source_authorships` d'une même `source_publication`** — une personne ne peut pas signer deux positions d'un même enregistrement, c'est une erreur certaine ; complémentaire du garde `_dubious` car cette double-accroche peut provenir d'un match par forme de nom, que `_dubious` ne voit pas ; (2) **nom manifestement collectif** sur la signature (« for the … study group », « consortium », « collaboration »). Variante de très haute précision du détecteur (1), mesurée par l'audit : quand sur une même `source_publication` une personne apparaît **deux fois** — une occurrence par identifiant au nom **incompatible** (l'intrus), une occurrence par nom **compatible** (le porteur légitime) — l'intrus est une erreur d'attribution d'identifiant prouvée, détachable d'office. L'audit en dénombre ~11,9k rattachements sur 104 personnes, à 99 % via ORCID crossref + openalex (réparti ~50/50, OpenAlex recopiant le `raw_orcid` de crossref ; HAL quasi propre, ORCID de provenance indépendante).

S'y ajoute la **capture des conflits d'identifiants** internes à la cascade de matching : quand les signaux identifiants d'une même authorship divergent (l'ORCID pointe la personne A, l'idref la personne B), ou qu'un identifiant brut pointe une personne différente de celle finalement retenue, la divergence signe un doublon réel ou une erreur d'attribution. Aujourd'hui la cascade tranche silencieusement par priorité (ORCID > hal > idref) ; matérialiser ces divergences en fait un signal exploitable.

## Phasage

Progression du certain et borné vers l'ambigu et ouvert : chaque étape laisse une base plus propre à la suivante. Le point d'entrée est l'étape 1.

### Étape 1 — Corruption éparse d'identifiant : prévenir + remédier

Le bout concret, parce que la cible est mesurée et bornée. Même logique de comparaison de noms des deux côtés : la corroboration empêche l'injection à venir, le détachement nettoie le stock déjà prouvé.

- [x] **Corroboration par le nom au matching identifiant** (1b31d2df) : un match par ORCID / hal_person_id / idref dont le nom de la personne ciblée est incompatible avec la signature (`names_compatible`) est refusé, chaque rejet journalisé (identifiant + les deux formes). Ampleur mesurée par l'audit `interfaces/cli/oneshot/audit_identifier_name_corroboration.py`. Reste à statuer sur les faux rejets résiduels (changement de nom, translittération).
- [ ] **Détachement du stock prouvé** : détacher les intrus repérés par le détecteur intrus-identifiant + porteur-légitime (~11,9k rattachements / 104 personnes, à 99 % via ORCID crossref + openalex). Détecteurs d'erreur connexes à brancher au passage : même `person_id` sur ≥2 `source_authorships` d'une même `source_publication` ; nom manifestement collectif sur la signature.

### Étape 2 — Verrouiller le non-retour

- [x] **Verdict bloquant `name_form ↔ person`** (066c3755, 66ca7b0b) — antidote à l'amplificateur secondaire (une signature mal rattachée devient une forme de nom de la personne et en attire d'autres par matching de nom ; verrouille ce que l'étape 1 vient de détacher). Statut `pending` / `confirmed` / `rejected` sur `person_name_forms` (enum partagée avec `person_identifiers`). Les formes dérivées du nom/prénom (source `'persons'`) sont confirmées d'office. Le recalcul (populate et chemin live) ne touche jamais aux statuts et ne supprime jamais un `confirmed`/`rejected`, sauf une forme `'persons'` rendue obsolète par une édition du nom. Au matching : `fetch_name_form_map` exclut les `rejected` (la forme rejetée ne propose plus la personne par nom) ; la corroboration du match par identifiant consulte le statut — `confirmed` corrobore sans test de tokens (gère le changement de nom), `rejected` refuse, sinon test de compatibilité par tokens. Les actions humaines confirm/reject (endpoints + UI) sont en étape 4.

### Étape 3 — Dédoublonnage du stock ambigu

Le gros morceau flou, itératif et human-in-the-loop, attaqué sur une base déjà assainie par les étapes 1-2.

Un seul moteur de dédoublonnage : des paires candidates `(A, B)` issues de plusieurs sources, une classification homonymie / doublon / erreur, trois actions.

- [ ] **Sources de paires candidates** : (i) **formes de nom ambiguës** — une forme portée par ≥2 `person_id` ; (ii) **liens par identifiant** — même valeur d'identifiant brut portée par des `source_authorships` rattachées à des `person_id` distincts, ou identifiants divergents sur une même signature (l'ORCID résout vers A, l'idref vers B). Les conflits d'identifiants ne sont pas une machinerie à part : c'est une source de paires de plus, à fort signal.
- [ ] **Classification homonymie / doublon / erreur** : pour chaque paire, recouvrements chiffrés (co-auteurs, labos, sujets, revues) — réseaux disjoints → homonymie légitime, communs → doublon ; un lien par identifiant sans recouvrement → erreur d'attribution. Définir l'agrégation en score, à partir de cas réels (méthode empirique, pas de typologie a priori).
- [ ] **Verdicts sur les formes de nom ambiguës à ≥1 lien `pending`** : matérialiser la classification en statut `person_name_forms` — homonymie → `confirmed` sur chaque personne (les deux gardent la forme) ; doublon → fusion puis `confirmed` ; erreur → `rejected` (bloque le retour, cf. verrou de l'étape 2). Audit de classification d'abord, action UI ensuite (étape 4).
- [ ] **Forme de l'outillage à trancher** : empirique d'abord (audits bottom-up), puis assistance human-in-the-loop dans l'UI. Probablement un mélange : correction automatique des erreurs nettes à haute confiance, suggestions pour les doublons probables, signalement non-intrusif des homonymies légitimes à laisser tranquilles.

### Étape 4 — Outillage humain : refonte `admin/persons`

Au service de l'étape 3. L'existant ne donne pas satisfaction : le générateur de paires candidates impose une navigation forcée d'une paire à l'autre, n'expose comme éléments de décision que les titres des publications, et `distinct_persons` ne sert qu'à ne plus re-suggérer une paire. Deux options ouvertes, à trancher :

- [ ] **Remplacer** par un autre outil ;
- [ ] **Retravailler** l'existant pour le rendre utilisable : consultation de la **liste** des candidats doublons (au lieu de la navigation paire-par-paire imposée), et présentation des **éléments de décision chiffrés** (scores de recouvrement co-auteurs, sujets, revues, labos — pas seulement les titres de publications).
- [ ] **Endpoints et UI de validation des formes de nom** (action humaine du verrou de l'étape 2, dont le socle backend est en place) : confirmer / rejeter un lien `(name_form, person_id)`. Un rejet bloque le retour de la forme au matching par nom ; une confirmation corrobore les matchs par identifiant sans test de nom. Inclut la bascule de `detach_name_form` (aujourd'hui un DELETE, donc la forme revient au recompute suivant) en pose de statut `rejected` (qui bloque durablement).

### Renforts optionnels (hors chemin critique)

Conservateurs, activables une fois le reste en place ; pas des prérequis.

- [ ] **Option de config `confirmed`-only** (défaut `false`) : restreint le matching aux identifiants `confirmed` ; les `pending` deviennent no-op. Évaluer l'impact (volume d'orphelins, besoin d'un flux de confirmation) avant d'envisager de l'activer sur une base curée.
- [ ] **Vérification ORCID via API** : récupérer le nom canonique — et affiliation / domaine de l'adresse mail si exposés — et confirmer ou rejeter le couple identifiant ↔ personne. Mesurer la couverture (combien de profils exposent un nom exploitable) et le taux de corroboration.
- [ ] **API IdRef** ?

## Questions ouvertes

- **Agrégation des recouvrements en score.** Pondération et seuils pour combiner co-auteurs / labos / sujets / revues en un score homonymie vs doublon par paire. Un vrai homonyme a des réseaux disjoints ; un doublon les a communs — reste à calibrer la frontière.
- **Frontière automatique / humain.** Quels cas corriger d'office (erreurs nettes à haute confiance), quels cas seulement suggérer (doublons probables), quels cas ne jamais toucher (homonymies légitimes).
- **Corroboration par le nom : faux rejets résiduels.** La comparaison par tokens règle les initiales et les noms multi-mots ; restent les **changements de nom** (« Van Lander » → « Maneval », mariage / jeune fille) et les translittérations, où la signature et la personne n'ont aucun token en commun. À décider : rejeter quand même, ou conditionner le rejet à l'absence de tout autre signal concordant.
- **Flux de confirmation des identifiants.** Si on active `confirmed`-only, comment confirmer à l'échelle : auto-confirmation sur faisceau d'indices, confirmation humaine ciblée, ou apport de la vérification ORCID.
- **Vérification ORCID : modalités.** Contact polite-pool propre à l'API ORCID (distinct de celui d'OpenAlex), rate-limiting et cache, et destination des verdicts (transition `pending` → `confirmed` / `rejected` sur `person_identifiers`, ou table dédiée).
