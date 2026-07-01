<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { api } from "$lib/api";
  import type { components } from "$lib/api/schema";
  import RunDetail from "./RunDetail.svelte";
  import RunList from "./RunList.svelte";

  type PipelineStatus = components["schemas"]["PipelineStatus"];
  type RunSummary = components["schemas"]["RunSummary"];
  type RunDetailT = components["schemas"]["RunDetail"];

  let pipelineStatus = $state<PipelineStatus | null>(null);
  let statusTimer: ReturnType<typeof setTimeout> | null = null;
  let wasRunning = false;

  const PAGE_SIZE = 50;
  // Cadence de suivi : serrée tant qu'un run tourne (phase courante et
  // avancement à la seconde), relâchée à l'arrêt (rien à observer).
  const STATUS_POLL_RUNNING_MS = 1000;
  const STATUS_POLL_IDLE_MS = 10000;

  let allPhases = $state<string[]>([]);
  let runs = $state<RunSummary[]>([]);
  let hasMore = $state(false);
  let loadingMore = $state(false);
  let selectedRunId = $state<number | null>(null);
  let runDetail = $state<RunDetailT | null>(null);
  let runLoading = $state(false);

  async function pollStatus() {
    try {
      pipelineStatus = await api<PipelineStatus | null>("/api/admin/pipeline/status");
    } catch {
      pipelineStatus = null;
    }
    const running = pipelineStatus?.running ?? false;
    // Transition fin de run (naturelle, exception ou interruption) : le ruban
    // fraîchement enregistré n'apparaît qu'au rechargement de la liste.
    if (wasRunning && !running) {
      await loadRuns();
      if (selectedRunId !== null) await selectRun(selectedRunId);
    }
    wasRunning = running;
  }

  function scheduleStatus() {
    const delay = pipelineStatus?.running ? STATUS_POLL_RUNNING_MS : STATUS_POLL_IDLE_MS;
    statusTimer = setTimeout(async () => {
      await pollStatus();
      scheduleStatus();
    }, delay);
  }

  async function loadRuns() {
    const page = await api<RunSummary[]>(`/api/admin/pipeline/runs?limit=${PAGE_SIZE}`);
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
        `/api/admin/pipeline/runs?limit=${PAGE_SIZE}&offset=${runs.length}`,
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
      runDetail = await api<RunDetailT>(`/api/admin/pipeline/runs/${runId}`);
    } finally {
      runLoading = false;
    }
  }

  function elapsed(isoDate: string): string {
    const seconds = Math.floor((Date.now() - new Date(isoDate).getTime()) / 1000);
    if (seconds < 60) return `${seconds}s`;
    const m = Math.floor(seconds / 60);
    return `${m} min ${seconds % 60}s`;
  }

  onMount(async () => {
    await pollStatus();
    scheduleStatus();
    allPhases = await api<string[]>("/api/admin/pipeline/phases");
    await loadRuns();
  });

  onDestroy(() => {
    if (statusTimer) clearTimeout(statusTimer);
  });
</script>

<svelte:head><title>Pipeline — Bibliométrie UCA</title></svelte:head>

<div class="page-header">
  <h2>Pipeline</h2>
</div>

{#if pipelineStatus?.running}
  <div class="status-banner">
    <span class="status-dot"></span>
    Pipeline <strong>{pipelineStatus.mode}</strong> en cours — phase
    <strong>{pipelineStatus.phase}</strong>
    ({pipelineStatus.phases_done}/{pipelineStatus.phases_total}) — depuis
    {elapsed(pipelineStatus.started_at)}
  </div>
{/if}

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
  .status-banner {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    margin-bottom: 16px;
    background: #fff8e1;
    border: 1px solid #f0d98c;
    border-radius: 6px;
    font-size: 0.9rem;
  }
  .status-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #e6a700;
    animation: pulse 1.5s ease-in-out infinite;
  }
  @keyframes pulse {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.3;
    }
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
