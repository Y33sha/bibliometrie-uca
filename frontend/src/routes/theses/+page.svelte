<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/stores";
  import { base } from "$app/paths";
  import { sanitizeTitle, halDocUrl, scanrPubUrl } from "$lib/utils";
  import FacetDropdown from "$lib/components/FacetDropdown.svelte";
  import SourceFilterToggle from "$lib/components/SourceFilterToggle.svelte";
  import Pagination from "$lib/components/Pagination.svelte";
  import { usePaginatedFetch } from "$lib/composables/usePaginatedFetch.svelte";
  import { useFacets } from "$lib/composables/useFacets.svelte";
  import { useUrlFilters } from "$lib/composables/useUrlFilters.svelte";

  interface Thesis {
    id: number;
    title: string;
    pub_year: number | null;
    doi: string | null;
    doc_type: string | null;
    labs: string | null;
    lab_items: { id: number; label: string }[] | null;
    hal_id: string | null;
    openalex_id: string | null;
    scanr_id: string | null;
    theses_id: string | null;
    oa_status: string | null;
    date_soutenance: string | null;
    date_inscription: string | null;
  }

  let search = $state("");
  let currentSort = $state("soutenance_desc");
  let selectedYears: string[] = $state([]);
  let selectedLabs: string[] = $state([]);
  let selectedStatus: string[] = $state([]);
  let selectedAccess: string[] = $state([]);
  let sourceStates: Record<string, 'all' | 'yes' | 'no'> = $state({});

  function buildFilterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (selectedYears.length) params.set("year", selectedYears.join(","));
    if (selectedLabs.length) params.set("lab_id", selectedLabs.join(","));
    if (selectedStatus.length) {
      params.set("doc_type", selectedStatus.join(","));
    } else {
      params.set("doc_type", "thesis,ongoing_thesis");
    }
    const q = search.trim();
    if (q) params.set("search", q);
    if (selectedAccess.length) params.set("access", selectedAccess.join(","));
    const sf = Object.entries(sourceStates).filter(([, v]) => v === 'yes' || v === 'no').map(([k, v]) => `${k}_${v}`).join(',');
    if (sf) params.set("source_filter", sf);
    params.set("sort", currentSort);
    return params;
  }

  const pubs = usePaginatedFetch<Thesis>({
    endpoint: "/api/publications",
    itemsKey: "publications",
    perPage: 100,
    apiKey: "theses-list",
    buildParams: buildFilterParams,
  });

  const facets = useFacets({
    endpoint: "/api/publications/facets",
    apiKey: "theses-facets",
    buildParams: buildFilterParams,
    sourceCountsKey: 'source_counts',
    facets: {
      years: { type: "simple", apiKey: "years" },
      labs: { type: "labeled", apiKey: "labs" },
      access: { type: "passthrough", apiKey: "access" },
      status: {
        type: "label_map",
        apiKey: "doc_types",
        labels: { thesis: "Soutenues", ongoing_thesis: "En cours" },
      },
    },
    afterLoad(_data, options) {
      options.labs = [{ value: "none", text: "— Aucun labo —", count: (_data.no_lab_count as number) ?? 0 }, ...options.labs];
      options.status = options.status.filter((f) => f.value === "thesis" || f.value === "ongoing_thesis");
    },
  });

  const url = useUrlFilters({
    basePath: "/theses",
    filters: {
      selectedYears: { type: "string_array", urlKey: "year" },
      selectedLabs: { type: "string_array", urlKey: "lab_id" },
      selectedStatus: { type: "string_array", urlKey: "status" },
      selectedAccess: { type: "string_array", urlKey: "access" },
      sourceStates: { type: "source_states", urlKey: "source_filter" },
      search: { type: "single", urlKey: "search" },
      currentSort: { type: "single", urlKey: "sort", defaultValue: "soutenance_desc" },
      currentPage: { type: "page", urlKey: "page" },
    },
  });

  function syncUrl() {
    url.syncUrl(() => ({
      selectedYears,
      selectedLabs,
      selectedStatus,
      selectedAccess,
      sourceStates,
      search,
      currentSort,
      currentPage: pubs.page,
    }));
  }

  function onFilterChange() {
    pubs.page = 1;
    syncUrl();
    pubs.load();
    facets.load();
  }

  function onLabChange(newSelection: string[]) {
    const hadNone = selectedLabs.includes("none");
    const hasNone = newSelection.includes("none");
    if (hasNone && !hadNone) selectedLabs = ["none"];
    else if (hasNone && newSelection.length > 1) selectedLabs = newSelection.filter((v: string) => v !== "none");
    else selectedLabs = newSelection;
    onFilterChange();
  }

  const onSearchInput = url.debouncedSearch(() => {
    pubs.page = 1;
    syncUrl();
    pubs.load();
  });

  function toggleSort(asc: string, desc: string) {
    currentSort = currentSort === desc ? asc : desc;
    onFilterChange();
  }

  const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];

  function formatDate(iso: string | null): { month: string; year: string } | null {
    if (!iso) return null;
    const [y, m] = iso.split('-');
    return { month: MONTHS[parseInt(m, 10) - 1] || '', year: y };
  }

  function sortArrow(asc: string, desc: string): string {
    return currentSort === asc ? '↑' : currentSort === desc ? '↓' : '';
  }
  function sortActive(asc: string, desc: string): boolean {
    return currentSort === asc || currentSort === desc;
  }

  const soutArrow = $derived(sortArrow("soutenance_asc", "soutenance_desc"));
  const soutActive = $derived(sortActive("soutenance_asc", "soutenance_desc"));
  const inscrArrow = $derived(sortArrow("inscription_asc", "inscription_desc"));
  const inscrActive = $derived(sortActive("inscription_asc", "inscription_desc"));
  const titleSortArrow = $derived(sortArrow("title", "title_desc"));
  const titleSortActive = $derived(sortActive("title", "title_desc"));

  onMount(async () => {
    const restored = url.restoreFromUrl($page.url.searchParams);
    if (restored.selectedYears) selectedYears = restored.selectedYears as string[];
    if (restored.selectedLabs) selectedLabs = restored.selectedLabs as string[];
    if (restored.selectedStatus) selectedStatus = restored.selectedStatus as string[];
    if (restored.selectedAccess) selectedAccess = restored.selectedAccess as string[];
    if (restored.sourceStates) sourceStates = restored.sourceStates as Record<string, 'all' | 'yes' | 'no'>;
    if (restored.search) search = restored.search as string;
    if (restored.currentSort) currentSort = restored.currentSort as string;
    if (restored.currentPage) pubs.page = restored.currentPage as number;

    await facets.load();
    pubs.load();
  });
