<script lang="ts">
  import "#lib/styles/shared.css";
  import "katex/dist/katex.min.css";
  import "@flaticon/flaticon-uicons/css/regular/rounded.css";
  import { page } from "$app/state";
  import { goto, afterNavigate } from "$app/navigation";
  import { asset, resolve } from "$app/paths";
  import type { Snippet } from "svelte";
  import { auth } from "#lib/api/index.js";
  import DialogHost from "#lib/components/DialogHost.svelte";
  import { loadInstitution, siteTitle } from "#lib/institution.svelte.js";
  import { isAdmin, loadSession, loginUrl, session } from "#lib/session.svelte.js";
  import { loadSources } from "#lib/sources.svelte.js";

  let { children }: { children: Snippet } = $props();

  loadInstitution();
  loadSources();
  loadSession();

  const isAdminSection = $derived(isActive("/admin"));
  const isHalProblems = $derived(isActive("/hal-problems"));
  const isPublicReferentiels = $derived(isActive("/theses") || isActive("/publishers") || isActive("/journals") || isActive("/monographs") || isActive("/subjects"));

  let mobileNavOpen = $state(false);
  type NavMenu = "referentiels" | "hal-problems" | "admin" | "account";
  // Un seul sous-menu est ouvert à la fois. Un sous-menu ouvert au survol se referme quand la souris le quitte ; un sous-menu ouvert au clic reste ouvert.
  let openMenu = $state<NavMenu | null>(null);
  let openedByHover = false;
  // Délai d'ouverture au survol : un passage rapide de la souris n'ouvre pas le sous-menu.
  const HOVER_OPEN_DELAY_MS = 250;
  let hoverTimer: ReturnType<typeof setTimeout> | undefined;

  // Referme le menu mobile et le sous-menu ouvert après chaque navigation.
  afterNavigate(() => {
    mobileNavOpen = false;
    setOpenMenu(null);
  });

  function setOpenMenu(menu: NavMenu | null, byHover = false) {
    clearTimeout(hoverTimer);
    openMenu = menu;
    openedByHover = byHover;
  }

  function toggleMenu(menu: NavMenu) {
    setOpenMenu(openMenu === menu ? null : menu);
  }

  function openOnHover(e: PointerEvent, menu: NavMenu) {
    if (e.pointerType !== "mouse" || openMenu === menu) return;
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => setOpenMenu(menu, true), HOVER_OPEN_DELAY_MS);
  }
  function closeOnHoverLeave(e: PointerEvent, menu: NavMenu) {
    if (e.pointerType !== "mouse") return;
    clearTimeout(hoverTimer);
    if (openMenu === menu && openedByHover) setOpenMenu(null);
  }

  // Un sous-menu se referme quand le focus le quitte, sur Échap (le focus revient à son bouton) et sur un clic hors des sous-menus.
  function closeOnFocusLeave(e: FocusEvent, menu: NavMenu) {
    if (openMenu === menu && !(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node | null)) setOpenMenu(null);
  }
  function closeOnEscape(e: KeyboardEvent) {
    if (e.key !== "Escape" || !openMenu) return;
    document.getElementById(`nav-button-${openMenu}`)?.focus();
    openMenu = null;
  }
  function closeOnClickOutside(e: MouseEvent) {
    if (openMenu && !(e.target as Element).closest(".nav-dropdown")) openMenu = null;
  }

  // Compare l'identifiant de la route courante, sans le préfixe de déploiement.
  function isActive(routeId: string): boolean {
    const current = page.route.id ?? "";
    if (current === routeId) return true;
    if (routeId !== "/" && current.startsWith(routeId + "/")) return true;
    return false;
  }

  // Après la déconnexion, une page d'administration cède la place à la page Statistiques ; toute autre page reste affichée.
  async function logout() {
    await auth.logout();
    if (isAdminSection) await goto(resolve("stats"));
    await loadSession(true);
  }
</script>

<svelte:window onkeydown={closeOnEscape} onclick={closeOnClickOutside} />

