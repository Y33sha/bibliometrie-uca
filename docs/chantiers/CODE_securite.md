# Chantier — Durcissement pour l'hébergement universitaire

## Contexte

L'hébergement de l'application par l'UCA est conditionné par le RSSI à une analyse selon deux axes, plus un volet de suivi :

1. **Analyse code / sécurité applicative** : bonnes pratiques de développement sécurisé, pas de dépendance vulnérable, maîtrise des points d'entrée (API, authentification).
2. **Analyse infrastructure** : hébergement totalement cloisonné (réseau et système hôte) pour éviter escalade de privilèges, latéralisation, intrusion, déni de service entrant ou sortant vers des SI extérieurs.
3. **Suivi dynamique dans le temps** : outils d'audit, veille, gouvernance.

Un audit interne a balayé six angles (surface d'API et authentification, dépendances, secrets et configuration, injections, posture infra et trafic sortant, sécurité frontend). Verdict d'ensemble : posture au-dessus de la moyenne, **aucune faille critique**. Le socle est sain — authentification sur les mutations, injections SQL maîtrisées (bind params, tris et dimensions de pivot en liste blanche), sortant borné par liste blanche d'hôtes et sans URL paramétrable (pas de SSRF ; l'API elle-même n'émet aucune requête réseau, tout le trafic sortant vit dans le pipeline lancé en ligne de commande), déni de service sortant tenu par circuit-breaker et sémaphores, dépendances épinglées et scannées, aucune primitive d'exécution (`subprocess`, `eval`, désérialisation) sur le chemin serveur. Ce chantier regroupe les points à traiter avant mise en production, à régler un par un.

### Données personnelles

La base contient des données personnelles de chercheurs : `persons` (identité), `person_identifiers` (ORCID/idHAL/idref), `persons_rh` (email, poste, service, dates de contrat). Trois constats :

- ces données sont **publiques** — postes et dates sont poussés par l'UCA sur les profils ORCID des chercheurs ;
- les adresses email sont stockées en base mais **aucune requête de lecture ne les sélectionne** : elles ne sortent pas de l'application ;
- le poste, le service et les dates de contrat, eux, sortent par les lectures des personnes, qui sont ouvertes.

L'argument « accès réservé aux personnels UCA » s'appuie sur une restriction qui ne vit pas dans le dépôt : aucune authentification ne garde les lectures. Elle est donc portée par l'hébergement (filtrage réseau, ou authentification au reverse-proxy) et doit être énoncée comme telle au dossier RSSI — ou implémentée dans l'application (phase 5).

## Décisions

- **Terminaison TLS par reverse-proxy** en frontal de l'application. Point d'ancrage de plusieurs corrections (chiffrement en transit, cookie `Secure`, en-têtes de sécurité, rate limiting réseau, cloisonnement) : à privilégier plutôt que de réimplémenter ces protections dans l'application.
- **Confiance dans les en-têtes de proxy : au serveur, pas dans l'application.** uvicorn embarque `ProxyHeadersMiddleware`, qui ne lit `X-Forwarded-For` que si le pair de la connexion figure dans `FORWARDED_ALLOW_IPS`, et qui remonte la liste des maillons de droite à gauche en écartant les proxys connus. L'application ne lit jamais l'en-tête : elle se contente de `request.client.host`, qu'uvicorn a déjà réécrit quand il y a lieu.
- **Mise à jour automatisée des dépendances** (Dependabot ou Renovate) sur les écosystèmes pip et npm, en complément des scans `pip-audit` / `npm audit` déjà bloquants au push. La détection existe ; la remédiation devient un flux de pull requests plutôt qu'une veille manuelle.
- **XSS Tooltip corrigé** hors de ce phasage (commit `b623d922`) : `Tooltip` rend son contenu en texte, `structsTooltip` produit du texte simple. Reste, en défense en profondeur, l'assainissement des titres et le second point d'injection HTML latent (phase dédiée ci-dessous).

## Phasage

### Fait

- [x] **XSS `Tooltip` sur `/publications/[id]`** — l'affiliation brute d'une source externe transitait par `{@html}`. `Tooltip` rend `{text}` (sauts de ligne en CSS `white-space: pre-line`), `structsTooltip` produit du texte. Test de non-régression sur `structsTooltip`. Commit `b623d922`.

### Phase 1 — Durcissement de l'API (code applicatif)

- [x] **Rate limiting du login** — limiteur applicatif à fenêtre fixe par IP sur `/api/auth/login` (`interfaces/api/rate_limit.py`, 10 tentatives / 5 min, 429 au-delà), sans dépendance externe. Le déni de service sur les lectures lourdes relève de la fréquence des requêtes, traité au reverse-proxy réseau (phase 3), pas d'un plafond par requête. Commit `5b2313df`.
- [ ] **Clé du limiteur de connexion** — `_client_key` retient le premier maillon de `X-Forwarded-For` dès que l'en-tête est présent. Deux défauts : sans proxy pour écraser l'en-tête, une valeur différente à chaque tentative ouvre un compteur neuf et le plafond ne protège de rien ; et derrière un proxy qui *ajoute* à l'en-tête (`$proxy_add_x_forwarded_for` chez nginx), ce premier maillon est justement la valeur fournie par le client. La clé se réduit à `request.client.host`. Documenter `FORWARDED_ALLOW_IPS` dans `.env.example` et la documentation de déploiement : sans elle, toutes les connexions partagent un compteur unique et dix échecs bloquent le login pour tout le monde pendant la fenêtre.
- [ ] **CORS validé par les settings** — la liste des origines autorisées est lue en brut depuis l'environnement dans `interfaces/api/app.py`. `CORS_ORIGINS=*` combiné à `allow_credentials=True` conduit Starlette à renvoyer l'`Origin` de l'appelant : toute origine devient autorisée, cookie de session compris. Faire passer la lecture par `infrastructure/settings.py`, avec refus explicite de `*`.
- [x] **Cookie de session `Secure`** — réglage `cookie_secure` (défaut vrai), desserré en HTTP local via `.env`. Commit `5b2469b5`.
- [x] **Docs OpenAPI privées** — réglage `expose_api_docs` (défaut faux) coupe `/docs`, `/redoc`, `/openapi.json` ; la génération du schéma frontend passe par `app.openapi()`. Commit `5b2469b5`.
- [x] **Révocabilité de session (globale)** — le jeton étant signé par `SESSION_SECRET`, en changer la valeur invalide tous les jetons émis : c'est la déconnexion globale, documentée dans `.env.example`. Suffisant pour l'unique compte admin actuel. La révocation fine (par session) via sessions à état se reposera à l'arrivée de plusieurs comptes.
- [x] **Credentials sources write-only** — `SECRET_CONFIG_KEYS` (`domain/config.py`) : la lecture masque la valeur (`value: null` + `is_set`), l'écriture reste ouverte. Frontend : ronds noirs si défini, `(non défini)` sinon, édition qui ne réécrit pas un secret laissé vide. Piste future non prioritaire : un bouton « Tester la connexion » par source (exerce la clé côté serveur, renvoie vert/rouge) comme équivalent sûr d'un affichage en clair.

### Phase 2 — En-têtes de sécurité et assainissement des sorties

- [x] **En-têtes de sécurité** — middleware FastAPI posant `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` (anti-clickjacking) et `Referrer-Policy` sur chaque réponse. HSTS reste au reverse-proxy TLS. Commit `1c0602bd`.
- [x] **Content-Security-Policy** — CSP native SvelteKit en mode hash, injectée en `<meta>` par page (`script-src 'self'` + empreinte du bootstrap inline, sans `unsafe-inline`). Vérifiée en local (Chrome headless, zéro violation) ; le bundle client ne fait ni `eval` ni Worker/WASM. `frame-ancestors` non exprimable en meta, couvert par `X-Frame-Options`. Commit `284c9b97`.
- [x] **Assainissement des titres par DOMPurify** — `sanitizeTitle` remplace son sanitiseur regex par DOMPurify (même liste blanche) ; dompurify déclaré en dépendance directe. Commit `7e17d9fa`.
- [x] **Point d'injection HTML latent `FacetDropdown`** — `{@html}` converti en rendu texte, comme `Tooltip`. Commit `279442a4`.
- [ ] **Injection de formule dans les exports CSV** — titres, revues et éditeurs viennent de HAL et OpenAlex, où un tiers dépose le contenu qu'il veut. Une cellule dont la valeur commence par `=`, `+`, `-` ou `@` est interprétée comme une formule à l'ouverture dans un tableur, sur le poste de qui télécharge l'export. Neutraliser ces cellules à l'écriture (`infrastructure/read_models/publications/list.py`), pour l'export des publications comme pour celui des thèses.

### Phase 3 — Cloisonnement infrastructure (déploiement)

La DSI gère le conteneur et la machine virtuelle (isolation réseau, exposition des ports, cloisonnement de l'hôte) selon ses propres exigences. Ce volet se limite donc à ce qui vit dans le dépôt : l'image de référence, la connexion applicative et les défauts de configuration.

- [x] **Image de production non-root** — utilisateur `appuser` (uid 10001) et bascule `USER` dans le `Dockerfile` de production ; l'API ne tourne plus en root. Commit `09372bd0`. Les Dockerfile de dev restent en root (écriture via bind-mount, usage local uniquement).
- [x] **TLS vers la base** — réglage `db_sslmode` injecté dans la connexion (`infrastructure/db/engine.py`), réutilisé par Alembic. Commit `09372bd0`.
- [x] **Défauts de mot de passe compose** — `${...:-changeme}` remplacé par la forme fail-safe `${...:?}` : refus de démarrage sans secret explicite. Commit `731c18ee`.
- [ ] **Rôle Postgres applicatif** — l'application se connecte avec le rôle d'installation de la base (`postgres` par défaut dans les deux fichiers compose), qui est superutilisateur. Un superutilisateur Postgres dispose de `COPY … PROGRAM`, donc de l'exécution de commandes sur l'hôte de la base : c'est précisément le scénario d'escalade que le RSSI demande d'écarter. Créer un rôle applicatif sans superutilisateur, limité au DML sur le schéma applicatif, et un rôle distinct porteur du DDL pour les migrations.
- [ ] **Durcissement du conteneur applicatif** — `docker-compose.prod.yml` : `security_opt: [no-new-privileges:true]`, `cap_drop: [ALL]`, système de fichiers racine en lecture seule, limites mémoire et CPU, `healthcheck`, et publication du port sur `127.0.0.1` plutôt que sur toutes les interfaces.
- Exposition réseau des ports, reverse-proxy et cloisonnement de l'hôte : ressort de la DSI. L'adresse du reverse-proxy lui est déclarée par `FORWARDED_ALLOW_IPS` (phase 1), sans quoi le limiteur de connexion ne distingue plus les clients.

### Phase 4 — Suivi dynamique dans le temps

- [x] **Mise à jour automatisée des dépendances** — `.github/dependabot.yml` : PR hebdomadaires sur pip (racine), npm (`interfaces/frontend`) et github-actions, mineures/correctives groupées par écosystème, majeures individuelles. Complète les scans `pip-audit` / `npm audit` bloquants au push.
- [x] **Blocage des secrets au push** — GitHub push protection activée : bloque côté serveur les secrets reconnus (motifs de fournisseurs) avant qu'ils n'atteignent le dépôt. Complément optionnel non retenu pour l'instant : gitleaks en pre-commit, qui ajoute la détection par entropie (secrets génériques : mot de passe DB, `SESSION_SECRET`) et un blocage local plus précoce.
- [x] **Alignement des postes de dev sur Node 22** — `interfaces/frontend/.nvmrc` fixe Node 22 (aligné sur la CI, `.github/workflows/ci.yml:88`) ; `nvm use` cale le poste dessus.

### Phase 5 — Surface de lecture anonyme

Toutes les lectures sont ouvertes : le middleware d'`interfaces/api/app.py` ne garde que les méthodes d'écriture, et la dépendance `require_admin` d'`interfaces/api/deps.py` n'est posée sur aucune route. Le premier point commande les deux autres, qui en sont les conséquences les plus coûteuses.

- [ ] **Frontière d'authentification en lecture** — trancher : la lecture reste ouverte et sa restriction est portée par l'hébergement, ou une session devient nécessaire, au moins sur les pages d'administration et sur les lectures qui rendent des données issues du fichier RH (poste, service, dates de contrat).
- [ ] **Export CSV sans plafond** — les deux exports de publications s'exécutent sans pagination et matérialisent le résultat entier en mémoire avant de l'envoyer. Ouverts et répétables, ils forment le vecteur de déni de service entrant le plus direct, et le moyen le plus simple d'extraire la base en masse. Plafonner le nombre de lignes rendues, ou réserver l'export à une session.
- [ ] **Log de phase du pipeline** — la lecture du log d'une phase relit `logs/pipeline.log` en entier à chaque appel et rend la section brute. Amplification mémoire proportionnelle à la taille du fichier, et exposition des traces d'exploitation. Borner la lecture (taille maximale, parcours par la fin) et réserver l'accès à une session. Sans portée tant que `LOG_TO_FILE` reste inactif, ce qui est le défaut en production.

## Questions ouvertes

- **Rate limiting : où ?** Le limiteur applicatif couvre le login ; le déni de service par fréquence sur les lectures lourdes reste à couvrir, au reverse-proxy (nginx/traefik) ou par un plafond applicatif par endpoint. Les deux ne s'excluent pas.
- **Révocation de session** : passer à des sessions à état (table de sessions) ou conserver le jeton stateless avec une simple liste de révocation / rotation de secret ? Arbitrage simplicité vs granularité.
- **Périmètre du reverse-proxy** : fourni par la DSI dans leur infra d'hébergement, ou embarqué dans le déploiement de l'application ? Détermine qui porte la config TLS, rate limiting et en-têtes.

## Liens

- Index des chantiers : [0_INDEX.md](0_INDEX.md)
- Commit du correctif XSS : `b623d922`
