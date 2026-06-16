# Chantier — Déduplication des publications sans identifiant fiable (arête pairwise-gated)

## Contexte

Issu de [DATA_publications-match-or-create](DATA_publications-match-or-create.md) (Phase 3, item 3.2b, renvoyé ici). La déduplication des publications repose sur des **tokens de confirmation par égalité** — DOI, NNT, hal_id, pmid, et le composite thèse `(title_normalized, pub_year)` — qui entrent nativement dans `connected_components` (`domain/publications/clustering.py`) : deux `source_publications` partageant un token sont reliées, la composante est l'œuvre. Ce mécanisme couvre les œuvres à **identifiant fiable** ou à **clé de blocage sélective** (un titre de thèse est unique).

Restent les types **sans identifiant fiable** et à **titre souvent générique**, que ces tokens ne dédupliquent pas :

| doc_type | SP au stock (2026-06) | difficulté |
|---|---|---|
| `conference_paper` | ~29 500 | titres parfois génériques (sessions, « Keynote ») |
| `book_chapter` | ~18 800 | titres très génériques (« Introduction », « Chapitre 1 ») — cas dur |
| `poster` | ~3 500 | proche de `conference_paper` |

Pour ces types, la clé de blocage `(doc_type, title_normalized, pub_year)` est **trop peu sélective** pour valoir identité : deux communications « Welcome address » 2020 ne sont pas la même œuvre. Il faut un **second accord** au-delà du titre+année.

## Cadre conceptuel — l'axe token vs garde pairwise

Hérité de la fiche d'origine, c'est la distinction structurante :

- **Token (confirmation par égalité)** — une clé composite dérivable de la SP, assez **sélective** pour valoir identité. Elle entre dans `connected_components`, zéro comparaison intra-bloc. Cas couverts : identifiants, thèse `(titre, année)`.
- **Garde pairwise (convergence conservatrice)** — pour une clé de blocage **faible**, une condition d'accord **supplémentaire** (ex. nombre d'auteurs identique) qui n'**arme l'arête que si elle tient**. À l'appariement, un désaccord laisse les records **non-fusionnés** (on ne fusionne jamais sur preuve faible). Mais l'appartenance reste une **fonction dérivée des arêtes courantes** : si la condition cesse de tenir plus tard, l'arête disparaît et la composante se recalcule — donc un split est *possible*, symétriquement aux tokens. Le risque associé (dé-fusionner un vrai doublon quand un signal **bruité** fluctue) est une question ouverte de **stabilité du prédicat** (cf. plus bas), pas une raison de figer les fusions.

Pourquoi le compte d'auteurs ne peut **pas** être un token : il **varie par source pour la même œuvre** (OpenAlex tronque, HAL liste tout — mesuré : ~16 % des publis multi-sources ont des comptes d'auteurs divergents). Token-iser le compte scinderait de vrais doublons. C'est donc un **prédicat pairwise**, évalué à l'appariement, jamais une clé d'égalité. Il est en revanche **matérialisable** (colonne SP ou projection) pour la perf de l'évaluation, sans changer sa nature.

## Méthode — audit empirique par type

On n'ajoute **pas** un type sans mesurer son blocage. Recette (la même que pour la thèse) : sur les blocs `(doc_type, title_normalized, pub_year)` à ≥2 SP, mesurer la **divergence réelle** du second signal candidat.

- Divergence ≈ 0 → la clé est assez sélective seule → **token pur** (zéro garde).
- Divergence non négligeable → **garde pairwise** (second accord) ou **clé de blocage enrichie**.

Et on construit le mécanisme **à la demande**, avec son **premier consommateur réel** — pas d'abstraction spéculative. L'audit de chaque type décide s'il devient un token (et alors aucun mécanisme nouveau) ou une arête gardée.

## Mécanisme à construire (quand le premier type le justifie)

