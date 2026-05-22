# Chantier — Documentation HTML précompilée avec sommaire scrollable

Commencé le 2026-05-22

## Contexte

La page `/docs` fonctionne mais s'appuie sur un rendu client lourd :

- `marked` parse le markdown **côté client** à chaque navigation
  ([interfaces/frontend/src/routes/docs/[slug]/+page.svelte:55-66](interfaces/frontend/src/routes/docs/%5Bslug%5D/+page.svelte#L55-L66))
- Mermaid render côté client après `tick()`, avec FOUC potentiel
- La TOC est extraite du DOM par un `MutationObserver`
  ([interfaces/frontend/src/routes/docs/+layout.svelte:42-48](interfaces/frontend/src/routes/docs/+layout.svelte#L42-L48))
- Les liens internes sont patchés en regex sur le HTML rendu
  ([interfaces/frontend/src/routes/docs/[slug]/+page.svelte:75-80](interfaces/frontend/src/routes/docs/%5Bslug%5D/+page.svelte#L75-L80))
- Pas de syntax highlighting
- Sidebar plate (pas de hiérarchie), pas de scrollspy sur la TOC

Source actuelle des pages :
[interfaces/api/routers/docs.py](interfaces/api/routers/docs.py) lit les `.md`
depuis `docs/` (liste hardcodée de 7 pages : `architecture`, `donnees`,
`sources`, `pipeline`, `exploitation`, `guide-utilisateur`, `glossaire`).
Les fiches `docs/chantiers/*.md` ne sont pas exposées en ligne.

Référence visuelle : `svelte.dev/docs/kit` — sidebar gauche scrollable avec
sections imbriquées, contenu central, TOC à droite sticky avec scrollspy,
code highlighté, mermaid pré-rendu.

## Décisions

- **Compilation au build SvelteKit, pas au runtime** : un `+page.server.ts`
  lit chaque `.md` au filesystem, parse en HTML + extrait la TOC, et la
  route est marquée `prerender = true`. La sortie est du HTML statique
  servi par l'adapter Node existant.

- **Le backend FastAPI ne sert plus la doc** : suppression de
  `interfaces/api/routers/docs.py` et de son enregistrement dans
  `interfaces/api/app.py`. Conséquence : un changement de doc nécessite
  un rebuild frontend (équivalent au cycle code → commit → déploiement
  déjà en place).

- **Périmètre figé aux 7 pages actuelles** (`architecture`, `donnees`, `sources`, `pipeline`, `exploitation`, `guide-utilisateur`, `glossaire`). Extensions possibles à terme, hors scope de ce chantier : indexation des fiches `docs/chantiers/*.md`, ajout de pages « workflow admin », pages par agrégat (schéma + pipeline + UI pour chaque entité), ou éclatement des pages longues actuelles en pages plus courtes pour la lisibilité.

- **Stack de parsing minimale** : `marked` côté Node (déjà connu du projet) avec un renderer custom pour les ancres et les liens internes. Pas de syntax highlighting dans un premier temps (peu de blocs de code dans la doc actuelle). Mermaid reste client-side comme aujourd'hui — le léger délai de chargement est acceptable.

- **Extraction de la TOC par le parser, pas par le DOM** : le renderer
  collecte les `h2`/`h3` et leurs ancres pendant le parse. Plus de
  `MutationObserver`, plus de `tick()`.

- **Liens internes résolus au build** : `[texte](glossaire#terme)` →
  `<a href="/bibliometrie/docs/glossaire#terme">` directement dans le
  HTML pré-rendu. Plus de regex au runtime.

- **Le TODO collector est retiré** : la page `/docs/todos` et l'endpoint
  `/api/docs/todos/all` disparaissent avec la migration. Un fichier de
  changelog viendra plus tard.

- **Titre de page = premier `h1` du `.md`** : pas de duplication avec une
  liste maintenue à part. Le parser l'extrait pendant le parse.

- **Ordre des pages dans la sidebar = `interfaces/frontend/src/lib/docs/pages.ts`** :
  un module qui exporte la liste ordonnée des slugs
  (`architecture`, `donnees`, `sources`, `pipeline`, `exploitation`,
  `guide-utilisateur`, `glossaire`). Court, typé, facile à éditer.

- **Le layout reprend les codes svelte.dev** :
  - sidebar gauche avec arborescence (sections imbriquées si besoin),
    sticky, scrollable indépendamment du contenu
  - contenu central avec largeur max raisonnable
  - TOC droite sticky avec scrollspy actif sur la section visible
  - styles unifiés avec le reste du frontend (variables CSS existantes)

## Phasage

### Phase 1 — Module de parsing

- [x] `marked` est déjà installé côté frontend, rien à ajouter
- [x] Créer `interfaces/frontend/src/lib/docs/` :
  - [x] `pages.ts` : liste ordonnée des slugs
  - [x] `parser.ts` : `parseMarkdown(content, base) → { html, toc, title }`
  - [x] `links.ts` : résolution des liens internes
  - [x] `mermaid.ts` : fonction `renderMermaidBlocks(container)` extraite de l'inline actuel
- [x] Tests unitaires sur le parser et les liens : ancres déterministes (Unicode), liens internes, blocs mermaid préservés, table des matières, h1 → titre

### Phase 2 — Routes prerendered

- [x] `/docs/[slug]/+page.server.ts` :
  - [x] `load()` lit le `.md` via `import.meta.glob` (HMR gratuit, contenu embarqué au build)
  - [x] `export const prerender = true`
  - [x] `export function entries()` énumère les slugs de `pages.ts`
  - [x] retourne `{ html, toc, title }`
- [x] `/docs/+layout.svelte` réécrit :
  - [x] sidebar gauche (props depuis `+layout.server.ts` qui extrait les h1 des `.md`)
  - [x] TOC droite (props depuis la page)
  - [x] scrollspy via `IntersectionObserver` sur les ancres de la TOC
- [x] Suppression du `marked` runtime, du `MutationObserver`, du `fixLinks` regex
- [x] Parser : support des ancres custom via `<span id="..."></span>` dans les headings, rendu inline markdown dans la TOC
- [x] Parser : tolérance CRLF/LF (fichiers `.md` en formats mixtes)
- [x] Audit syntaxe markdown : liens `chantiers/*` en backtick (notes internes, hors doc en ligne), liens vers code source en URL GitHub absolue, ancres cassées corrigées

### Phase 3 — Style et UX

- [ ] `/docs` (index) : landing avec présentation des sections plutôt qu'une
  redirection JS
- [ ] Polish responsive : la sidebar passe en menu burger sur mobile

### Phase 4 — Retrait du backend doc et de la page TODOs

- [ ] Supprimer `interfaces/api/routers/docs.py`
- [ ] Retirer l'inclusion du router dans
  [interfaces/api/app.py](interfaces/api/app.py)
- [ ] Supprimer la route frontend `/docs/todos` et le lien correspondant
  dans la sidebar
  ([interfaces/frontend/src/routes/docs/+layout.svelte:71-76](interfaces/frontend/src/routes/docs/+layout.svelte#L71-L76))
- [ ] Nettoyer les éventuels tests
- [ ] Vérifier qu'aucun appel `api("/api/docs/...")` ne subsiste côté frontend
- [ ] Vérifier qu'aucun lien externe ou bookmark ne pointe vers `/api/docs/...`

## Questions ouvertes

- **Adapter SvelteKit** : `adapter-node` (actuel) ou `adapter-static` pour la partie docs ? On reste probablement sur `adapter-node` avec routes prerendered (le HTML est généré au build, servi par le serveur Node — pas besoin d'adapter-static).

- **Migration du contenu** : certains `.md` actuels utilisent une syntaxe qui passait dans le rendu client (ex. `[texte](slug)` sans extension). À auditer pendant la phase 1, ou à corriger en cours de migration.
