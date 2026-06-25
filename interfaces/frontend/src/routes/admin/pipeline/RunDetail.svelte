<script lang="ts">
  import type { components } from "$lib/api/schema";
  import PhaseRibbon from "./PhaseRibbon.svelte";
  import {
    CELL_COLOR,
    fmtDate,
    fmtDuration,
    fmtRatio,
    isSlow,
    STATUS_LABEL,
    type Status,
  } from "./helpers";

  type RunDetail = components["schemas"]["RunDetail"];
  type PhaseExecutionDetail = components["schemas"]["PhaseExecutionDetail"];

  let { detail, allPhases }: { detail: RunDetail; allPhases: string[] } = $props();

  let expanded = $state<string | null>(null);
  function toggle(phase: string) {
    expanded = expanded === phase ? null : phase;
  }

  const statuses = $derived.by(() => {
    const map: Record<string, Status> = {};
    for (const p of detail.phases) map[p.phase] = p.status;
    return map;
  });

  function metricsSummary(m: PhaseExecutionDetail["metrics"]): string {
    const parts: string[] = [];
    if (m.new) parts.push(`${m.new} new`);
    if (m.updated) parts.push(`${m.updated} updated`);
    if (m.unchanged) parts.push(`${m.unchanged} unchanged`);
    if (m.errors) parts.push(`${m.errors} errors`);
    for (const [k, v] of Object.entries(m.extras ?? {})) if (v) parts.push(`${v} ${k}`);
    return parts.join(", ") || "—";
  }

  function volumes(v: { [key: string]: number } | null): [string, number][] {
    return v ? Object.entries(v) : [];
  }
</script>

<div class="run-meta">
  <div class="meta-row">
    <span class="meta-label">Run</span>
    <span class="meta-value">
      #{detail.run_id}
      <span class="dot" style="background:{CELL_COLOR[detail.status as Status]}"></span>
      {STATUS_LABEL[detail.status as Status]}
    </span>
  </div>
  <div class="meta-row">
    <span class="meta-label">Mode · sources</span>
    <span class="meta-value">{detail.mode} · {detail.sources.join(", ") || "—"}</span>
  </div>
  <div class="meta-row">
    <span class="meta-label">Début</span>
    <span class="meta-value">{fmtDate(detail.started_at)}</span>
  </div>
  <div class="meta-row">
    <span class="meta-label">Durée totale</span>
    <span class="meta-value">{fmtDuration(detail.total_duration_s)}</span>
  </div>
</div>

<div class="ribbon-block">
  <PhaseRibbon {allPhases} {statuses} />
</div>

<table class="phase-table">
  <thead>
    <tr>
      <th>Phase</th>
      <th>Statut</th>
      <th class="num">Durée</th>
      <th class="num">Signaux</th>
    </tr>
  </thead>
  <tbody>
    {#each detail.phases as p (p.phase)}
      <tr
        class="phase-row"
        class:slow={isSlow(p.duration_ratio)}
        class:open={expanded === p.phase}
        onclick={() => toggle(p.phase)}
      >
        <td class="ph-name">{p.phase}</td>
        <td>
          <span class="dot" style="background:{CELL_COLOR[p.status as Status]}"></span>
          {STATUS_LABEL[p.status as Status]}
        </td>
        <td
          class="num"
          title={p.historical_median_duration_s !== null
            ? `médian ${fmtDuration(p.historical_median_duration_s)}`
            : "pas d'historique"}
        >
          {fmtDuration(p.duration_s)}{#if isSlow(p.duration_ratio)}<span class="slow-flag" title="nettement plus lent que le médian"> ⚠</span>{/if}
        </td>
        <td class="num">{p.signals.length || "—"}</td>
      </tr>
      {#if expanded === p.phase}
        <tr class="expand-row">
          <td colspan="4">
            <div class="expand">
              <div class="expand-line"><span class="k">Métriques</span><span>{metricsSummary(p.metrics)}</span></div>
              {#if p.historical_median_duration_s !== null}
                <div class="expand-line">
                  <span class="k">Durée vs médian</span>
                  <span>{fmtDuration(p.duration_s)} / {fmtDuration(p.historical_median_duration_s)} (×{fmtRatio(p.duration_ratio)})</span>
                </div>
              {/if}
              {#if volumes(p.input).length}
                <div class="expand-line">
                  <span class="k">Entrée</span>
                  <span>{#each volumes(p.input) as [t, n], i}{i > 0 ? " · " : ""}{t} {n}{/each}</span>
                </div>
              {/if}
              {#if volumes(p.output).length}
                <div class="expand-line">
                  <span class="k">Sortie</span>
                  <span>{#each volumes(p.output) as [t, n], i}{i > 0 ? " · " : ""}{t} {n}{/each}</span>
                </div>
              {/if}
              {#if p.signals.length}
                <div class="expand-line">
                  <span class="k">Signaux</span>
                  <span class="signals">
                    {#each p.signals as s}
                      <span class="signal" style="border-color:{CELL_COLOR[s.level as Status]}">{s.message}</span>
                    {/each}
                  </span>
                </div>
              {/if}
            </div>
          </td>
        </tr>
      {/if}
    {/each}
  </tbody>
</table>

<style>
  .run-meta {
    display: grid;
    grid-template-columns: 160px 1fr;
    row-gap: 4px;
    column-gap: 12px;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
  }
  .meta-label {
    font-size: 0.8rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .meta-value {
    font-size: 0.9rem;
    font-family: "JetBrains Mono", monospace;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    display: inline-block;
    flex: none;
  }
  .ribbon-block {
    margin-bottom: 16px;
  }
  .phase-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
  }
  .phase-table th {
    padding: 6px 8px;
    border-bottom: 2px solid var(--border);
    font-size: 0.75rem;
    color: var(--muted);
    text-transform: uppercase;
    text-align: left;
  }
  .phase-table th.num {
    text-align: right;
  }
  .phase-row {
    cursor: pointer;
  }
  .phase-row td {
    padding: 5px 8px;
    border-bottom: 1px solid var(--border);
  }
  .phase-row:hover td {
    background: var(--hover);
  }
  .phase-row.open td {
    background: var(--hover);
  }
  .phase-row.slow .num {
    color: #9a6700;
    font-weight: 600;
  }
  .slow-flag {
    cursor: help;
  }
  .ph-name {
    font-family: "JetBrains Mono", monospace;
  }
  .num {
    text-align: right;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.8rem;
    white-space: nowrap;
  }
  .expand-row td {
    padding: 0;
    border-bottom: 1px solid var(--border);
  }
  .expand {
    padding: 8px 16px 12px;
    background: var(--bg);
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .expand-line {
    display: grid;
    grid-template-columns: 140px 1fr;
    gap: 12px;
    font-size: 0.82rem;
  }
  .expand-line .k {
    color: var(--muted);
    text-transform: uppercase;
    font-size: 0.72rem;
    letter-spacing: 0.05em;
  }
  .signals {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .signal {
    padding: 1px 6px;
    border: 1px solid;
    border-radius: 10px;
    font-size: 0.78rem;
  }
</style>
