# Chantier — Documentation HTML précompilée avec sommaire scrollable

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

- **Stack de parsing** :
  - `marked` côté Node (déjà connu du projet) avec un renderer custom
    pour les ancres et les liens internes
  - `shiki` pour le syntax highlighting (rendu en HTML au build, zéro JS
    runtime ; thèmes intégrés)
  - Mermaid pré-rendu en SVG au build via `@mermaid-js/mermaid` headless
    ou un service worker au moment du SSR

- **Extraction de la TOC par le parser, pas par le DOM** : le renderer
  collecte les `h2`/`h3` et leurs ancres pendant le parse. Plus de
  `MutationObserver`, plus de `tick()`.

- **Liens internes résolus au build** : `[texte](glossaire#terme)` →
  `<a href="/bibliometrie/docs/glossaire#terme">` directement dans le
  HTML pré-rendu. Plus de regex au runtime.

- **TODO collector conservé en build-time** : la collecte des
  `<!-- TODO: ... -->` se fait au prerender et alimente la page
  `/docs/todos` (elle aussi prerendered).

- **Le layout reprend les codes svelte.dev** :
  - sidebar gauche avec arborescence (sections imbriquées si besoin),
    sticky, scrollable indépendamment du contenu
  - contenu central avec largeur max raisonnable
  - TOC droite sticky avec scrollspy actif sur la section visible
  - styles unifiés avec le reste du frontend (variables CSS existantes)

## Phasage

### Phase 1 — Module de parsing

- Ajouter `marked`, `shiki`, et la dépendance mermaid headless dans
  `interfaces/frontend/package.json`
- Créer `interfaces/frontend/src/lib/docs/` :
  - `parser.ts` : `parseMarkdown(content: string) → { html, toc, title }`
  - `links.ts` : résolution des liens internes (slug → URL absolue)
  - `mermaid.ts` : pré-rendu SVG d'un bloc mermaid
- Tests unitaires sur le parser : ancres déterministes, code highlight,
  liens internes, mermaid, table des matières

### Phase 2 — Routes prerendered

- `/docs/[slug]/+page.server.ts` :
  - `load()` lit `docs/{slug}.md` au filesystem
  - `export const prerender = true`
  - `export function entries()` énumère les `.md` de `docs/`
  - retourne `{ html, toc, title, pages }` (pages = liste pour la sidebar)
- `/docs/+layout.svelte` réécrit :
  - sidebar gauche (props depuis `+layout.server.ts` ou un `+layout.ts`)
  - TOC droite (props depuis la page)
  - scrollspy via `IntersectionObserver` sur les ancres de la TOC
- Suppression du `marked` runtime, du `MutationObserver`, du `fixLinks` regex
- Vérifier que `vite.config.ts` watche `docs/**/*.md` en dev (HMR sur
  édition de markdown)

### Phase 3 — Style et UX

- Thème shiki accordé aux couleurs du projet
- `/docs` (index) : landing avec présentation des sections plutôt qu'une
  redirection JS
- Polish responsive : la sidebar passe en menu burger sur mobile

### Phase 4 — Retrait du backend doc

- Supprimer `interfaces/api/routers/docs.py`
- Retirer l'inclusion du router dans
  [interfaces/api/app.py](interfaces/api/app.py)
- Nettoyer les éventuels tests
- Vérifier qu'aucun appel `api("/api/docs/...")` ne subsiste côté frontend
- Vérifier qu'aucun lien externe ou bookmark ne pointe vers `/api/docs/...`

## Questions ouvertes

- **Périmètre des pages indexées** : on garde les 7 pages actuelles,
  ou on étend à `docs/chantiers/*.md` (≈30 fichiers, dont `archived/`) ?
  Si on étend, la sidebar a besoin d'une hiérarchie (catégories CODE /
  DATA / METIER, état en-cours / archived).

- **Search** : Pagefind compile un index de recherche au build et
  s'intègre en quelques lignes. Utile si on indexe les chantiers (~40
  pages au total), probablement over-engineering pour 7 pages seules.

- **Pré-rendu Mermaid** : `@mermaid-js/mermaid` headless tourne sur
  Puppeteer/Playwright en CI (lourd). Alternative : conserver Mermaid
  client-side uniquement pour ces blocs, le reste prerendered.

- **Adapter SvelteKit** : `adapter-node` (actuel) ou `adapter-static`
  pour la partie docs ? On reste probablement sur `adapter-node` avec
  routes prerendered (le HTML est généré au build, servi par le
  serveur Node — pas besoin d'adapter-static).

- **Migration du contenu** : certains `.md` actuels utilisent une
  syntaxe qui passait dans le rendu client (ex. `[texte](slug)` sans
  extension). À auditer pendant la phase 1, ou à corriger en cours
  de migration.