<!-- Sous-menu de la navigation : ouvert et fermé au clic ou au clavier, ouvert au survol prolongé de la souris. -->
{#snippet dropdown(menu: NavMenu, label: Snippet, items: Snippet, { active = false, right = false, switchLink = false } = {})}
  <div class="nav-dropdown" class:active role="none" onfocusout={(e) => closeOnFocusLeave(e, menu)} onpointerenter={(e) => openOnHover(e, menu)} onpointerleave={(e) => closeOnHoverLeave(e, menu)}>
    <button id="nav-button-{menu}" class="nav-link" class:active class:nav-switch-link={switchLink} aria-expanded={openMenu === menu} aria-controls="nav-menu-{menu}" onclick={() => toggleMenu(menu)}>{@render label()} <span class="chevron" aria-hidden="true"></span></button>
    <div id="nav-menu-{menu}" class="nav-dropdown-menu" class:nav-dropdown-menu-right={right} class:open={openMenu === menu}>
      {@render items()}
    </div>
  </div>
{/snippet}

{#snippet referentielsLabel()}Référentiels{/snippet}
{#snippet referentielsItems()}
  <a href={resolve('theses')} class:active={isActive("/theses")}>Thèses</a>
  <a href={resolve('publishers')} class:active={isActive("/publishers")}>Éditeurs</a>
  <a href={resolve('journals')} class:active={isActive("/journals")}>Publications en série</a>
  <a href={resolve('monographs')} class:active={isActive("/monographs")}>Monographies</a>
  <a href={resolve('subjects')} class:active={isActive("/subjects")}>Sujets</a>
{/snippet}
{#snippet halProblemsLabel()}Problèmes HAL{/snippet}
{#snippet halProblemsItems()}
  <a href={resolve('hal-problems/duplicate-accounts')} class:active={isActive("/hal-problems/duplicate-accounts")}>Comptes auteur en double</a>
  <a href={resolve('hal-problems/duplicate-publications')} class:active={isActive("/hal-problems/duplicate-publications")}>Dépôts en double</a>
  <a href={resolve('hal-problems/missing-collections')} class:active={isActive("/hal-problems/missing-collections")}>Publications absentes des collections</a>
  <a href={resolve('hal-problems/affiliation-conflicts')} class:active={isActive("/hal-problems/affiliation-conflicts")}>Affiliations divergentes</a>
{/snippet}
{#snippet adminLabel()}Administration{/snippet}
{#snippet adminItems()}
  <a href={resolve('admin/config')} class:active={isActive("/admin/config")}>Configuration</a>
  <a href={resolve('admin/pipeline')} class:active={isActive("/admin/pipeline")}>Pipeline</a>
  <span class="nav-dropdown-group">Adresses</span>
  <a href={resolve('admin/addresses')} class:active={isActive("/admin/addresses")}>Affiliations</a>
  <a href={resolve('admin/countries')} class:active={isActive("/admin/countries")}>Pays</a>
{/snippet}
{#snippet accountLabel()}<i class="fi fi-rr-user nav-icon" aria-hidden="true"></i>{session.login}{/snippet}
{#snippet accountItems()}
  <button class="nav-dropdown-action" onclick={logout}>Déconnexion</button>
{/snippet}

<a class="skip-link" href="#contenu">Aller au contenu</a>

<header class="site-header" class:admin={isAdmin()}>
  <div class="site-brand">
    <img src={asset(isAdmin() ? "connectome.svg" : "favicon-menu.svg")} alt="" class="site-icon" />
    <span class="site-title">{siteTitle()}</span>
  </div>
  <nav id="site-nav" class="site-nav" class:open={mobileNavOpen} aria-label="Navigation principale">
    <a href={resolve('stats')} class="nav-link" class:active={isActive("/stats")}><i class="fi fi-rr-chart-histogram nav-icon" aria-hidden="true"></i>Stats</a>
    <a href={resolve('publications')} class="nav-link" class:active={isActive("/publications")}><i class="fi fi-rr-book-open-cover nav-icon" aria-hidden="true"></i>Publications</a>
    <a href={resolve('structures')} class="nav-link" class:active={isActive("/structures")}><i class="fi fi-rr-school nav-icon" aria-hidden="true"></i>Labos</a>
    <a href={resolve('persons')} class="nav-link" class:active={isActive("/persons")}><i class="fi fi-rr-users nav-icon" aria-hidden="true"></i>Chercheurs</a>
    {@render dropdown("referentiels", referentielsLabel, referentielsItems, { active: isPublicReferentiels })}
    {@render dropdown("hal-problems", halProblemsLabel, halProblemsItems, { active: isHalProblems, right: true })}
    {#if isAdmin()}
      {@render dropdown("admin", adminLabel, adminItems, { active: isAdminSection, right: true })}
    {/if}
    {#if session.login}
      {@render dropdown("account", accountLabel, accountItems, { right: true, switchLink: true })}
    {:else if session.loaded && !isActive("/login")}
      <a href={loginUrl(page.url)} class="nav-link nav-switch-link">Connexion</a>
    {/if}
  </nav>
  <button class="nav-toggle" aria-label="Menu" aria-expanded={mobileNavOpen} aria-controls="site-nav" onclick={() => (mobileNavOpen = !mobileNavOpen)}>&#9776;</button>
</header>

<main id="contenu" class="container" tabindex="-1">
  <!-- Une page se monte une fois la session lue, pour un identifiant et un rôle : ses fonctions d'administration et ses filtres par défaut dépendent du rôle. Naviguer vers un autre identifiant de la même route, ou changer de rôle, la remonte avec ses chargements au montage. -->
  {#if session.loaded}
    {#key `${page.params.id}|${isAdmin()}`}
      {@render children()}
    {/key}
  {/if}
</main>

<DialogHost />

<style>
  :global(html) {
    font-size: var(--fs-base);
  }
  :global(body) {
    margin: 0;
    font-family: var(--font);
    font-variant-numeric: tabular-nums;
    font-size: var(--fs-base);
    line-height: 1.5;
    color: var(--text);
    background: var(--bg);
  }
  :global(*, *::before, *::after) {
    box-sizing: border-box;
  }
  /* Socle uniforme des champs `type="search"` (sémantique correcte, et évite que les gestionnaires de mots de passe les prennent pour des champs de connexion). On retire l'apparence native du navigateur — forme « pilule », bouton d'effacement — et on reproduit le champ texte standard de l'application. `:where()` donne une spécificité nulle : ce socle s'applique aux barres de recherche nues sans écraser les champs volontairement stylés (inputs de fusion thémés, recherche du composant Picker). */
  :global(:where(input[type="search"])) {
    appearance: none;
    -webkit-appearance: none;
    padding: 6px 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--card);
    font-family: inherit;
    font-size: var(--fs-md);
    color: inherit;
  }
  :global(:where(input[type="search"]):focus) {
    outline: none;
    border-color: var(--accent-mid);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent-mid) 20%, transparent);
  }
  :global(input[type="search"]::-webkit-search-cancel-button) {
    -webkit-appearance: none;
    appearance: none;
  }
  .site-brand {
    display: flex;
    align-items: center;
  }
  .site-icon {
    height: 32px;
    width: auto;
    margin-right: 10px;
  }
  /* Couleurs de la barre en variables : la session admin les redéfinit (barre claire, repère du mode d'administration). */
  .site-header {
    --nav-bg: var(--nav-public);
    --nav-menu-bg: var(--nav-public-menu);
    --nav-fg: white;
    --nav-fg-soft: rgba(255, 255, 255, 0.85);
    --nav-hover: rgba(255, 255, 255, 0.1);
    --nav-active: rgba(255, 255, 255, 0.14);
    --nav-rule: rgba(255, 255, 255, 0.15);
    background: var(--nav-bg);
    color: var(--nav-fg);
    padding: 0 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: var(--header-height);
    position: sticky;
    top: 0;
    /* Au-dessus des dropdowns de page (facettes, filtres d'entité… tous à z-index 100) : la navigation globale reste toujours visible, y compris quand un panneau déployé recouvre la zone d'en-tête sur un viewport scrollable. Les surcouches modales (dialogues, tooltips, lightbox) restent volontairement au-dessus (z-index ≥ 1000). */
    z-index: 300;
  }
  .site-header.admin {
    --nav-bg: var(--nav-admin);
    --nav-menu-bg: var(--nav-admin-menu);
    --nav-fg: var(--accent);
    --nav-fg-soft: var(--accent);
    --nav-hover: color-mix(in srgb, var(--accent) 8%, transparent);
    --nav-active: color-mix(in srgb, var(--accent) 14%, transparent);
    --nav-rule: color-mix(in srgb, var(--accent) 20%, transparent);
    box-shadow: inset 0 -1px 0 var(--nav-rule);
  }
  .nav-toggle {
    display: none;
    background: none;
    border: none;
    color: inherit;
    font-size: var(--fs-2xl);
    line-height: 1;
    cursor: pointer;
    padding: 0 6px;
    height: var(--header-height);
  }
  .site-title {
    white-space: nowrap;
    font-family: var(--font-brand);
    font-size: var(--fs-lg);
    font-weight: 500;
    margin: 0;
  }
  .site-nav {
    display: flex;
    align-items: center;
    gap: 2px;
    height: 100%;
  }
  /* Rubrique : pastille arrondie, fond plus clair pour la rubrique active. */
  .nav-link {
    white-space: nowrap;
    color: var(--nav-fg-soft);
    text-decoration: none;
    font-size: var(--fs-md);
    font-weight: 500;
    padding: 0 12px;
    height: 34px;
    display: flex;
    align-items: center;
    border: none;
    border-radius: var(--radius);
    background: none;
    cursor: pointer;
    font-family: inherit;
    transition: background 0.15s, color 0.15s;
  }
  .nav-link:hover {
    color: var(--nav-fg);
    background: var(--nav-hover);
  }
  .nav-icon {
    display: inline-flex;
    margin-right: 7px;
    font-size: var(--fs-sm);
  }
  .nav-link.active,
  .nav-dropdown.active > .nav-link {
    color: var(--nav-fg);
    background: var(--nav-active);
  }
  .nav-switch-link {
    color: var(--nav-fg-soft);
    font-size: var(--fs-sm);
    margin-left: 12px;
  }
  .nav-switch-link:hover {
    color: var(--nav-fg);
  }
  .nav-dropdown {
    position: relative;
    height: 100%;
    display: flex;
    align-items: center;
  }
  .nav-dropdown-menu.open {
    display: block;
  }
  .nav-link[aria-expanded="true"] .chevron {
    transform: rotate(180deg);
  }
  .nav-dropdown-menu {
    display: none;
    position: absolute;
    top: 100%;
    left: 0;
    padding: 4px 0;
    background: var(--nav-menu-bg);
    border-radius: 0 0 var(--radius) var(--radius);
    min-width: 170px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    z-index: 100;
  }
  .nav-dropdown-menu a {
    display: block;
    white-space: nowrap;
    padding: 8px 16px;
    color: var(--nav-fg-soft);
    text-decoration: none;
    font-size: var(--fs-md);
  }
  .nav-dropdown-menu a:hover {
    background: var(--nav-hover);
    color: var(--nav-fg);
  }
  .nav-dropdown-menu a.active {
    color: var(--nav-fg);
    font-weight: 600;
  }
  .nav-dropdown-menu-right {
    left: auto;
    right: 0;
  }
  .nav-dropdown-group {
    display: block;
    padding: 8px 16px 2px;
    color: var(--nav-fg-soft);
    font-size: var(--fs-xs);
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
  }
  /* Une rubrique qui suit des entrées en est séparée par un filet. */
  .nav-dropdown-group:not(:first-child) {
    margin-top: 6px;
    padding-top: 10px;
    border-top: 1px solid var(--nav-rule);
  }
  .nav-dropdown-action {
    display: block;
    width: 100%;
    padding: 8px 16px;
    border: none;
    background: none;
    color: var(--nav-fg-soft);
    font-family: inherit;
    font-size: var(--fs-md);
    text-align: left;
    cursor: pointer;
  }
  .nav-dropdown-action:hover {
    background: var(--nav-hover);
    color: var(--nav-fg);
  }

  .container {
    max-width: 1400px;
    margin: 0 auto;
    padding: 24px var(--page-gutter);
  }
  /* Cible du lien d'évitement : le focus s'y pose sans contour, la zone n'étant pas un contrôle. */
  .container:focus {
    outline: none;
  }
  /* Lien d'évitement : hors de l'écran, affiché à la prise de focus. */
  .skip-link {
    position: absolute;
    top: -100px;
    left: 8px;
    z-index: 1000;
    padding: 8px 14px;
    background: var(--card);
    color: var(--accent);
    font-weight: 600;
    border-radius: var(--radius);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
  }
  .skip-link:focus {
    top: 8px;
  }

  /* ── Largeur intermédiaire : rubriques sans icône, plus serrées, pour tenir sur une ligne ── */
  @media (max-width: 1100px) {
    .nav-icon {
      display: none;
    }
    .nav-link {
      padding: 0 9px;
    }
  }

  /* ── Responsive : hamburger + menu vertical sous 940px ── */
  @media (max-width: 940px) {
    .nav-toggle {
      display: flex;
      align-items: center;
    }
    .site-nav {
      display: none;
      position: absolute;
      top: var(--header-height);
      left: 0;
      right: 0;
      flex-direction: column;
      align-items: stretch;
      height: auto;
      padding: 4px 0;
      background: var(--nav-bg);
      box-shadow: 0 6px 14px rgba(0, 0, 0, 0.25);
      z-index: 200;
    }
    .site-nav.open {
      display: flex;
      /* Sur écran court, le menu déplié peut dépasser le bas du viewport : on borne sa hauteur et on le rend défilable pour atteindre le bas. */
      max-height: calc(100vh - var(--header-height));
      overflow-y: auto;
    }
    .nav-link {
      height: auto;
      width: 100%;
      padding: 11px 22px;
      border-radius: 0;
    }
    .nav-dropdown {
      height: auto;
      flex-direction: column;
      align-items: stretch;
    }
    /* Sur mobile, les sous-menus sont toujours dépliés (pas de survol). */
    .nav-dropdown-menu {
      display: block;
      position: static;
      box-shadow: none;
      border-radius: 0;
      min-width: 0;
    }
    .nav-dropdown-menu a,
    .nav-dropdown-action {
      padding-left: 38px;
    }
    .nav-dropdown-group {
      padding-left: 30px;
    }
    .nav-switch-link {
      margin-left: 0;
      border-top: 1px solid var(--nav-rule);
    }
  }
</style>
