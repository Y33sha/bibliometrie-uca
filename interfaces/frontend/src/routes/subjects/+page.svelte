<script lang="ts">
  import { onMount } from "svelte";
  import { base } from "$app/paths";
  import { api } from "$lib/api";
  import Pagination from "$lib/components/Pagination.svelte";
  import type { components } from "$lib/api/schema";

  type SubjectListItem = components["schemas"]["SubjectListItem"];
  type SubjectListResponse = components["schemas"]["SubjectListResponse"];

  // Libellés courts d'ontologies pour le badge.
  const ONTOLOGY_LABELS: Record<string, string> = {
    openalex_topic: "OpenAlex",
    openalex_keyword: "OpenAlex",
    hal_domain: "HAL",
    wos_subject: "WoS",
    wos_heading: "WoS",
    rameau: "RAMEAU",
    theses_discipline: "Thèse",
    scanr_domain: "ScanR",
  };

  const PER_PAGE = 50;

  let search = $state("");
  let minCount = $state(3);
  let page = $state(1);

  let data = $state<SubjectListResponse | null>(null);
  let loading = $state(false);
  let searchTimer: ReturnType<typeof setTimeout> | undefined;

  async function load() {
    loading = true;
    try {
      const params = new URLSearchParams();
      const q = search.trim();
      if (q) params.set("q", q);
      params.set("min_count", String(minCount));
      params.set("page", String(page));
      params.set("per_page", String(PER_PAGE));
      data = await api<SubjectListResponse>(`/api/subjects?${params}`);
    } finally {
      loading = false;
    }
  }

  function onSearchInput() {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      page = 1;
      load();
    }, 300);
  }

  function onMinCountChange() {
    page = 1;
    load();
  }

  function onPageChange(p: number) {
    page = p;
    load();
  }

  function isFree(s: SubjectListItem): boolean {
    return Object.keys(s.ontologies).length === 0;
  }

  function ontologiesLabel(s: SubjectListItem): string {
    const keys = Object.keys(s.ontologies);
    if (keys.length === 0) return "libre";
    const names = keys.map((k) => ONTOLOGY_LABELS[k] ?? k);
    // Dédoublonne (openalex_topic + openalex_keyword → "OpenAlex" une fois).
    return [...new Set(names)].join(", ");
  }

  const totalPages = $derived(data ? Math.max(1, Math.ceil(data.total / PER_PAGE)) : 1);

  onMount(load);
</script>

<svelte:head>
  <title>Sujets — Bibliométrie UCA</title>
</svelte:head>

<h1>Sujets</h1>
  <p class="hint">
    Liste de tous les sujets observés sur les publications, triés par nombre d'occurrences.
    Cliquer sur un sujet pour explorer ses voisins par co-occurrence.
  </p>

  <div class="filters">
    <input
      type="text"
      placeholder="Rechercher dans les libellés…"
      bind:value={search}
      oninput={onSearchInput}
    />
    <label>
      Occurrences min&nbsp;:
      <input type="number" min="1" bind:value={minCount} onchange={onMinCountChange} />
    </label>
  </div>

  {#if !data}
    <p class="loading">Chargement…</p>
  {:else}
    <p class="total" class:loading-overlay={loading}>
      {data.total.toLocaleString("fr-FR")} sujets
    </p>
    {#if data.items.length === 0}
      <p class="empty">Aucun sujet ne correspond à ces critères.</p>
    {:else}
      <table>
        <thead>
          <tr>
            <th>Libellé</th>
            <th>Type</th>
            <th class="right">Occurrences</th>
          </tr>
        </thead>
        <tbody>
          {#each data.items as s (s.id)}
            <tr>
              <td>
                <a href="{base}/subjects/{s.id}">{s.label}</a>
              </td>
              <td>
                <span class="badge" class:concept={!isFree(s)} class:free={isFree(s)}>
                  {ontologiesLabel(s)}
                </span>
              </td>
              <td class="right">{s.usage_count.toLocaleString("fr-FR")}</td>
            </tr>
          {/each}
        </tbody>
      </table>

      <Pagination page={data.page} pages={totalPages} onchange={onPageChange} />
    {/if}
  {/if}

<style>
  h1 {
    margin: 0 0 4px;
    font-size: 1.4rem;
  }
  .hint {
    margin: 0 0 16px;
    color: var(--muted, #6b7280);
    font-size: 0.9rem;
  }
  .filters {
    display: flex;
    gap: 16px;
    align-items: center;
    margin-bottom: 12px;
  }
  .filters input[type="text"] {
    padding: 6px 10px;
    border: 1px solid var(--border);
    border-radius: 4px;
    min-width: 320px;
  }
  .filters input[type="number"] {
    width: 70px;
    padding: 4px 8px;
    border: 1px solid var(--border);
    border-radius: 4px;
    margin-left: 4px;
  }
  .total {
    color: var(--muted, #6b7280);
    margin: 0 0 8px;
    font-size: 0.9rem;
  }
  .loading-overlay {
    opacity: 0.6;
  }
  .empty {
    color: var(--muted, #6b7280);
    font-style: italic;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    background: white;
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
  }
  th,
  td {
    padding: 8px 12px;
    text-align: left;
    border-bottom: 1px solid var(--border);
  }
  tr:last-child td {
    border-bottom: none;
  }
  th {
    font-weight: 600;
    background: var(--bg-muted, #f9fafb);
    font-size: 0.85rem;
  }
  td.right,
  th.right {
    text-align: right;
  }
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.8rem;
  }
  .badge.concept {
    background: #e0f2fe;
    color: #075985;
    border: 1px solid #bae6fd;
  }
  .badge.free {
    background: #fef3c7;
    color: #92400e;
    border: 1px solid #fde68a;
  }
  a {
    color: #075985;
    text-decoration: none;
  }
  a:hover {
    text-decoration: underline;
  }
  .loading {
    color: var(--muted, #6b7280);
  }
</style>
