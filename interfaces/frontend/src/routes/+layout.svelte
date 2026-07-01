<script lang="ts">
  import "$lib/styles/shared.css";
  import "katex/dist/katex.min.css";
  import { page } from "$app/stores";
  import { goto, afterNavigate } from "$app/navigation";
  import { base } from "$app/paths";
  import type { Snippet } from "svelte";
  import { auth } from "$lib/api";
  import DialogHost from "$lib/components/DialogHost.svelte";

  let { children }: { children: Snippet } = $props();

  const isAdmin = $derived($page.url.pathname.startsWith(base + "/admin"));
  const isPipeline = $derived($page.url.pathname === base + "/admin/pipeline" || $page.url.pathname === base + "/admin/config");
  const isAddresses = $derived($page.url.pathname === base + "/admin/addresses" || $page.url.pathname === base + "/admin/feedback" || $page.url.pathname === base + "/admin/countries");
  const isReferentiels = $derived(
    isActive("/admin/structures") ||
      isActive("/admin/persons") ||
      isActive("/admin/publishers") ||
      isActive("/admin/journals"),
  );
  const isDuplicates = $derived($page.url.pathname === base + "/admin/duplicates");
  const isHalProblems = $derived($page.url.pathname.startsWith(base + "/hal-problems"));
  const isPublicReferentiels = $derived(
    isActive("/publishers") || isActive("/journals") || isActive("/subjects"),
  );

  let mobileNavOpen = $state(false);
  // Referme le menu mobile après chaque navigation.
  afterNavigate(() => {
    mobileNavOpen = false;
  });

  function isActive(path: string): boolean {
    const current = $page.url.pathname;
    const full = base + path;
    if (current === full) return true;
    if (path !== "/" && current.startsWith(full + "/")) return true;
    return false;
  }

  async function logout() {
    await auth.logout();
    goto(base + "/login");
  }
</script>

