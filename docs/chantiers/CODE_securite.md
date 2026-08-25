# Chantier — Durcissement pour l'hébergement universitaire

## Contexte

L'hébergement de l'application par l'UCA est conditionné par le RSSI à une analyse selon deux axes, plus un volet de suivi :

1. **Analyse code / sécurité applicative** : bonnes pratiques de développement sécurisé, pas de dépendance vulnérable, maîtrise des points d'entrée (API, authentification).
2. **Analyse infrastructure** : hébergement totalement cloisonné (réseau et système hôte) pour éviter escalade de privilèges, latéralisation, intrusion, déni de service entrant ou sortant vers des SI extérieurs.
3. **Suivi dynamique dans le temps** : outils d'audit, veille, gouvernance.

Un audit interne a balayé six angles (surface d'API et authentification, dépendances, secrets et configuration, injections, posture infra et trafic sortant, sécurité frontend). Verdict d'ensemble : posture au-dessus de la moyenne, **aucune faille critique**. Le socle est sain — auth sur les mutations, injections SQL maîtrisées (bind params, tris en liste blanche), sortant borné par liste blanche d'hôtes (pas de SSRF), DoS sortant tenu par circuit-breaker et sémaphores, dépendances épinglées et scannées. Ce chantier regroupe les points à traiter avant mise en production, à régler un par un.

### Données personnelles — hors risque

La base contient des données personnelles de chercheurs (`persons` : identité ; `person_identifiers` : ORCID/idHAL/idref ; `persons_rh` : email, poste, dates de contrat). Ce point est **versé au dossier pour information, sans exigence de remédiation** :

- ces données sont **publiques** (postes et dates poussés par l'UCA sur les profils ORCID des chercheurs) ;
- l'accès à l'application est **réservé aux personnels UCA** ;
- les adresses email sont stockées en base mais **ne sont pas affichées** dans l'application.

## Décisions

- **Terminaison TLS par reverse-proxy** en frontal de l'application. Point d'ancrage de plusieurs corrections (chiffrement en transit, cookie `Secure`, en-têtes de sécurité, rate limiting réseau, cloisonnement) : à privilégier plutôt que de réimplémenter ces protections dans l'application.
- **Mise à jour automatisée des dépendances** (Dependabot ou Renovate) sur les écosystèmes pip et npm, en complément des scans `pip-audit` / `npm audit` déjà bloquants au push. La détection existe ; la remédiation devient un flux de pull requests plutôt qu'une veille manuelle.
- **XSS Tooltip corrigé** hors de ce phasage (commit `b623d922`) : `Tooltip` rend son contenu en texte, `structsTooltip` produit du texte simple. Reste, en défense en profondeur, l'assainissement des titres et le second point d'injection HTML latent (phase dédiée ci-dessous).

## Phasage

### Fait

- [x] **XSS `Tooltip` sur `/publications/[id]`** — l'affiliation brute d'une source externe transitait par `{@html}`. `Tooltip` rend `{text}` (sauts de ligne en CSS `white-space: pre-line`), `structsTooltip` produit du texte. Test de non-régression sur `structsTooltip`. Commit `b623d922`.

### Phase 1 — Durcissement de l'API (code applicatif)

- [x] **Rate limiting du login** — limiteur applicatif à fenêtre fixe par IP sur `/api/auth/login` (`interfaces/api/rate_limit.py`, 10 tentatives / 5 min, 429 au-delà), sans dépendance externe. Le DoS sur les lectures lourdes (exports CSV, agrégations) relève de la fréquence des requêtes, traité au reverse-proxy réseau (phase 3), pas d'un plafond par requête. Commit `5b2313df`.
- [x] **Cookie de session `Secure`** — réglage `cookie_secure` (défaut vrai), desserré en HTTP local via `.env`. Commit `5b2469b5`.
- [x] **Docs OpenAPI privées** — réglage `expose_api_docs` (défaut faux) coupe `/docs`, `/redoc`, `/openapi.json` ; la génération du schéma frontend passe par `app.openapi()`. Commit `5b2469b5`.
- [x] **Révocabilité de session (globale)** — le jeton étant signé par `SESSION_SECRET`, en changer la valeur invalide tous les jetons émis : c'est la déconnexion globale, documentée dans `.env.example`. Suffisant pour l'unique compte admin actuel. La révocation fine (par session) via sessions à état se reposera à l'arrivée de plusieurs comptes.
- [x] **Credentials sources write-only** — `SECRET_CONFIG_KEYS` (`domain/config.py`) : la lecture masque la valeur (`value: null` + `is_set`), l'écriture reste ouverte. Frontend : ronds noirs si défini, `(non défini)` sinon, édition qui ne réécrit pas un secret laissé vide. Piste future non prioritaire : un bouton « Tester la connexion » par source (exerce la clé côté serveur, renvoie vert/rouge) comme équivalent sûr d'un affichage en clair.

### Phase 2 — En-têtes de sécurité et défense en profondeur frontend

- [x] **En-têtes de sécurité** — middleware FastAPI posant `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` (anti-clickjacking) et `Referrer-Policy` sur chaque réponse. HSTS reste au reverse-proxy TLS. Commit `1c0602bd`.
- [x] **Content-Security-Policy** — CSP native SvelteKit en mode hash, injectée en `<meta>` par page (`script-src 'self'` + empreinte du bootstrap inline, sans `unsafe-inline`). Vérifiée en local (Chrome headless, zéro violation) ; le bundle client ne fait ni `eval` ni Worker/WASM. `frame-ancestors` non exprimable en meta, couvert par `X-Frame-Options`. Commit `284c9b97`.
- [x] **Assainissement des titres par DOMPurify** — `sanitizeTitle` remplace son sanitiseur regex par DOMPurify (même liste blanche) ; dompurify déclaré en dépendance directe. Commit `7e17d9fa`.
- [x] **Point d'injection HTML latent `FacetDropdown`** — `{@html}` converti en rendu texte, comme `Tooltip`. Commit `279442a4`.

### Phase 3 — Cloisonnement infrastructure (déploiement)

La DSI gère le conteneur et la machine virtuelle (isolation réseau, exposition des ports, cloisonnement de l'hôte) selon ses propres exigences. Ce volet se limite donc à ce qui vit dans le dépôt : l'image de référence, la connexion applicative et les défauts de configuration.

- [x] **Image de production non-root** — utilisateur `appuser` (uid 10001) et bascule `USER` dans le `Dockerfile` de production ; l'API ne tourne plus en root. Commit `09372bd0`. Les Dockerfile de dev restent en root (écriture via bind-mount, usage local uniquement).
- [x] **TLS vers la base** — réglage `db_sslmode` injecté dans la connexion (`infrastructure/db/engine.py`), réutilisé par Alembic. Commit `09372bd0`.
- [x] **Défauts de mot de passe compose** — `${...:-changeme}` remplacé par la forme fail-safe `${...:?}` : refus de démarrage sans secret explicite. Commit `731c18ee`.
- Exposition réseau des ports, reverse-proxy et cloisonnement de l'hôte : ressort de la DSI.

### Phase 4 — Suivi dynamique dans le temps

- [x] **Mise à jour automatisée des dépendances** — `.github/dependabot.yml` : PR hebdomadaires sur pip (racine), npm (`interfaces/frontend`) et github-actions, mineures/correctives groupées par écosystème, majeures individuelles. Complète les scans `pip-audit` / `npm audit` bloquants au push.
- [x] **Blocage des secrets au push** — GitHub push protection activée : bloque côté serveur les secrets reconnus (motifs de fournisseurs) avant qu'ils n'atteignent le dépôt. Complément optionnel non retenu pour l'instant : gitleaks en pre-commit, qui ajoute la détection par entropie (secrets génériques : mot de passe DB, `SESSION_SECRET`) et un blocage local plus précoce.
- [x] **Alignement des postes de dev sur Node 22** — `interfaces/frontend/.nvmrc` fixe Node 22 (aligné sur la CI, `.github/workflows/ci.yml:88`) ; `nvm use` cale le poste dessus.

## Questions ouvertes

- **Rate limiting : où ?** Au reverse-proxy (nginx/traefik) ou applicatif (slowapi) ? Le proxy couvre le DoS réseau ; l'applicatif permet des règles fines par endpoint (login vs exports). Les deux ne s'excluent pas.
- **Révocation de session** : passer à des sessions à état (table de sessions) ou conserver le jeton stateless avec une simple liste de révocation / rotation de secret ? Arbitrage simplicité vs granularité.
- **Périmètre du reverse-proxy** : fourni par la DSI dans leur infra d'hébergement, ou embarqué dans le déploiement de l'application ? Détermine qui porte la config TLS, rate limiting et en-têtes.

## Liens

- Index des chantiers : [0_INDEX.md](0_INDEX.md)
- Commit du correctif XSS : `b623d922`
