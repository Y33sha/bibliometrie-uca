<script lang="ts">
  import type { components } from "#lib/api/schema.js";
  import PhaseRibbon from "./PhaseRibbon.svelte";
  import { CELL_COLOR, fmtDate, fmtDuration, STATUS_LABEL, type Status } from "./helpers";

  type RunSummary = components["schemas"]["RunSummary"];

  let {
    runs,
    allPhases,
    selectedRunId,
    onSelect,
    hasMore,
    loadingMore,
    onLoadMore,
  }: {
    runs: RunSummary[];
    allPhases: string[];
    selectedRunId: number | null;
    onSelect: (runId: number) => void;
    hasMore: boolean;
    loadingMore: boolean;
    onLoadMore: () => void;
  } = $props();

  function statusMap(run: RunSummary): Record<string, Status> {
    const map: Record<string, Status> = {};
    for (const p of run.phases) map[p.phase] = p.status;
    return map;
  }
</script>

<div class="run-list">
  {#if runs.length === 0}
    <p class="empty">Aucun run enregistré.</p>
  {:else}
    {#each runs as run (run.run_id)}
      <button
        class="run-item"
        class:active={selectedRunId === run.run_id}
        onclick={() => onSelect(run.run_id)}
      >
        <div class="run-head">
          <span
            class="dot"
            style="background:{CELL_COLOR[run.status as Status]}"
            title={STATUS_LABEL[run.status as Status]}
          ></span>
          <span class="run-id">#{run.run_id}</span>
          <span class="run-date">{fmtDate(run.started_at)}</span>
          <span class="run-duration">{fmtDuration(run.total_duration_s)}</span>
        </div>
        <div class="run-sub">
          <span>{run.mode}</span>
          {#if run.sources.length}
            <span>· {run.sources.length} source{run.sources.length > 1 ? "s" : ""}</span>
          {/if}
          <span>· {run.phase_count} phase{run.phase_count > 1 ? "s" : ""}</span>
        </div>
        <div class="ribbon-wrap">
          <PhaseRibbon {allPhases} statuses={statusMap(run)} />
        </div>
      </button>
    {/each}
    {#if hasMore}
      <button class="load-more" onclick={onLoadMore} disabled={loadingMore}>
        {loadingMore ? "Chargement…" : "Charger les runs plus anciens"}
      </button>
    {/if}
  {/if}
</div>

<style>
  .run-list {
    display: flex;
    flex-direction: column;
  }
  .load-more {
    padding: 8px 12px;
    margin-top: 8px;
    border: 1px dashed var(--border);
    border-radius: var(--radius);
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font: inherit;
    font-size: var(--fs-sm);
  }
  .load-more:hover:not(:disabled) {
    background: var(--hover);
    color: inherit;
  }
  .load-more:disabled {
    cursor: default;
    opacity: 0.6;
  }
  .run-item {
    display: flex;
    flex-direction: column;
    gap: 6px;
    width: 100%;
    text-align: left;
    padding: 10px 12px;
    border: none;
    border-bottom: 1px solid var(--border);
    border-left: 3px solid transparent;
    background: none;
    cursor: pointer;
    font: inherit;
  }
  .run-item:hover {
    background: var(--hover);
  }
  .run-item.active {
    border-left-color: var(--accent);
    background: var(--accent-light);
  }
  .run-head {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex: none;
  }
  .run-id {
    font-weight: 600;
    font-family: var(--mono);
    font-size: var(--fs-sm);
  }
  .run-date {
    color: var(--muted);
    font-size: var(--fs-sm);
    font-family: var(--mono);
  }
  .run-duration {
    margin-left: auto;
    font-size: var(--fs-sm);
    font-family: var(--mono);
  }
  .run-sub {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
    font-size: var(--fs-sm);
    color: var(--muted);
  }
  .ribbon-wrap {
    pointer-events: none;
  }
  .empty {
    color: var(--muted);
    font-size: var(--fs-md);
  }
</style>
