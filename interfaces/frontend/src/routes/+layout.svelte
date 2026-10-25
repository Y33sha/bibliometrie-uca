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
  import { loadSources } from "#lib/sources.svelte.js";

  let { children }: { children: Snippet } = $props();

  loadInstitution();
  loadSources();

  const isAdmin = $derived(isActive("/admin"));
  const isPipeline = $derived(page.route.id === "/admin/pipeline" || page.route.id === "/admin/config");
  const isAddresses = $derived(page.route.id === "/admin/addresses" || page.route.id === "/admin/feedback" || page.route.id === "/admin/countries");
  const isReferentiels = $derived(isActive("/admin/structures") || isActive("/admin/persons") || isActive("/admin/publications") || isActive("/admin/publishers") || isActive("/admin/serials") || isActive("/admin/monographs"));
  const isHalProblems = $derived(isActive("/hal-problems"));
  const isPublicReferentiels = $derived(isActive("/theses") || isActive("/publishers") || isActive("/journals") || isActive("/monographs") || isActive("/subjects"));

  let mobileNavOpen = $state(false);
  // Referme le menu mobile après chaque navigation.
  afterNavigate(() => {
    mobileNavOpen = false;
  });

  // Compare l'identifiant de la route courante, sans le préfixe de déploiement.
  function isActive(routeId: string): boolean {
    const current = page.route.id ?? "";
    if (current === routeId) return true;
    if (routeId !== "/" && current.startsWith(routeId + "/")) return true;
    return false;
  }

  async function logout() {
    await auth.logout();
    goto(resolve('login'));
  }
</script>