</script>

<svelte:head><title>Thèses — Bibliométrie UCA</title></svelte:head>

<div class="page-header">
  <h2>Thèses</h2>
  <span class="result-count">{pubs.total} résultats</span>
</div>

<div class="toolbar">
  <input
    type="search"
    placeholder="Rechercher par titre..."
    bind:value={search}
    oninput={onSearchInput}
    onkeydown={(e: KeyboardEvent) => {
      if (e.key === "Enter") {
        e.preventDefault();
        onFilterChange();
      }
    }}
  />

  <div class="facets">
    <FacetDropdown label="Année" options={facets.options.years} bind:selected={selectedYears} onchange={() => onFilterChange()} />
    <FacetDropdown label="Laboratoire" options={facets.options.labs} bind:selected={selectedLabs} onchange={(v: string[]) => onLabChange(v)} />
    <FacetDropdown label="Statut" options={facets.options.status} bind:selected={selectedStatus} onchange={() => onFilterChange()} />
    <FacetDropdown label="Accès" options={facets.options.access} bind:selected={selectedAccess} onchange={() => onFilterChange()} />
    <SourceFilterToggle
      sources={[
        { key: 'theses', label: 'theses.fr' },
        { key: 'hal', label: 'HAL' },
        { key: 'oa', label: 'OpenAlex' },
        { key: 'scanr', label: 'ScanR' },
      ]}
      bind:states={sourceStates} counts={facets.sourceCounts} onchange={() => onFilterChange()} />
  </div>
</div>

