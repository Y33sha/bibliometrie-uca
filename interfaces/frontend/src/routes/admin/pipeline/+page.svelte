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
  let statusInterval: ReturnType<typeof setInterval> | null = null;

  let allPhases = $state<string[]>([]);
  let runs = $state<RunSummary[]>([]);
  let selectedRunId = $state<number | null>(null);
  let runDetail = $state<RunDetailT | null>(null);
  let runLoading = $state(false);

  let logsLoaded = $state(false);
  let logsContent = $state("");

  async function pollStatus() {
    try {
      pipelineStatus = await api<PipelineStatus | null>("/api/admin/pipeline/status");
    } catch {
      pipelineStatus = null;
    }
  }

  async function loadRuns() {
    runs = await api<RunSummary[]>("/api/admin/pipeline/runs?limit=100");
    if (runs.length > 0 && selectedRunId === null) {
      await selectRun(runs[0].run_id);
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

  async function onLogsToggle(event: Event) {
    const el = event.currentTarget as HTMLDetailsElement;
    if (el.open && !logsLoaded) {
      logsLoaded = true;
      const r = await api<{ content: string }>("/api/admin/pipeline/logs?lines=200");
      logsContent = r.content;
    }
  }

  function elapsed(isoDate: string): string {
    const seconds = Math.floor((Date.now() - new Date(isoDate).getTime()) / 1000);
    if (seconds < 60) return `${seconds}s`;
    const m = Math.floor(seconds / 60);
    return `${m} min ${seconds % 60}s`;
  }

  onMount(async () => {
    pollStatus();
    statusInterval = setInterval(pollStatus, 10000);
    allPhases = await api<string[]>("/api/admin/pipeline/phases");
    await loadRuns();
  });

  onDestroy(() => {
    if (statusInterval) clearInterval(statusInterval);
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
    <RunList {runs} {allPhases} {selectedRunId} onSelect={selectRun} />
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

<details class="logs" ontoggle={onLogsToggle}>
  <summary>Logs (cron.log)</summary>
  {#if logsContent}
    <pre class="log-block">{logsContent}</pre>
  {:else}
    <p class="empty">Aucun log.</p>
  {/if}
</details>

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
  .col-detail {
    min-width: 0;
    padding: 16px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--card);
  }
  .logs {
    margin-top: 20px;
    border: 1px solid var(--border);
    border-radius: 6px;
  }
  .logs summary {
    padding: 8px 12px;
    cursor: pointer;
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--muted);
  }
  .log-block {
    margin: 0;
    padding: 10px 12px;
    border-top: 1px solid var(--border);
    background: var(--bg);
    font-family: "JetBrains Mono", monospace;
    font-size: 0.75rem;
    line-height: 1.5;
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 400px;
    overflow-y: auto;
  }
  .empty {
    color: var(--muted);
    font-size: 0.9rem;
  }
</style>
