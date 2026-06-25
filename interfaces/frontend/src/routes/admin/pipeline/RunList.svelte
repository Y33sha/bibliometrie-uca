<script lang="ts">
  import type { components } from "$lib/api/schema";
  import PhaseRibbon from "./PhaseRibbon.svelte";
  import { CELL_COLOR, fmtDate, fmtDuration, STATUS_LABEL, type Status } from "./helpers";

  type RunSummary = components["schemas"]["RunSummary"];

  let {
    runs,
    allPhases,
    selectedRunId,
    onSelect,
  }: {
    runs: RunSummary[];
    allPhases: string[];
    selectedRunId: number | null;
    onSelect: (runId: number) => void;
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
  {/if}
</div>

<style>
  .run-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
    overflow-y: auto;
  }
  .run-item {
    display: flex;
    flex-direction: column;
    gap: 6px;
    width: 100%;
    text-align: left;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--card);
    cursor: pointer;
    font: inherit;
  }
  .run-item:hover {
    background: var(--hover);
  }
  .run-item.active {
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent);
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
    font-family: "JetBrains Mono", monospace;
    font-size: 0.85rem;
  }
  .run-date {
    color: var(--muted);
    font-size: 0.8rem;
    font-family: "JetBrains Mono", monospace;
  }
  .run-duration {
    margin-left: auto;
    font-size: 0.8rem;
    font-family: "JetBrains Mono", monospace;
  }
  .run-sub {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
    font-size: 0.78rem;
    color: var(--muted);
  }
  .ribbon-wrap {
    pointer-events: none;
  }
  .empty {
    color: var(--muted);
    font-size: 0.9rem;
  }
</style>