<div class="site-header" class:admin={isAdmin}>
  {#if isAdmin}
    <div class="site-brand">
      <img src={asset('connectome.png')} alt="" class="site-icon" />
      <h1 class="site-title">
        {siteTitle()} <span class="site-title-admin">Admin</span>
      </h1>
    </div>
    <nav class="site-nav" class:open={mobileNavOpen}>
      <div class="nav-dropdown" role="navigation" class:active={isPipeline}>
        <button class="nav-link" class:active={isPipeline}>Pipeline &#x25BE;</button>
        <div class="nav-dropdown-menu">
          <a href={resolve('admin/config')} class:active={isActive("/admin/config")}>Config</a>
          <a href={resolve('admin/pipeline')} class:active={isActive("/admin/pipeline")}>Logs</a>
        </div>
      </div>
      <div class="nav-dropdown" role="navigation" class:active={isReferentiels}>
        <button class="nav-link" class:active={isReferentiels}>Référentiels &#x25BE;</button>
        <div class="nav-dropdown-menu">
          <a href={resolve('admin/structures')} class:active={isActive("/admin/structures")}>Structures</a>
          <a href={resolve('admin/persons')} class:active={isActive("/admin/persons")}>Personnes</a>
          <a href={resolve('admin/publications')} class:active={isActive("/admin/publications")}>Publications</a>
          <a href={resolve('admin/publishers')} class:active={isActive("/admin/publishers")}>Éditeurs</a>
          <a href={resolve('admin/serials')} class:active={isActive("/admin/serials")}>Publications en série</a>
          <a href={resolve('admin/monographs')} class:active={isActive("/admin/monographs")}>Monographies</a>
        </div>
      </div>
      <div class="nav-dropdown" role="navigation" class:active={isAddresses}>
        <button class="nav-link" class:active={isAddresses}>Adresses &#x25BE;</button>
        <div class="nav-dropdown-menu">
          <a href={resolve('admin/addresses')} class:active={isActive("/admin/addresses")}>Affiliations</a>
          <a href={resolve('admin/countries')} class:active={isActive("/admin/countries")}>Pays</a>
        </div>
      </div>
      <a href={resolve('stats')} class="nav-link nav-switch-link">Public</a>
      <button class="nav-link nav-switch-link" onclick={logout}>Déconnexion</button>
    </nav>
  {:else}
    <div class="site-brand">
      <img src={asset('favicon.png')} alt="" class="site-icon" />
      <h1 class="site-title">{siteTitle()}</h1>
    </div>
    <nav class="site-nav" class:open={mobileNavOpen}>
      <a href={resolve('stats')} class="nav-link" class:active={isActive("/stats")}><i class="fi fi-rr-chart-histogram nav-icon" aria-hidden="true"></i>Stats</a>
      <a href={resolve('publications')} class="nav-link" class:active={isActive("/publications")}><i class="fi fi-rr-book-open-cover nav-icon" aria-hidden="true"></i>Publications</a>
      <a href={resolve('laboratories')} class="nav-link" class:active={isActive("/laboratories")}><i class="fi fi-rr-school nav-icon" aria-hidden="true"></i>Labos</a>
      <a href={resolve('persons')} class="nav-link" class:active={isActive("/persons")}><i class="fi fi-rr-users nav-icon" aria-hidden="true"></i>Chercheurs</a>
      <div class="nav-dropdown" role="navigation" class:active={isPublicReferentiels}>
        <button class="nav-link" class:active={isPublicReferentiels}>Référentiels &#x25BE;</button>
        <div class="nav-dropdown-menu">
          <a href={resolve('theses')} class:active={isActive("/theses")}>Thèses</a>
          <a href={resolve('publishers')} class:active={isActive("/publishers")}>Éditeurs</a>
          <a href={resolve('journals')} class:active={isActive("/journals")}>Revues</a>
          <a href={resolve('monographs')} class:active={isActive("/monographs")}>Monographies</a>
          <a href={resolve('subjects')} class:active={isActive("/subjects")}>Sujets</a>
        </div>
      </div>
      <div class="nav-dropdown" role="navigation" class:active={isHalProblems}>
        <button class="nav-link" class:active={isHalProblems}>Problèmes HAL &#x25BE;</button>
        <div class="nav-dropdown-menu">
          <a href={resolve('hal-problems/duplicate-accounts')} class:active={isActive("/hal-problems/duplicate-accounts")}>Doublons auteurs</a>
          <a href={resolve('hal-problems/duplicate-publications')} class:active={isActive("/hal-problems/duplicate-publications")}>Doublons publis</a>
          <a href={resolve('hal-problems/missing-collections')} class:active={isActive("/hal-problems/missing-collections")}>Manques collections</a>
          <a href={resolve('hal-problems/affiliation-conflicts')} class:active={isActive("/hal-problems/affiliation-conflicts")}>Affiliations suspectes</a>
        </div>
      </div>
      <a href={resolve('admin/pipeline')} class="nav-link nav-switch-link">Admin</a>
    </nav>
  {/if}
  <button class="nav-toggle" aria-label="Menu" aria-expanded={mobileNavOpen} onclick={() => (mobileNavOpen = !mobileNavOpen)}>&#9776;</button>
</div>

<div class="container">
  <!-- Une page de détail se monte pour un identifiant : naviguer vers un autre identifiant de la même route la remonte, avec ses chargements au montage. -->
  {#key page.params.id}
    {@render children()}
  {/key}
</div>

<DialogHost />

<style>
  :global(html) {
    font-size: 16px;
  }
  :global(body) {
    margin: 0;
    font-family: var(--font);
    font-variant-numeric: tabular-nums;
    font-size: 1rem;
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
    font-size: 0.95rem;
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
    height: 30px;
    width: auto;
    margin-right: 10px;
  }
  .site-header {
    background: var(--nav-public);
    color: white;
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
    background: var(--nav-admin);
  }
  .site-header.admin .nav-dropdown-menu {
    background: var(--nav-admin-menu);
  }
  .nav-toggle {
    display: none;
    background: none;
    border: none;
    color: inherit;
    font-size: 1.5rem;
    line-height: 1;
    cursor: pointer;
    padding: 0 6px;
    height: var(--header-height);
  }
  .site-title {
    font-family: "Ubuntu", sans-serif;
    font-size: 1.15rem;
    font-weight: 500;
    margin: 0;
  }
  .site-title-admin {
    font-size: 0.8rem;
    font-weight: 400;
    color: rgba(255, 255, 255, 0.6);
    margin-left: 6px;
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  .site-nav {
    display: flex;
    align-items: center;
    gap: 2px;
    height: 100%;
  }
  /* Rubrique : pastille arrondie, fond plus clair pour la rubrique active. */
  .nav-link {
    color: rgba(255, 255, 255, 0.85);
    text-decoration: none;
    font-size: 0.92rem;
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
    color: white;
    background: rgba(255, 255, 255, 0.1);
  }
  .nav-icon {
    display: inline-flex;
    margin-right: 7px;
    font-size: 0.9em;
  }
  .nav-link.active,
  .nav-dropdown.active > .nav-link {
    color: white;
    background: rgba(255, 255, 255, 0.18);
  }
  .nav-switch-link {
    color: rgba(255, 255, 255, 0.6);
    font-size: 0.85rem;
    margin-left: 12px;
  }
  .nav-switch-link:hover {
    color: white;
  }
  .nav-dropdown {
    position: relative;
    height: 100%;
    display: flex;
    align-items: center;
  }
  .nav-dropdown:hover > .nav-dropdown-menu {
    display: block;
  }
  .nav-dropdown-menu {
    display: none;
    position: absolute;
    top: 100%;
    left: 0;
    padding: 4px 0;
    background: var(--nav-public-menu);
    border-radius: 0 0 var(--radius) var(--radius);
    min-width: 170px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    z-index: 100;
  }
  .nav-dropdown-menu a {
    display: block;
    padding: 8px 16px;
    color: rgba(255, 255, 255, 0.85);
    text-decoration: none;
    font-size: 0.92rem;
  }
  .nav-dropdown-menu a:hover {
    background: rgba(255, 255, 255, 0.1);
    color: white;
  }
  .nav-dropdown-menu a.active {
    color: white;
    font-weight: 600;
  }

  .container {
    max-width: 1400px;
    margin: 0 auto;
    padding: 24px;
  }

  /* ── Responsive : hamburger + menu vertical sous 860px ── */
  @media (max-width: 860px) {
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
      background: var(--nav-public);
      box-shadow: 0 6px 14px rgba(0, 0, 0, 0.25);
      z-index: 200;
    }
    .site-header.admin .site-nav {
      background: var(--nav-admin);
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
    .nav-dropdown-menu a {
      padding-left: 38px;
    }
    .nav-switch-link {
      margin-left: 0;
      border-top: 1px solid rgba(255, 255, 255, 0.15);
    }
  }
</style>