<div class="site-header" class:admin={isAdmin}>
  {#if isAdmin}
    <div class="site-brand">
      <img src="{base}/connectome.png" alt="" class="site-icon" />
      <h1 class="site-title">
        Bibliométrie UCA <span class="site-title-admin">Admin</span>
      </h1>
    </div>
    <nav class="site-nav" class:open={mobileNavOpen}>
      <div class="nav-dropdown" role="navigation" class:active={isPipeline}>
        <button class="nav-link" class:active={isPipeline}>Pipeline &#x25BE;</button>
        <div class="nav-dropdown-menu">
          <a href="{base}/admin/config" class:active={isActive("/admin/config")}>Config</a>
          <a href="{base}/admin/pipeline" class:active={isActive("/admin/pipeline")}>Logs</a>
        </div>
      </div>
      <div class="nav-dropdown" role="navigation" class:active={isReferentiels}>
        <button class="nav-link" class:active={isReferentiels}>Référentiels &#x25BE;</button>
        <div class="nav-dropdown-menu">
          <a href="{base}/admin/structures" class:active={isActive("/admin/structures")}>Structures</a>
          <a href="{base}/admin/persons" class:active={isActive("/admin/persons")}>Personnes</a>
          <a href="{base}/admin/publishers" class:active={isActive("/admin/publishers")}>Éditeurs</a>
          <a href="{base}/admin/journals" class:active={isActive("/admin/journals")}>Revues</a>
        </div>
      </div>
      <div class="nav-dropdown" role="navigation" class:active={isAddresses}>
        <button class="nav-link" class:active={isAddresses}>Adresses &#x25BE;</button>
        <div class="nav-dropdown-menu">
          <a href="{base}/admin/addresses" class:active={isActive("/admin/addresses")}>Affiliations</a>
          <a href="{base}/admin/countries" class:active={isActive("/admin/countries")}>Pays</a>
        </div>
      </div>
      <a href="{base}/admin/duplicates" class="nav-link" class:active={isDuplicates}
        >Dédoublonnage</a
      >
      <a href="{base}/stats" class="nav-link nav-switch-link">Public</a>
      <button class="nav-link nav-switch-link" onclick={logout}>Déconnexion</button>
    </nav>
  {:else}
    <div class="site-brand">
      <img src="{base}/favicon.png" alt="" class="site-icon" />
      <h1 class="site-title">Bibliométrie UCA</h1>
    </div>
    <nav class="site-nav" class:open={mobileNavOpen}>
      <a href="{base}/stats" class="nav-link" class:active={isActive("/stats")}>Statistiques</a>
      <a href="{base}/publications" class="nav-link" class:active={isActive("/publications")}>Publications</a>
      <a href="{base}/theses" class="nav-link" class:active={isActive("/theses")}>Thèses</a>
      <a href="{base}/laboratories" class="nav-link" class:active={isActive("/laboratories")}>Laboratoires</a>
      <a href="{base}/persons" class="nav-link" class:active={isActive("/persons")}>Personnes</a>
      <div class="nav-dropdown" role="navigation" class:active={isPublicReferentiels}>
        <button class="nav-link" class:active={isPublicReferentiels}>Référentiels &#x25BE;</button>
        <div class="nav-dropdown-menu">
          <a href="{base}/publishers" class:active={isActive("/publishers")}>Éditeurs</a>
          <a href="{base}/journals" class:active={isActive("/journals")}>Revues</a>
          <a href="{base}/subjects" class:active={isActive("/subjects")}>Sujets</a>
        </div>
      </div>
      <div class="nav-dropdown" role="navigation" class:active={isHalProblems}>
        <button class="nav-link" class:active={isHalProblems}>Problèmes HAL &#x25BE;</button>
        <div class="nav-dropdown-menu">
          <a href="{base}/hal-problems/duplicate-accounts" class:active={isActive("/hal-problems/duplicate-accounts")}>Doublons auteurs</a>
          <a href="{base}/hal-problems/duplicate-pubs" class:active={isActive("/hal-problems/duplicate-pubs")}>Doublons publis</a>
          <a href="{base}/hal-problems/missing-collections" class:active={isActive("/hal-problems/missing-collections")}>Manques collections</a>
          <a href="{base}/hal-problems/affiliation-conflicts" class:active={isActive("/hal-problems/affiliation-conflicts")}>Affiliations suspectes</a>
        </div>
      </div>
      <a href="{base}/docs" class="nav-link nav-help-link" title="Documentation" class:active={isActive("/docs")}
        ><svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
          ><circle cx="12" cy="12" r="10" /><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg
        ></a
      >
      <a href="{base}/admin/pipeline" class="nav-link nav-switch-link">Admin</a>
    </nav>
  {/if}
  <button
    class="nav-toggle"
    aria-label="Menu"
    aria-expanded={mobileNavOpen}
    onclick={() => (mobileNavOpen = !mobileNavOpen)}>&#9776;</button>
</div>

<div class="container">
  {@render children()}
</div>

<DialogHost />

<style>
  :global(html) {
    font-size: 16px;
  }
  :global(body) {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 1rem;
    line-height: 1.5;
    color: var(--text);
    background: var(--bg);
  }
  :global(:root) {
    --bg: #f8f7f4;
    --card: #ffffff;
    --text: #2c2c2c;
    --muted: #6b7280;
    --accent: #3b6b9e;
    --border: #e5e5e0;
    --hover: #efede6; /* fond de survol des éléments cliquables (lignes, items de liste) */
    --gold: #d4a017;
    --diamond: #0288a8;
    --hybrid: #8e6bbf;
    --bronze: #b8733e;
    --green: #2a7d4f;
    --open: #4caf50; /* vert « accès ouvert » (indicateur générique), plus clair que la voie green */
    --embargoed: #b08900;
    --closed: #555;
    --unknown: #bbb;
    --header-height: 46px; /* hauteur du menu supérieur fixe (sticky top:0) */
  }
  :global(*, *::before, *::after) {
    box-sizing: border-box;
  }
  /* Socle uniforme des champs `type="search"` (sémantique correcte, et évite que
     les gestionnaires de mots de passe les prennent pour des champs de connexion).
     On retire l'apparence native du navigateur — forme « pilule », bouton
     d'effacement — et on reproduit le champ texte standard de l'application.
     `:where()` donne une spécificité nulle : ce socle s'applique aux barres de
     recherche nues sans écraser les champs volontairement stylés (inputs de
     fusion thémés, recherche du composant Picker). */
  :global(:where(input[type="search"])) {
    appearance: none;
    -webkit-appearance: none;
    padding: 6px 10px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: white;
    font-family: inherit;
    font-size: 0.95rem;
    color: inherit;
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
    background: #5b9ea0;
    color: white;
    padding: 0 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: var(--header-height);
    position: sticky;
    top: 0;
    z-index: 100;
  }
  .site-header.admin {
    background: #3d7a7c;
  }
  .site-header.admin .nav-dropdown-menu {
    background: #4d8a8c;
  }
  .nav-toggle {
    display: none;
    background: none;
    border: none;
    color: white;
    font-size: 1.5rem;
    line-height: 1;
    cursor: pointer;
    padding: 0 6px;
    height: 46px;
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
    color: rgba(255, 255, 255, 0.5);
    margin-left: 6px;
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  .site-nav {
    display: flex;
    align-items: center;
    gap: 0;
    height: 100%;
  }
  .nav-link {
    color: rgba(255, 255, 255, 0.7);
    text-decoration: none;
    font-size: 0.95rem;
    padding: 0 14px;
    height: 46px;
    display: flex;
    align-items: center;
    border: none;
    background: none;
    cursor: pointer;
    font-family: inherit;
    transition: color 0.15s;
  }
  .nav-link:hover {
    color: white;
  }
  .nav-link.active {
    color: white;
    box-shadow: inset 0 -2px 0 white;
  }
  .nav-switch-link {
    color: rgba(255, 255, 255, 0.4);
    font-size: 0.85rem;
    margin-left: 12px;
    border-left: 1px solid rgba(255, 255, 255, 0.15);
  }
  .nav-switch-link:hover {
    color: rgba(255, 255, 255, 0.7);
  }
  .nav-help-link {
    color: rgba(255, 255, 255, 0.4);
    padding: 0 10px;
    margin-right: 4px;
  }
  .nav-help-link:hover {
    color: white;
  }
  .nav-help-link.active {
    color: white;
    box-shadow: none;
  }
  .nav-dropdown {
    position: relative;
    height: 46px;
    display: flex;
    align-items: center;
  }
  .nav-dropdown.active > .nav-link {
    color: white;
    box-shadow: inset 0 -2px 0 white;
  }
  .nav-dropdown:hover > .nav-dropdown-menu {
    display: block;
  }
  .nav-dropdown-menu {
    display: none;
    position: absolute;
    top: 46px;
    left: 0;
    background: #4a8c8e;
    border-radius: 0 0 5px 5px;
    min-width: 150px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    z-index: 100;
  }
  .nav-dropdown-menu a {
    display: block;
    padding: 9px 16px;
    color: rgba(255, 255, 255, 0.8);
    text-decoration: none;
    font-size: 0.95rem;
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
      top: 46px;
      left: 0;
      right: 0;
      flex-direction: column;
      align-items: stretch;
      height: auto;
      padding: 4px 0;
      background: #5b9ea0;
      box-shadow: 0 6px 14px rgba(0, 0, 0, 0.25);
      z-index: 200;
    }
    .site-header.admin .site-nav {
      background: #3d7a7c;
    }
    .site-nav.open {
      display: flex;
      /* Sur écran court, le menu déplié peut dépasser le bas du viewport :
         on borne sa hauteur et on le rend défilable pour atteindre le bas. */
      max-height: calc(100vh - var(--header-height));
      overflow-y: auto;
    }
    .nav-link {
      height: auto;
      width: 100%;
      padding: 11px 22px;
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
      border-left: none;
      border-top: 1px solid rgba(255, 255, 255, 0.15);
    }
  }
</style>
