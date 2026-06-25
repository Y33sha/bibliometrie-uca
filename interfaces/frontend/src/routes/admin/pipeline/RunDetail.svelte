<script lang="ts">
  import type { components } from "$lib/api/schema";
  import PhaseRibbon from "./PhaseRibbon.svelte";
  import { CELL_COLOR, fmtDate, fmtDuration, STATUS_LABEL, type Status } from "./helpers";

  type RunDetail = components["schemas"]["RunDetail"];
  type PhaseExecutionDetail = components["schemas"]["PhaseExecutionDetail"];

  type SourceRow = {
    found: number;
    new: number;
    updated: number;
    unchanged: number;
    errors: number;
    duration_s: number;
  };
  type RaRow = { ra: string; dois: number; prefixes: number; new: number };
  type Details = {
    tables?: Record<string, { before: number; after: number }>;
    by_source?: Record<string, SourceRow>;
    distributions?: Record<string, Record<string, number>>;
    ra_table?: { rows: RaRow[] };
  };

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

  function asDetails(d: unknown): Details {
    return (d ?? {}) as Details;
  }
  function bySource(d: unknown): [string, SourceRow][] {
    return Object.entries(asDetails(d).by_source ?? {});
  }
  function tableEntries(d: unknown): [string, { before: number; after: number }][] {
    // Seules les tables dont le volume change : un « 59841 ⇒ 59841 (+0) » pour une
    // phase d'enrichissement en place n'apprend rien.
    return Object.entries(asDetails(d).tables ?? {}).filter(([, v]) => v.before !== v.after);
  }
  function distributions(d: unknown): [string, Record<string, number>][] {
    return Object.entries(asDetails(d).distributions ?? {});
  }
  function pctRows(counts: Record<string, number>): { label: string; count: number; pct: string }[] {
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([label, count]) => ({ label, count, pct: fmtPct(count, total) }));
  }
  function raRows(d: unknown): RaRow[] {
    return asDetails(d).ra_table?.rows ?? [];
  }
  function raTotals(rows: RaRow[]): { dois: number; prefixes: number; new: number } {
    return rows.reduce(
      (a, r) => ({ dois: a.dois + r.dois, prefixes: a.prefixes + r.prefixes, new: a.new + r.new }),
      { dois: 0, prefixes: 0, new: 0 },
    );
  }
  function fmtPct(n: number, total: number): string {
    return total ? `${((n / total) * 100).toFixed(1)} %` : "—";
  }
  function fmtPerItem(durationS: number, total: number): string {
    if (!total) return "";
    const per = durationS / total;
    return per >= 1 ? `${per.toFixed(2)} s/élément` : `${(per * 1000).toFixed(0)} ms/élément`;
  }
  function extra(m: PhaseExecutionDetail["metrics"], key: string): number {
    return m.extras[key] ?? 0;
  }

  function metricsSummary(m: PhaseExecutionDetail["metrics"]): string {
    const parts: string[] = [];
    if (m.total) parts.push(`${m.total} traités`);
    if (m.new) parts.push(`${m.new} new`);
    if (m.updated) parts.push(`${m.updated} updated`);
    if (m.unchanged) parts.push(`${m.unchanged} unchanged`);
    if (m.errors) parts.push(`${m.errors} errors`);
    for (const [k, v] of Object.entries(m.extras ?? {})) if (v) parts.push(`${v} ${k}`);
    return parts.join(", ");
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
      <tr class="phase-row" class:open={expanded === p.phase} onclick={() => toggle(p.phase)}>
        <td class="ph-name">{p.phase}</td>
        <td>
          <span class="dot" style="background:{CELL_COLOR[p.status as Status]}"></span>
          {STATUS_LABEL[p.status as Status]}
        </td>
        <td class="num">{fmtDuration(p.duration_s)}</td>
        <td class="num">{p.signals.length || "—"}</td>
      </tr>
      {#if expanded === p.phase}
        <tr class="expand-row">
          <td colspan="4">
            <div class="expand">
              {#if raRows(p.details).length}
                {@const rows = raRows(p.details)}
                {@const tot = raTotals(rows)}
                <div class="expand-line">
                  <span class="k">Run</span>
                  <span>{p.metrics.new} nouveaux préfixes · {extra(p.metrics, "resolved")} résolus</span>
                </div>
                <table class="src-table">
                  <thead>
                    <tr>
                      <th>Registration Agency</th>
                      <th class="num">DOI</th>
                      <th class="num">Préfixes DOI</th>
                      <th class="num">Run</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each rows as r (r.ra)}
                      <tr>
                        <td>{r.ra}</td>
                        <td class="num">{r.dois} ({fmtPct(r.dois, tot.dois)})</td>
                        <td class="num">{r.prefixes} ({fmtPct(r.prefixes, tot.prefixes)})</td>
                        <td class="num">{r.new ? `+${r.new}` : "—"}</td>
                      </tr>
                    {/each}
                    <tr class="total-row">
                      <td>TOTAL</td>
                      <td class="num">{tot.dois}</td>
                      <td class="num">{tot.prefixes}</td>
                      <td class="num">{tot.new ? `+${tot.new}` : "—"}</td>
                    </tr>
                  </tbody>
                </table>
              {:else}
                {#if bySource(p.details).length}
                  <table class="src-table">
                    <thead>
                      <tr>
                        <th>Source</th>
                        <th class="num">Trouvés</th>
                        <th class="num">Nouveaux</th>
                        <th class="num">Màj</th>
                        <th class="num">Inchangés</th>
                        <th class="num">Durée</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each bySource(p.details) as [src, m] (src)}
                        <tr>
                          <td>{src}</td>
                          <td class="num">{m.found}</td>
                          <td class="num">{m.new}</td>
                          <td class="num">{m.updated}</td>
                          <td class="num">{m.unchanged}</td>
                          <td class="num">{fmtDuration(m.duration_s)}</td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                {/if}
                {#each distributions(p.details) as [title, counts] (title)}
                  <div class="dist">
                    <div class="dist-title">{title}</div>
                    {#each pctRows(counts) as row (row.label)}
                      <div class="dist-row">
                        <span>{row.label}</span>
                        <span class="num">{row.count} ({row.pct})</span>
                      </div>
                    {/each}
                  </div>
                {/each}
                {#each tableEntries(p.details) as [t, v] (t)}
                  <div class="expand-line">
                    <span class="k">{t}</span>
                    <span>{v.before} ⇒ {v.after} ({v.after - v.before >= 0 ? "+" : ""}{v.after - v.before})</span>
                  </div>
                {/each}
                {#if metricsSummary(p.metrics)}
                  <div class="expand-line">
                    <span class="k">Métriques</span><span>{metricsSummary(p.metrics)}</span>
                  </div>
                {/if}
              {/if}
              <div class="expand-line">
                <span class="k">Durée</span>
                <span>{fmtDuration(p.duration_s)}{#if p.metrics.total} ({fmtPerItem(p.duration_s, p.metrics.total)}){/if}</span>
              </div>
              {#if p.signals.length}
                <div class="expand-line">
                  <span class="k">Signaux</span>
                  <span class="signals">
                    {#each p.signals as s, i (i)}
                      <span class="signal" style="border-color:{CELL_COLOR[s.level as Status]}"
                        >{s.message}</span
                      >
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
  .phase-row:hover td,
  .phase-row.open td {
    background: var(--hover);
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
    gap: 6px;
  }
  .src-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82rem;
    margin-bottom: 4px;
  }
  .src-table th {
    padding: 3px 8px;
    border-bottom: 1px solid var(--border);
    font-size: 0.7rem;
    color: var(--muted);
    text-transform: uppercase;
    text-align: left;
  }
  .src-table th.num {
    text-align: right;
  }
  .src-table td {
    padding: 3px 8px;
    border-bottom: 1px solid var(--border);
  }
  .src-table .total-row td {
    border-top: 2px solid var(--border);
    border-bottom: none;
    font-weight: 600;
  }
  .dist {
    font-size: 0.82rem;
  }
  .dist-title {
    color: var(--muted);
    text-transform: uppercase;
    font-size: 0.72rem;
    letter-spacing: 0.05em;
    font-family: "JetBrains Mono", monospace;
    margin-bottom: 2px;
  }
  .dist-row {
    display: flex;
    justify-content: space-between;
    max-width: 320px;
    padding: 1px 0;
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
    font-family: "JetBrains Mono", monospace;
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
