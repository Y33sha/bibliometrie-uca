<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "$lib/api";
  import type { components } from "$lib/api/schema";
  import RunDetail from "./RunDetail.svelte";
  import RunList from "./RunList.svelte";

  type RunSummary = components["schemas"]["RunSummary"];
  type RunDetailT = components["schemas"]["RunDetail"];

  const PAGE_SIZE = 50;

  let allPhases = $state<string[]>([]);
  let runs = $state<RunSummary[]>([]);
  let hasMore = $state(false);
  let loadingMore = $state(false);
  let selectedRunId = $state<number | null>(null);
  let runDetail = $state<RunDetailT | null>(null);
  let runLoading = $state(false);

  async function loadRuns() {
    const page = await api<RunSummary[]>(`/api/pipeline/runs?limit=${PAGE_SIZE}`);
    runs = page;
    hasMore = page.length === PAGE_SIZE;
    if (runs.length > 0 && selectedRunId === null) {
      await selectRun(runs[0].run_id);
    }
  }

  async function loadMore() {
    if (loadingMore || !hasMore) return;
    loadingMore = true;
    try {
      const page = await api<RunSummary[]>(
        `/api/pipeline/runs?limit=${PAGE_SIZE}&offset=${runs.length}`,
      );
      runs = [...runs, ...page];
      hasMore = page.length === PAGE_SIZE;
    } finally {
      loadingMore = false;
    }
  }

  async function selectRun(runId: number) {
    runLoading = true;
    selectedRunId = runId;
    try {
      runDetail = await api<RunDetailT>(`/api/pipeline/runs/${runId}`);
    } finally {
      runLoading = false;
    }
  }

  onMount(async () => {
    allPhases = await api<string[]>("/api/pipeline/phases");
    await loadRuns();
  });
</script>

<svelte:head><title>Pipeline — Bibliométrie UCA</title></svelte:head>

<div class="page-header">
  <h2>Pipeline</h2>
</div>

<div class="layout">
  <div class="col-list">
    <RunList
      {runs}
      {allPhases}
      {selectedRunId}
      onSelect={selectRun}
      {hasMore}
      {loadingMore}
      onLoadMore={loadMore}
    />
  </div>
  <div class="col-detail">
    {#if runLoading}
      <p class="empty">Chargement…</p>
    {:else if !runDetail}
      <p class="empty">Sélectionner un run dans la liste.</p>
    {:else}
      <RunDetail detail={runDetail} {allPhases} />
    {/if}
  </div>
</div>

<style>
  .page-header h2 {
    margin: 0 0 16px;
  }
  .layout {
    display: grid;
    grid-template-columns: 360px 1fr;
    gap: 20px;
    align-items: start;
  }
  .col-list {
    position: sticky;
    top: 1rem;
    max-height: calc(100vh - 2rem);
    overflow-y: auto;
    /* Gouttière pour que la scrollbar ne se superpose pas aux cartes de run. */
    padding-right: 8px;
    scrollbar-gutter: stable;
  }
  .col-detail {
    min-width: 0;
    padding: 16px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--card);
  }
  .empty {
    color: var(--muted);
    font-size: 0.9rem;
  }
</style>
