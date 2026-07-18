<script lang="ts">
  import { api } from "$lib/api";
  import type { components } from "$lib/api/schema";
  import PhaseRibbon from "./PhaseRibbon.svelte";
  import { CELL_COLOR, fmtDate, fmtDuration, STATUS_LABEL, type Status } from "./helpers";
  import { PHASE_VIEWS, type PhaseView, type TableColumn } from "./phase-views";

  type RunDetail = components["schemas"]["RunDetail"];
  type PhaseExecutionDetail = components["schemas"]["PhaseExecutionDetail"];
  type PhaseLog = components["schemas"]["PipelinePhaseLog"];

  type TableBlock = { rows?: Record<string, string | number>[] };
  type Details = {
    summary?: Record<string, number>;
    // Tableaux sur-mesure, chacun sous sa propre clé (cf. `TableView.source`).
    [source: string]: unknown;
  };

  let { detail, allPhases }: { detail: RunDetail; allPhases: string[] } = $props();

  // Une ligne de phase déroule soit ses métriques (clic sur la ligne), soit son
  // log (clic sur le bouton « log ») ; jamais les deux à la fois.
  let expanded = $state<{ phase: string; kind: "metrics" | "log" } | null>(null);
  let logs = $state<Record<string, PhaseLog | "loading">>({});

  // Le composant est réutilisé d'un run à l'autre : réinitialiser l'ouverture et
  // le cache de logs (indexé par phase, mais propre au run) au changement de run.
  $effect(() => {
    detail.run_id;
    expanded = null;
    logs = {};
  });

  function toggleMetrics(phase: string) {
    expanded =
      expanded?.phase === phase && expanded.kind === "metrics" ? null : { phase, kind: "metrics" };
  }

  async function toggleLog(phase: string) {
    if (expanded?.phase === phase && expanded.kind === "log") {
      expanded = null;
      return;
    }
    expanded = { phase, kind: "log" };
    if (logs[phase] === undefined) {
      logs[phase] = "loading";
      try {
        logs[phase] = await api<PhaseLog>(
          `/api/pipeline/runs/${detail.run_id}/phases/${phase}/log`,
        );
      } catch {
        logs[phase] = { available: false, content: "" };
      }
    }
  }

  const statuses = $derived.by(() => {
    const map: Record<string, Status> = {};
    for (const p of detail.phases) map[p.phase] = p.status;
    return map;
  });

  function asDetails(d: unknown): Details {
    return (d ?? {}) as Details;
  }
  function detailSummary(d: unknown): Record<string, number> {
    return asDetails(d).summary ?? {};
  }
  function summaryLines(
    view: PhaseView | undefined,
    dsummary: Record<string, number>,
  ): [string, number][] {
    if (!view?.summary) return [];
    return view.summary
      .filter((item) => item.key in dsummary)
      .map((item): [string, number] => [item.label, dsummary[item.key]]);
  }
  function tableRows(d: unknown, source: string): Record<string, string | number>[] {
    const block = asDetails(d)[source] as TableBlock | undefined;
    return block?.rows ?? [];
  }

  function colTotal(rows: Record<string, string | number>[], key: string): number {
    return rows.reduce((a, r) => a + (Number(r[key]) || 0), 0);
  }
  function fmtPct(n: number, total: number): string {
    return total ? `${((n / total) * 100).toFixed(1)} %` : "—";
  }
  function fmtSigned(n: number): string {
    return n > 0 ? `+${n}` : n < 0 ? `${n}` : "—";
  }
  function fmtCell(value: string | number, col: TableColumn, total: number): string {
    const n = Number(value) || 0;
    if (col.duration) return fmtDuration(n);
    if (col.sign) return fmtSigned(n);
    if (col.percent) return `${n} %`;
    if (col.pct) return `${n} (${fmtPct(n, total)})`;
    return `${n}`;
  }
  function fmtTotalCell(sum: number, col: TableColumn): string {
    if (col.duration || col.percent) return "";
    return col.sign ? fmtSigned(sum) : `${sum}`;
  }
  function fillTemplate(tpl: string, dsummary: Record<string, number>): string {
    return tpl.replace(/\{(\w+)\}/g, (_, k) => `${dsummary[k] ?? "—"}`);
  }

  function fmtDurationLabel(p: PhaseExecutionDetail): string {
    const base = fmtDuration(p.duration_s);
    if (!p.metrics.total) return base; // pas de division par zéro sur un no-op
    const per = p.duration_s / p.metrics.total;
    const rate = per >= 1 ? `${per.toFixed(2)} s/élément` : `${(per * 1000).toFixed(0)} ms/élément`;
    return `${base} (${rate})`;
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
      <th class="num">Durée</th>
      <th>Statut</th>
      <th></th>
    </tr>
  </thead>
  <tbody>
    {#each detail.phases as p (p.phase)}
      <tr
        class="phase-row"
        class:open={expanded?.phase === p.phase}
        onclick={() => toggleMetrics(p.phase)}
      >
        <td class="ph-name">{p.phase}</td>
        <td class="num">{fmtDuration(p.duration_s)}</td>
        <td>
          <span class="dot" style="background:{CELL_COLOR[p.status as Status]}"></span>
          {STATUS_LABEL[p.status as Status]}
        </td>
        <td class="log-cell">
          <button
            class="log-btn"
            class:on={expanded?.phase === p.phase && expanded.kind === "log"}
            onclick={(e) => {
              e.stopPropagation();
              toggleLog(p.phase);
            }}>log</button
          >
        </td>
      </tr>
      {#if expanded?.phase === p.phase && expanded.kind === "log"}
        {@const entry = logs[p.phase]}
        <tr class="expand-row">
          <td colspan="4">
            <div class="expand">
              {#if entry === undefined || entry === "loading"}
                <p class="log-status">Chargement du log…</p>
              {:else if !entry.available}
                <p class="log-status">
                  Log indisponible (fichier logs/pipeline.log absent ou section purgée).
                </p>
              {:else}
                <pre class="log-view">{entry.content}</pre>
              {/if}
            </div>
          </td>
        </tr>
      {:else if expanded?.phase === p.phase}
        {@const view = PHASE_VIEWS[p.phase]}
        {@const lines = summaryLines(view, detailSummary(p.details))}
        <tr class="expand-row">
          <td colspan="4">
            <div class="expand">
              {#if view?.lines}
                {@const dsummary = detailSummary(p.details)}
                <div class="detail-lines">
                  {#each view.lines as tpl, i (i)}
                    <div>{fillTemplate(tpl, dsummary)}</div>
                  {/each}
                </div>
              {:else if lines.length}
                <div class="summary">
                  {#each lines as [label, value] (label)}
                    <div class="summary-line">
                      <span class="sk">{label}</span><span class="sv">{value}</span>
                    </div>
                  {/each}
                </div>
              {:else if !view?.matrix && metricsSummary(p.metrics)}
                <div class="expand-line">
                  <span class="k">Métriques</span><span>{metricsSummary(p.metrics)}</span>
                </div>
              {/if}

              {#if view?.matrix}
                {@const dsummary = detailSummary(p.details)}
                <table class="src-table">
                  <thead>
                    <tr>
                      <th></th>
                      {#each view.matrix.columns as c (c.key)}<th class="num">{c.label}</th>{/each}
                    </tr>
                  </thead>
                  <tbody>
                    {#each view.matrix.rows as row (row.key)}
                      <tr>
                        <td>{row.label}</td>
                        {#each view.matrix.columns as c (c.key)}
                          <td class="num">{dsummary[`${row.key}_${c.key}`] ?? "—"}</td>
                        {/each}
                      </tr>
                    {/each}
                  </tbody>
                </table>
              {/if}

              {#if view?.tables?.length}
                {#each view.tables as t (t.source)}
                  {@const drows = tableRows(p.details, t.source)}
                  {#if drows.length}
                    <table class="src-table">
                      <thead>
                        <tr>
                          <th>{t.firstColumnLabel}</th>
                          {#each t.columns as c (c.key)}<th class="num">{c.label}</th>{/each}
                        </tr>
                      </thead>
                      <tbody>
                        {#each drows as r (r.key)}
                          <tr>
                            <td>{t.rowLabels?.[r.key] ?? r.key}</td>
                            {#each t.columns as c (c.key)}
                              <td class="num">{fmtCell(r[c.key], c, colTotal(drows, c.key))}</td>
                            {/each}
                          </tr>
                        {/each}
                        {#if t.total}
                          <tr class="total-row">
                            <td>TOTAL</td>
                            {#each t.columns as c (c.key)}
                              <td class="num">{fmtTotalCell(colTotal(drows, c.key), c)}</td>
                            {/each}
                          </tr>
                        {/if}
                      </tbody>
                    </table>
                  {/if}
                {/each}
              {/if}

              <div class="expand-line">
                <span class="k">Durée</span><span>{fmtDurationLabel(p)}</span>
              </div>
              {#if p.signals.length}
                <div class="expand-line">
                  <span class="k">Motif</span>
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
    border-collapse: collapse;
    font-size: 0.82rem;
    margin-bottom: 10px;
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
  .summary {
    display: flex;
    flex-direction: column;
    font-size: 0.82rem;
    max-width: 420px;
    margin-bottom: 6px;
  }
  .summary-line {
    display: flex;
    justify-content: space-between;
    gap: 24px;
    padding: 4px 12px;
    border-bottom: 1px solid var(--border);
  }
  .summary-line:first-child {
    border-top: 1px solid var(--border);
  }
  .summary-line .sk {
    color: var(--muted);
  }
  .summary-line .sv {
    font-family: "JetBrains Mono", monospace;
  }
  .detail-lines {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 0.82rem;
    margin-bottom: 6px;
  }
  .expand-line {
    display: grid;
    grid-template-columns: 160px 1fr;
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
  .log-cell {
    width: 1%;
    text-align: right;
    white-space: nowrap;
  }
  .log-btn {
    padding: 1px 8px;
    border: 1px solid var(--border);
    border-radius: 4px;
    /* Fond blanc opaque : le bouton reste blanc même quand la ligne est
       survolée ou dépliée (le fond de survol de la ligne ne transparaît pas). */
    background: var(--card);
    color: var(--muted);
    cursor: pointer;
    font: inherit;
    font-size: 0.75rem;
    font-family: "JetBrains Mono", monospace;
  }
  .log-btn:hover {
    color: var(--accent);
    border-color: var(--accent);
  }
  .log-btn.on {
    border-color: var(--accent);
    color: var(--accent);
  }
  .log-status {
    color: var(--muted);
    font-size: 0.82rem;
    margin: 0;
  }
  .log-view {
    max-height: 420px;
    overflow-y: auto;
    margin: 0;
    padding: 8px 10px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 4px;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.75rem;
    line-height: 1.45;
    /* Largeur constante : les longues lignes wrappent à l'intérieur (indentation
       préservée), les tokens interminables (URLs) sont cassés, aucun débordement
       horizontal qui élargirait la colonne de détail. */
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
</style>
