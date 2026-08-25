# Chantier — Durcissement pour l'hébergement universitaire

## Contexte

L'hébergement de l'application par l'UCA est conditionné par le RSSI à une analyse selon deux axes, plus un volet de suivi :

1. **Analyse code / sécurité applicative** : bonnes pratiques de développement sécurisé, pas de dépendance vulnérable, maîtrise des points d'entrée (API, authentification).
2. **Analyse infrastructure** : hébergement totalement cloisonné (réseau et système hôte) pour éviter escalade de privilèges, latéralisation, intrusion, déni de service entrant ou sortant vers des SI extérieurs.
3. **Suivi dynamique dans le temps** : outils d'audit, veille, gouvernance.

Un audit interne a balayé six angles (surface d'API et authentification, dépendances, secrets et configuration, injections, posture infra et trafic sortant, sécurité frontend). Verdict d'ensemble : posture au-dessus de la moyenne, **aucune faille critique**. Le socle est sain — authentification sur les mutations, injections SQL maîtrisées (bind params, tris et dimensions de pivot en liste blanche), sortant borné par liste blanche d'hôtes et sans URL paramétrable (pas de SSRF ; l'API elle-même n'émet aucune requête réseau, tout le trafic sortant vit dans le pipeline lancé en ligne de commande), déni de service sortant tenu par circuit-breaker et sémaphores, dépendances épinglées et scannées, aucune primitive d'exécution (`subprocess`, `eval`, désérialisation) sur le chemin serveur. Ce chantier regroupe les points à traiter avant mise en production, à régler un par un.

### Ce que la base contient de sensible

Une seule catégorie : les **identifiants d'accès aux sources** — clés d'API OpenAlex et Web of Science, compte ScanR. Ils sont write-only, une liste blanche de clés bornant ce que la lecture de la configuration rend (`domain/config.py`). Les journaux du pipeline ne les portent pas davantage : aucune trace n'écrit une valeur de configuration secrète ni une URL qui en contienne une.

Le reste des données est **public par nature** : publications, revues, éditeurs, structures, et les personnes qui les signent. La base porte des données personnelles de chercheurs — `persons` (identité), `person_identifiers` (ORCID/idHAL/idref), `persons_rh` (poste, service, dates de contrat) —, mais ce sont celles que l'UCA pousse elle-même sur les profils ORCID publics. Les adresses email, seule donnée de contact, sont stockées sans qu'aucune requête de lecture ne les sélectionne : elles ne sortent pas de l'application.

## Décisions

- **La lecture reste ouverte ; sa restriction relève de l'hébergement.** Aucune des données servies n'est sensible, et rien dans l'application ne pourrait fonder une restriction : il n'existe pas de système d'authentification en dehors du compte d'administration, donc pas d'identité à laquelle rattacher un droit de lecture. Réserver l'accès aux personnels de l'université est un contrôle d'hébergement — filtrage réseau ou authentification au reverse-proxy —, à énoncer comme tel au dossier RSSI. Les écritures, elles, restent gardées par la session d'administration, et les pages d'administration derrière une vérification de session.
- **Terminaison TLS par reverse-proxy** en frontal de l'application. Point d'ancrage de plusieurs corrections (chiffrement en transit, cookie `Secure`, en-têtes de sécurité, rate limiting réseau, cloisonnement) : à privilégier plutôt que de réimplémenter ces protections dans l'application.
- **Confiance dans les en-têtes de proxy : au serveur, pas dans l'application.** uvicorn embarque `ProxyHeadersMiddleware`, qui ne lit `X-Forwarded-For` que si le pair de la connexion figure dans `FORWARDED_ALLOW_IPS`, et qui remonte la liste des maillons de droite à gauche en écartant les proxys connus. L'application ne lit jamais l'en-tête : elle se contente de `request.client.host`, qu'uvicorn a déjà réécrit quand il y a lieu.
- **Mise à jour automatisée des dépendances** (Dependabot ou Renovate) sur les écosystèmes pip et npm, en complément des scans `pip-audit` / `npm audit` déjà bloquants au push. La détection existe ; la remédiation devient un flux de pull requests plutôt qu'une veille manuelle.
- **XSS Tooltip corrigé** hors de ce phasage (commit `b623d922`) : `Tooltip` rend son contenu en texte, `structsTooltip` produit du texte simple. Reste, en défense en profondeur, l'assainissement des titres et le second point d'injection HTML latent (phase dédiée ci-dessous).

## Phasage

### Fait

- [x] **XSS `Tooltip` sur `/publications/[id]`** — l'affiliation brute d'une source externe transitait par `{@html}`. `Tooltip` rend `{text}` (sauts de ligne en CSS `white-space: pre-line`), `structsTooltip` produit du texte. Test de non-régression sur `structsTooltip`. Commit `b623d922`.

### Phase 1 — Durcissement de l'API (code applicatif)

- [x] **Rate limiting du login** — limiteur applicatif à fenêtre fixe par IP sur `/api/auth/login` (`interfaces/api/rate_limit.py`, 10 tentatives / 5 min, 429 au-delà), sans dépendance externe. Le déni de service sur les lectures lourdes relève de la fréquence des requêtes, traité au reverse-proxy réseau (phase 3), pas d'un plafond par requête. Commit `5b2313df`.
- [x] **Clé du limiteur de connexion** — `_client_key` ne lit plus `X-Forwarded-For` : un en-tête forgé ouvrait un compteur neuf à chaque tentative, et derrière un proxy qui *ajoute* à l'en-tête (`$proxy_add_x_forwarded_for` chez nginx) son premier maillon est justement la valeur fournie par le client. La clé se réduit à `request.client.host`, qu'uvicorn réécrit lui-même quand le pair est déclaré de confiance. `FORWARDED_ALLOW_IPS` documentée dans `.env.example` et dans la documentation de déploiement, avec la conséquence d'un réglage absent : un compteur partagé par tous les clients. Test de non-régression sur la clé.
- [x] **CORS validé par les settings** — la liste des origines autorisées est un champ typé d'`infrastructure/settings.py`, découpé et validé au chargement plutôt que lu en brut depuis l'environnement au moment de poser le middleware. `*` y est refusé : combiné à `allow_credentials=True`, il conduit Starlette à renvoyer l'`Origin` de l'appelant, ce qui autorise n'importe quel site à appeler l'API avec le cookie de session de qui le visite. Le refus tombe au démarrage. Tests de non-régression sur le découpage et sur les deux formes du joker.
- [x] **Cookie de session `Secure`** — réglage `cookie_secure` (défaut vrai), desserré en HTTP local via `.env`. Commit `5b2469b5`.
- [x] **Docs OpenAPI privées** — réglage `expose_api_docs` (défaut faux) coupe `/docs`, `/redoc`, `/openapi.json` ; la génération du schéma frontend passe par `app.openapi()`. Commit `5b2469b5`.
- [x] **Révocabilité de session (globale)** — le jeton étant signé par `SESSION_SECRET`, en changer la valeur invalide tous les jetons émis : c'est la déconnexion globale, documentée dans `.env.example`. Suffisant pour l'unique compte admin actuel. La révocation fine (par session) via sessions à état se reposera à l'arrivée de plusieurs comptes.
- [x] **Credentials sources write-only** — `SECRET_CONFIG_KEYS` (`domain/config.py`) : la lecture masque la valeur (`value: null` + `is_set`), l'écriture reste ouverte. Frontend : ronds noirs si défini, `(non défini)` sinon, édition qui ne réécrit pas un secret laissé vide. Piste future non prioritaire : un bouton « Tester la connexion » par source (exerce la clé côté serveur, renvoie vert/rouge) comme équivalent sûr d'un affichage en clair.

### Phase 2 — En-têtes de sécurité et assainissement des sorties

- [x] **En-têtes de sécurité** — middleware FastAPI posant `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` (anti-clickjacking) et `Referrer-Policy` sur chaque réponse. HSTS reste au reverse-proxy TLS. Commit `1c0602bd`.
- [x] **Content-Security-Policy** — CSP native SvelteKit en mode hash, injectée en `<meta>` par page (`script-src 'self'` + empreinte du bootstrap inline, sans `unsafe-inline`). Vérifiée en local (Chrome headless, zéro violation) ; le bundle client ne fait ni `eval` ni Worker/WASM. `frame-ancestors` non exprimable en meta, couvert par `X-Frame-Options`. Commit `284c9b97`.
- [x] **Assainissement des titres par DOMPurify** — `sanitizeTitle` remplace son sanitiseur regex par DOMPurify (même liste blanche) ; dompurify déclaré en dépendance directe. Commit `7e17d9fa`.
- [x] **Point d'injection HTML latent `FacetDropdown`** — `{@html}` converti en rendu texte, comme `Tooltip`. Commit `279442a4`.
- [x] **Injection de formule dans les exports CSV** — titres, revues et éditeurs viennent de HAL et OpenAlex, où un tiers dépose le contenu qu'il veut, et une cellule qui commence par `=`, `+`, `-`, `@`, une tabulation ou un retour chariot est évaluée comme formule à l'ouverture dans un tableur. Les deux exports écrivent par un writer qui préfixe ces cellules d'une apostrophe : la cellule est marquée comme texte, la valeur reste entière. Les valeurs non textuelles traversent sans préfixe, qui ferait perdre le tri chronologique sur l'année et la somme sur les montants d'APC. Tests de non-régression sur les six amorces et sur le contournement par espace de tête.

### Phase 3 — Cloisonnement infrastructure (déploiement)

La DSI gère le conteneur et la machine virtuelle (isolation réseau, exposition des ports, cloisonnement de l'hôte) selon ses propres exigences. Ce volet se limite donc à ce qui vit dans le dépôt : l'image de référence, la connexion applicative et les défauts de configuration.

- [x] **Image de production non-root** — utilisateur `appuser` (uid 10001) et bascule `USER` dans le `Dockerfile` de production ; l'API ne tourne plus en root. Commit `09372bd0`. Les Dockerfile de dev restent en root (écriture via bind-mount, usage local uniquement).
- [x] **TLS vers la base** — réglage `db_sslmode` injecté dans la connexion (`infrastructure/db/engine.py`), réutilisé par Alembic. Commit `09372bd0`.
- [x] **Défauts de mot de passe compose** — `${...:-changeme}` remplacé par la forme fail-safe `${...:?}` : refus de démarrage sans secret explicite. Commit `731c18ee`.
- [x] **Rôle Postgres applicatif** — l'API se connecte sous une identité distincte (`DB_APP_USER`), limitée à la lecture et à l'écriture des données : ni structure du schéma, ni rafraîchissement de vue matérialisée, ni `TRUNCATE`, aucun de ces pouvoirs qu'elle n'exerce jamais. Migrations, pipeline et scripts de maintenance gardent l'identité principale, propriétaire du schéma. Le rôle et ses droits sont créés par `infrastructure/db/roles.sql`, joué à l'initialisation ; identité vide, l'API se connecte comme le reste, ce qui laisse un poste de développement inchangé. Le point qui comptait est acquis dans les deux cas : plus aucune connexion applicative en superutilisateur, donc plus de `COPY … PROGRAM` atteignable depuis l'application.
- [x] **Durcissement du conteneur applicatif** — `docker-compose.prod.yml` : privilèges figés (`no-new-privileges`, posé aussi sur la base), aucune capacité du noyau, racine en lecture seule avec `/tmp` en mémoire, plafonds de mémoire, de CPU et de processus, sonde de vie sur une route servie sans accès à la base, et port publié sur la loopback.
- [x] **Écritures sous racine en lecture seule** — la journalisation se rabat sur la sortie standard quand le fichier lui est refusé : une trace a un repli, et une destination indisponible n'est pas une raison d'empêcher le démarrage. Le stockage des payloads bruts, lui, porte de la donnée et ne se rabat sur rien : il vit dans un volume monté sur `/app/data`, dont le répertoire existe dans l'image et appartient à l'uid applicatif pour que le volume en hérite le propriétaire. C'est le seul emplacement du conteneur ouvert en écriture.
- [x] **Suppression du statut de run** — l'avancement du run en cours ne transite plus par un fichier : ni écriture par l'orchestrateur, ni endpoint de statut, ni bandeau de suivi sur la page d'administration, ni exception au contrat import-linter des routers. Un affichage à la seconde n'a pas de spectateur quand le pipeline tourne la nuit, et il ouvrait un emplacement en écriture sous racine en lecture seule. L'historique des runs, servi en base, porte seul le suivi ; la liste se recharge à l'ouverture de la page.
- Exposition réseau des ports, reverse-proxy et cloisonnement de l'hôte : ressort de la DSI. L'adresse du reverse-proxy lui est déclarée par `FORWARDED_ALLOW_IPS` (phase 1), sans quoi le limiteur de connexion ne distingue plus les clients.

### Phase 4 — Suivi dynamique dans le temps

- [x] **Mise à jour automatisée des dépendances** — `.github/dependabot.yml` : PR hebdomadaires sur pip (racine), npm (`interfaces/frontend`) et github-actions, mineures/correctives groupées par écosystème, majeures individuelles. Complète les scans `pip-audit` / `npm audit` bloquants au push.
- [x] **Blocage des secrets au push** — GitHub push protection activée : bloque côté serveur les secrets reconnus (motifs de fournisseurs) avant qu'ils n'atteignent le dépôt. Complément optionnel non retenu pour l'instant : gitleaks en pre-commit, qui ajoute la détection par entropie (secrets génériques : mot de passe DB, `SESSION_SECRET`) et un blocage local plus précoce.
- [x] **Alignement des postes de dev sur Node 22** — `interfaces/frontend/.nvmrc` fixe Node 22 (aligné sur la CI, `.github/workflows/ci.yml:88`) ; `nvm use` cale le poste dessus.

### Phase 5 — Coût des lectures ouvertes

La lecture reste ouverte (cf. Décisions) : ce qui subsiste n'est pas une question de confidentialité, mais de ressources. Une lecture que n'importe qui peut répéter doit coûter un montant borné.

- [x] **Lecture bornée du log de phase** — la lecture parcourt le fichier ligne à ligne et ne retient que la fin de la section demandée : la mémoire consommée tient au plafond de lignes, non à la taille du fichier. La troncature s'annonce, le nombre de lignes non rendues accompagnant l'extrait jusque dans la page.
- [x] **Plafond des exports CSV** — les deux exports s'arrêtent à 500 000 lignes, plafond posé en base par un `LIMIT` : la coupe précède le transfert, au lieu de matérialiser en mémoire un résultat sans borne. Les requêtes demandent une ligne de plus que le plafond, dont la présence révèle le dépassement sans compte séparé. Un export coupé le dit par une dernière ligne : il arrive par un lien de téléchargement, hors de toute page qui pourrait l'avertir, et un fichier incomplet qui se présente comme complet induit en erreur.
- [ ] **Fréquence des lectures coûteuses** — le limiteur de débit n'est posé que sur la connexion. Exports et agrégations s'appellent sans plafond de fréquence : le coût d'un appel est borné, celui d'une rafale ne l'est pas. Poser le limiteur existant sur les endpoints coûteux, ou traiter la fréquence au reverse-proxy.

## Questions ouvertes

- **Révocation de session** : passer à des sessions à état (table de sessions) ou conserver le jeton stateless avec une simple liste de révocation / rotation de secret ? Arbitrage simplicité vs granularité.
- **Périmètre du reverse-proxy** : fourni par la DSI dans leur infra d'hébergement, ou embarqué dans le déploiement de l'application ? Détermine qui porte la config TLS, rate limiting et en-têtes.
- **Où vivent les payloads bruts des sources ?** Le volume monté sur `/app/data` est ce qu'un système de fichiers en lecture seule réclame de plus simple. Une piste de fond, hors du périmètre de ce chantier : les conserver en base, dans les tables de staging, ce qui supprimerait le dernier emplacement en écriture du conteneur au prix d'un volume de TOAST considérable.

## Liens

- Index des chantiers : [0_INDEX.md](0_INDEX.md)
- Commit du correctif XSS : `b623d922`