<table class="data-table">
  <thead>
    <tr>
      <th class="col-date sortable" class:active={inscrActive} onclick={() => toggleSort('inscription_asc', 'inscription_desc')}>Inscription {inscrArrow}</th>
      <th class="col-date sortable" class:active={soutActive} onclick={() => toggleSort('soutenance_asc', 'soutenance_desc')}>Soutenance {soutArrow}</th>
      <th class="col-title sortable" class:active={titleSortActive} onclick={() => toggleSort('title', 'title_desc')}>Titre {titleSortArrow}</th>
      <th class="col-status">Statut</th>
      <th class="col-labs">Laboratoire(s)</th>
      <th class="col-oa">OA</th>
      <th class="col-link">Sources</th>
    </tr>
  </thead>
  <tbody>
    {#each pubs.items as pub (pub.id)}
      <tr>
        <td class="col-date">{@html (() => { const d = formatDate(pub.date_inscription); return d ? `<span class="date-month">${d.month}</span> ${d.year}` : ''; })()}</td>
        <td class="col-date">{@html (() => { const d = formatDate(pub.date_soutenance); return d ? `<span class="date-month">${d.month}</span> ${d.year}` : ''; })()}</td>
        <td class="col-title">
          <a href="{base}/publications/{pub.id}">{@html sanitizeTitle(pub.title)}</a>
        </td>
        <td class="col-status">
          <span class="status-badge" class:soutenue={pub.doc_type === "thesis"} class:en-cours={pub.doc_type === "ongoing_thesis"}>
            {pub.doc_type === "thesis" ? "Soutenue" : pub.doc_type === "ongoing_thesis" ? "En cours" : ""}
          </span>
        </td>
        <td class="col-labs">
          {#each pub.lab_items || [] as lab}
            <a href="{base}/laboratories/{lab.id}" class="lab-tag">{lab.label}</a>
          {/each}
        </td>
        <td class="oa-lock-cell">
          {#if pub.doc_type === 'ongoing_thesis'}
            <span class="oa-lock-badge oa-lock-ongoing">
              <img src="{base}/hourglass.svg" alt="En cours" class="oa-lock" title="Thèse en cours" />
              <span class="oa-lock-label">en cours</span>
            </span>
          {:else if pub.oa_status && !['unknown', 'closed'].includes(pub.oa_status)}
            <span class="oa-lock-badge oa-lock-open">
              <img src="{base}/lock-open.svg" alt="Open Access" class="oa-lock" title="Open Access ({pub.oa_status})" />
              <span class="oa-lock-label">ouvert</span>
            </span>
          {:else}
            <span class="oa-lock-badge oa-lock-closed">
              <img src="{base}/lock-closed.svg" alt="Closed" class="oa-lock" title="Accès fermé" />
              <span class="oa-lock-label">fermé</span>
            </span>
          {/if}
        </td>
        <td class="links-cell">
          {#if pub.theses_id}
            <a href="https://theses.fr/{pub.theses_id}" target="_blank" rel="noopener" class="source-tag source-theses" title="theses.fr: {pub.theses_id}">
              <img src="https://theses.fr/favicon.ico" alt="theses.fr" />
            </a>
          {:else}
            <span class="source-tag source-placeholder"></span>
          {/if}
          {#if pub.hal_id}
            <a href={halDocUrl(pub.hal_id)} target="_blank" rel="noopener" class="source-tag source-hal" title="HAL: {pub.hal_id}">
              <img src="https://hal.science/favicon.ico" alt="HAL" />
            </a>
          {:else}
            <span class="source-tag source-placeholder"></span>
          {/if}
          {#if pub.openalex_id}
            <a href="https://openalex.org/{pub.openalex_id}" target="_blank" rel="noopener" class="source-tag source-oa" title="OpenAlex: {pub.openalex_id}">
              <img src="https://raw.githubusercontent.com/ourresearch/openalex-gui/refs/heads/master/public/favicon.png" alt="OA" />
            </a>
          {:else}
            <span class="source-tag source-placeholder"></span>
          {/if}
          {#if pub.scanr_id}
            <a href={scanrPubUrl(pub.scanr_id)} target="_blank" rel="noopener" class="source-tag source-scanr" title="ScanR: {pub.scanr_id}">
              <img src="{base}/scanr-icon.svg" alt="ScanR" />
            </a>
          {:else}
            <span class="source-tag source-placeholder"></span>
          {/if}
        </td>
      </tr>
    {/each}
  </tbody>
</table>

<Pagination
  page={pubs.page}
  pages={pubs.pages}
  onchange={(p: number) => {
    pubs.page = p;
    syncUrl();
    pubs.load();
  }}
/>

<style>
  .page-header {
    display: flex;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 8px;
  }
  .page-header h2 {
    margin: 0;
    font-size: 1.2rem;
  }
  .result-count {
    font-size: 0.85rem;
    color: var(--muted);
  }

  .toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
    position: sticky;
    top: 46px;
    background: var(--bg);
    padding: 6px 0;
  }
  .toolbar input[type="search"] {
    width: 280px;
    padding: 5px 10px;
    font-size: 0.9rem;
    font-family: inherit;
    border: 1px solid var(--border);
    border-radius: 4px;
  }
  .facets {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }

  .data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }
  .data-table th {
    text-align: left;
    padding: 6px 8px;
    border-bottom: 2px solid var(--border);
    font-size: 0.8rem;
    color: var(--muted);
    text-transform: uppercase;
  }
  .data-table td {
    padding: 5px 8px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }
  .data-table tbody tr:hover {
    background: var(--hover);
  }

  .col-date {
    width: 85px;
    text-align: center;
    font-size: 0.85rem;
    white-space: nowrap;
  }
  .col-date :global(.date-month) {
    font-size: 0.75rem;
    color: var(--muted);
  }
  .col-title {
    min-width: 300px;
  }
  .col-title a {
    color: var(--accent);
    text-decoration: none;
  }
  .col-title a:hover {
    text-decoration: underline;
  }
  .col-status {
    width: 90px;
    text-align: center;
  }
  .col-labs {
    width: 180px;
  }
  .col-oa {
    width: 75px;
  }
  .col-link {
    width: 120px;
    text-align: center;
  }

  .sortable {
    cursor: pointer;
    user-select: none;
  }
  .sortable.active {
    color: var(--accent);
  }

  .status-badge {
    font-size: 0.75rem;
    padding: 2px 6px;
    border-radius: 8px;
  }
  .status-badge.soutenue {
    background: #e8f5e9;
    color: #2e7d32;
  }
  .status-badge.en-cours {
    background: #fff3e0;
    color: #e65100;
  }
</style>
