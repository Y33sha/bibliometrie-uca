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

- [ ] **Content-Security-Policy et en-têtes de sécurité** — l'application est une SPA statique servie par FastAPI (`interfaces/api/app.py`), aucun en-tête de sécurité posé hormis `X-Response-Time`. Ajouter CSP, `X-Frame-Options`/`frame-ancestors` (anti-clickjacking), `X-Content-Type-Options: nosniff`, `Referrer-Policy`, HSTS — au reverse-proxy ou via un middleware FastAPI.
- [ ] **Assainissement des titres par bibliothèque** — `lib/utils.ts:133-142` (`sanitizeTitle`) parse le HTML des titres/résumés de publications (données externes) par expressions régulières maison, rendu via `{@html}` sur plusieurs pages publiques. DOMPurify (`dompurify@3.4.14`) est déjà dans l'arbre de dépendances : router ce HTML par DOMPurify.
- [ ] **Second point d'injection HTML latent** — `lib/components/FacetDropdown.svelte:141` rend une prop via `{@html}`, aujourd'hui alimentée par des littéraux statiques. Même piège que l'ancien `Tooltip` : convertir en rendu texte pour fermer le risque avant qu'un appelant y passe une donnée dynamique.

### Phase 3 — Cloisonnement infrastructure (déploiement)

- [ ] **Conteneurs non-root** — les trois Dockerfile n'ont pas de directive `USER` ; les conteneurs tournent en root. Ajouter un utilisateur non privilégié (répond directement au risque d'escalade / latéralisation cité par le RSSI).
- [ ] **Publication des ports sur loopback** — `docker-compose.prod.yml:41` publie `8003:8000` sur `0.0.0.0` de l'hôte. Restreindre à `127.0.0.1:8003:8000` derrière le reverse-proxy.
- [ ] **TLS vers la base** — `infrastructure/db/engine.py:21-29` et `alembic/env.py` construisent l'URL Postgres sans `sslmode`. Exiger `sslmode=require`/`verify-full` dès que la base n'est pas colocalisée.
- [ ] **Défauts de mot de passe compose** — `docker-compose.yml` / `docker-compose.prod.yml` utilisent `${...:-changeme}`. Retirer les valeurs par défaut faibles pour forcer l'injection explicite des secrets.

### Phase 4 — Suivi dynamique dans le temps

- [x] **Mise à jour automatisée des dépendances** — `.github/dependabot.yml` : PR hebdomadaires sur pip (racine), npm (`interfaces/frontend`) et github-actions, mineures/correctives groupées par écosystème, majeures individuelles. Complète les scans `pip-audit` / `npm audit` bloquants au push.
- [x] **Blocage des secrets au push** — GitHub push protection activée : bloque côté serveur les secrets reconnus (motifs de fournisseurs) avant qu'ils n'atteignent le dépôt. Complément optionnel non retenu pour l'instant : gitleaks en pre-commit, qui ajoute la détection par entropie (secrets génériques : mot de passe DB, `SESSION_SECRET`) et un blocage local plus précoce.
- [ ] **Alignement des postes de dev sur Node 22** — la CI utilise Node 22 (`.github/workflows/ci.yml:88`) ; les postes locaux sont sur Node 20, proche de sa fin de support.

## Questions ouvertes

- **Rate limiting : où ?** Au reverse-proxy (nginx/traefik) ou applicatif (slowapi) ? Le proxy couvre le DoS réseau ; l'applicatif permet des règles fines par endpoint (login vs exports). Les deux ne s'excluent pas.
- **Révocation de session** : passer à des sessions à état (table de sessions) ou conserver le jeton stateless avec une simple liste de révocation / rotation de secret ? Arbitrage simplicité vs granularité.
- **Périmètre du reverse-proxy** : fourni par la DSI dans leur infra d'hébergement, ou embarqué dans le déploiement de l'application ? Détermine qui porte la config TLS, rate limiting et en-têtes.

## Liens

- Index des chantiers : [0_INDEX.md](0_INDEX.md)
- Commit du correctif XSS : `b623d922`