Une **arête pairwise-gated** dans la réconciliation (`reconcile_components`) : pour les SP co-bloquées (même `doc_type` + `title_normalized` + `pub_year`), évaluer le prédicat pairwise ; si vrai, **armer l'arête** (l'ajouter au graphe que voit `connected_components`), sinon laisser les SP séparées. Distinct du token (qui entre nativement dans le graphe). La projection partagée `domain/source_publications/keys.py` reste la définition unique des tokens ; les arêtes gardées sont un second canal, hors token.

Contraintes héritées :

- **Cannot-link DOI** préservé : une arête gardée ne fusionne jamais deux DOI distincts (l'ancre DOI et la partition restent souverains).
- **Le blocking est le vrai travail pour ces types** : leurs titres sont trop génériques pour bloquer finement (un bloc `book_chapter` « Introduction » + année colle des centaines d'œuvres sans rapport, et la confirmation pairwise y est quadratique). Les mitigations sont standard — clés composites/canopy, sorted-neighborhood, drop des blocs à titre stop, ou, pour les chapitres, bloquer sur le **conteneur** (l'ouvrage) plutôt que sur le titre. C'est le cœur du design par type.

## Phases (à dérouler par type, empiriquement)

- [ ] **conference_paper** — audit volume + divergence du compte d'auteurs sur les blocs `(conference_paper, titre>seuil, année)`. Décider token vs garde pairwise. Premier consommateur probable du mécanisme.
- [ ] **poster** — idem `conference_paper` (probablement même forme).
- [ ] **book_chapter** — **cas dur** : titres trop génériques pour que `(type, titre, année)` bloque utilement. Il faut l'identité du **conteneur** (l'ouvrage) — recoupe la correction chapitre/chapitre de la fiche d'origine (Phase 2). À cadrer à part : la clé de blocage n'est pas le titre du chapitre mais `(ouvrage, position/titre de chapitre)`.

## Questions ouvertes

- **Prédicat pairwise et sur-fusion** : un second accord trop faible (titre générique + même année + même compte d'auteurs par hasard) peut sur-fusionner. Mesurer la précision par type avant de figer.
- **Stabilité du prédicat vs dé-fusion (split sur bruit)** : l'appartenance étant dérivée des arêtes courantes, une arête pairwise qui tombe **peut** splitter — souhaitable si le signal est fiable, néfaste s'il est bruité. Exemple : deux communications fusionnées sur accord du compte d'auteurs (3 = 3) ; une source révise sa liste (→ 5) ; l'arête tombe → split, alors que c'est la **même œuvre** (enrichissement, pas preuve de distinction). Le bon levier n'est **pas** « interdire le split des fusions pairwise » (ça casserait la pureté « appartenance = fonction de l'état »), mais **choisir des prédicats stables** : l'identité du **conteneur** (chapitres) est stable → split seulement sur vrai changement ; le **compte d'auteurs** est bruité → risque réel. Privilégier les signaux stables, et mesurer le taux de dé-fusion par type avant de retenir un prédicat instable.
- **Thèse mistypée sans `journal_id`** (renvoyée depuis la fiche d'origine) : SP typées thèse portant un DOI éditeur sans `journal_id` (~69 au stock, dont 3 partageant un DOI avec un article). Relève d'une **correction de `doc_type`** (étendre `THESIS_WITH_JOURNAL_TO_ARTICLE` au signal DOI éditeur, unaire ou relationnel), pas de la dédup pairwise — mais à traiter dans le même mouvement d'étoffement des règles.

## Liens

- [DATA_publications-match-or-create](DATA_publications-match-or-create.md) — fiche d'origine : tokens de confirmation, réconciliation unifiée merge+split, ancre DOI, vocabulaire token/garde-pairwise. L'item 3.2b y renvoie ici.
- [METIER_doc-types](METIER_doc-types.md) — nomenclature canonique des `doc_type`.
- [METIER_relations-publications](METIER_relations-publications.md) — un identifiant secondaire pontant deux DOI = relation, pas fusion.
