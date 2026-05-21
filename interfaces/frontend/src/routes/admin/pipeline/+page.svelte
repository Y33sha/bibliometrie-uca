<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { api } from "$lib/api";

  import type { components } from "$lib/api/schema";
  type PipelineStatus = components["schemas"]["PipelineStatus"];
  type RunSummary = components["schemas"]["PipelineRunSummary"];
  type RunDetail = components["schemas"]["PipelineRunDetail"];
  type Observation = components["schemas"]["PipelineRunObservation"];
  type Report = components["schemas"]["PipelineReportItem"];

  type Tab = "snapshots" | "reports";

  let activeTab: Tab = $state("snapshots");

  // ── État statut pipeline ────────────────────────────────────────────
  let pipelineStatus: PipelineStatus | null = $state(null);
  let statusInterval: ReturnType<typeof setInterval> | null = null;

  // ── État snapshots ─────────────────────────────────────────────────
  let runs: RunSummary[] = $state([]);
  let selectedRunId: number | null = $state(null);
  let runDetail: RunDetail | null = $state(null);
  let runLoading = $state(false);

  // ── État rapports markdown ─────────────────────────────────────────
  const REPORTS_PAGE_SIZE = 20;
  let reports: Report[] = $state([]);
  let reportPage = $state(1);
  let selectedReport: string | null = $state(null);
  let reportContent: string = $state("");
  let reportRenderedHtml: string = $state("");
  let reportLoading = $state(false);

  const totalReportPages = $derived(Math.max(1, Math.ceil(reports.length / REPORTS_PAGE_SIZE)));
  const pagedReports = $derived(reports.slice((reportPage - 1) * REPORTS_PAGE_SIZE, reportPage * REPORTS_PAGE_SIZE));

  // ── Statut pipeline (polling) ──────────────────────────────────────
  async function pollStatus() {
    try {
      pipelineStatus = await api<PipelineStatus | null>("/api/admin/pipeline/status");
    } catch {
      pipelineStatus = null;
    }
  }

  function elapsed(isoDate: string): string {
    const seconds = Math.floor((Date.now() - new Date(isoDate).getTime()) / 1000);
    if (seconds < 60) return `${seconds}s`;
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m} min ${s}s`;
  }

  // ── Snapshots ──────────────────────────────────────────────────────
  async function loadRuns() {
    runs = await api<RunSummary[]>("/api/admin/pipeline-runs?limit=100");
    if (runs.length > 0 && selectedRunId === null) {
      await selectRun(runs[0].id);
    }
  }

  async function selectRun(runId: number) {
    runLoading = true;
    selectedRunId = runId;
    try {
      runDetail = await api<RunDetail>(`/api/admin/pipeline-runs/${runId}`);
    } finally {
      runLoading = false;
    }
  }

  function fmtDate(iso: string): string {
    const d = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function fmtDuration(s: number): string {
    if (s < 60) return `${s.toFixed(0)}s`;
    const m = Math.floor(s / 60);
    const rs = s - m * 60;
    if (m < 60) return `${m} min ${rs.toFixed(0)}s`;
    const h = Math.floor(m / 60);
    return `${h} h ${m - h * 60} min`;
  }

  function fmtValue(v: number): string {
    if (Number.isInteger(v)) return v.toString();
    if (Math.abs(v) < 1) return v.toFixed(3);
    return v.toFixed(1);
  }

  function fmtPrev(v: number | null): string {
    return v === null ? "—" : fmtValue(v);
  }

  type ObsFamily = { title: string; observations: Observation[] };

  const detailFamilies = $derived.by((): ObsFamily[] => {
    const d = runDetail;
    if (!d) return [];
    const groups: Record<string, Observation[]> = {};
    for (const o of d.observations) {
      const family = o.key.split(".")[0];
      groups[family] ??= [];
      groups[family].push(o);
    }
    const order: { key: string; title: string }[] = [
      { key: "volumes", title: "Volumes" },
      { key: "orphans", title: "Orphelins" },
      { key: "distributions", title: "Distributions" },
      { key: "matching_quality", title: "Qualité matching" },
    ];
    return order
      .filter((o) => groups[o.key]?.length)
      .map((o) => ({ title: o.title, observations: groups[o.key] }));
  });

  const suspectCount = $derived.by((): number => {
    const d = runDetail;
    if (!d) return 0;
    return d.observations.filter((o) => o.suspect).length;
  });

  const metricsRows = $derived.by(() => {
    const d = runDetail;
    if (!d) return [];
    return Object.entries(d.payload.metrics_per_phase).map(([phase, m]) => ({
      phase,
      ...m,
    }));
  });

  // ── Rapports markdown (préservé de l'ancien composant) ─────────────
  async function loadReports() {
    reports = await api<Report[]>("/api/admin/pipeline/reports");
  }

  async function selectReport(filename: string) {
    reportLoading = true;
    selectedReport = filename;
    const data = await api<{ content: string }>(`/api/admin/pipeline/reports/${filename}`);
    reportContent = data.content;
    reportRenderedHtml = markdownToHtml(reportContent);
    reportLoading = false;
  }

  function markdownToHtml(md: string): string {
    const lines = md.split("\n");
    const out: string[] = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (line.trim() === "") { i++; continue; }
      if (line.trim().startsWith("<details")) {
        out.push(lines[i]); i++;
        while (i < lines.length && !lines[i].includes("</details>")) {
          const inner = lines[i];
          if (inner.trim().startsWith("<summary") || inner.trim().startsWith("</summary")) {
            out.push(inner);
          } else if (inner.trim().startsWith("```")) {
            const codeLines: string[] = [];
            i++;
            while (i < lines.length && !lines[i].trim().startsWith("```")) {
              codeLines.push(escapeHtml(lines[i]));
              i++;
            }
            out.push(`<pre class="log-block">${codeLines.join("\n")}</pre>`);
          } else if (inner.startsWith("### ")) {
            out.push(`<h4>${inner.slice(4)}</h4>`);
          } else if (inner.trim() !== "") {
            out.push(`<p>${formatInline(inner)}</p>`);
          }
          i++;
        }
        if (i < lines.length) { out.push(lines[i]); i++; }
        continue;
      }
      if (line.trim().startsWith("```")) {
        const codeLines: string[] = [];
        i++;
        while (i < lines.length && !lines[i].trim().startsWith("```")) {
          codeLines.push(escapeHtml(lines[i]));
          i++;
        }
        if (i < lines.length) i++;
        out.push(`<pre class="log-block">${codeLines.join("\n")}</pre>`);
        continue;
      }
      if (line.startsWith("# ")) { out.push(`<h2>${line.slice(2)}</h2>`); i++; continue; }
      if (line.startsWith("## ")) { out.push(`<h3>${line.slice(3)}</h3>`); i++; continue; }
      if (line.startsWith("### ")) { out.push(`<h4>${line.slice(4)}</h4>`); i++; continue; }
      if (line.includes("|")) {
        const tableLines: string[] = [];
        while (i < lines.length && lines[i].includes("|")) {
          tableLines.push(lines[i]);
          i++;
        }
        const rows = tableLines.filter((r) => r.trim() && !r.includes("---"));
        if (rows.length > 0) {
          const header = rows[0].split("|").filter(Boolean).map((c) => c.trim());
          const body = rows.slice(1).map((r) => r.split("|").filter(Boolean).map((c) => c.trim()));
          out.push(`<table class="report-table"><thead><tr>${header.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${body.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
        }
        continue;
      }
      if (line.startsWith("- ")) {
        const items: string[] = [];
        while (i < lines.length && lines[i].startsWith("- ")) {
          items.push(lines[i].slice(2));
          i++;
        }
        out.push(`<ul>${items.map((it) => `<li>${formatInline(it)}</li>`).join("")}</ul>`);
        continue;
      }
      out.push(`<p>${formatInline(line)}</p>`);
      i++;
    }
    return out.join("\n");
  }

  function escapeHtml(s: string): string {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function formatInline(s: string): string {
    return s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  }

  // ── Cycle de vie ───────────────────────────────────────────────────
  onMount(() => {
    pollStatus();
    statusInterval = setInterval(pollStatus, 10000);
    loadRuns();
    loadReports();
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
    Pipeline <strong>{pipelineStatus.mode}</strong> en cours
    — phase <strong>{pipelineStatus.phase}</strong>
    ({pipelineStatus.phases_done}/{pipelineStatus.phases_total})
    — depuis {elapsed(pipelineStatus.started_at)}
  </div>
{/if}

<div class="tabs">
  <button class="tab" class:active={activeTab === "snapshots"} onclick={() => (activeTab = "snapshots")}>
    Snapshots
  </button>
  <button class="tab" class:active={activeTab === "reports"} onclick={() => (activeTab = "reports")}>
    Rapports
  </button>
</div>

{#if activeTab === "snapshots"}
  <div class="layout">
    <div class="run-list">
      {#if runs.length === 0}
        <p class="empty">Aucun snapshot disponible.</p>
      {:else}
        {#each runs as run (run.id)}
          <button
            class="run-item"
            class:active={selectedRunId === run.id}
            onclick={() => selectRun(run.id)}
          >
            <div class="run-item-row">
              <span class="run-mode">{run.mode}</span>
              <span class="run-duration">{fmtDuration(run.total_duration_s)}</span>
            </div>
            <div class="run-date">{fmtDate(run.ran_at)}</div>
          </button>
        {/each}
      {/if}
    </div>

    <div class="run-detail">
      {#if runLoading}
        <p class="loading">Chargement...</p>
      {:else if !runDetail}
        <p class="empty">Sélectionner un snapshot dans la liste.</p>
      {:else}
        <div class="run-meta">
          <div class="meta-row">
            <span class="meta-label">Mode</span>
            <span class="meta-value">{runDetail.mode}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Date</span>
            <span class="meta-value">{fmtDate(runDetail.ran_at)}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Durée totale</span>
            <span class="meta-value">{fmtDuration(runDetail.payload.total_duration_s)}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Sources</span>
            <span class="meta-value">{runDetail.payload.sources.join(", ") || "—"}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Phases</span>
            <span class="meta-value">{runDetail.payload.phases_run.join(" → ") || "—"}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Snapshot précédent</span>
            <span class="meta-value">
              {runDetail.previous_snapshot_at ? fmtDate(runDetail.previous_snapshot_at) : "—"}
            </span>
          </div>
        </div>

        <div class="section">
          <h3>
            Observations
            {#if suspectCount > 0}
              <span class="badge-suspect">{suspectCount} suspecte{suspectCount > 1 ? "s" : ""}</span>
            {:else if runDetail.previous_snapshot_at}
              <span class="badge-ok">aucune suspecte</span>
            {:else}
              <span class="badge-neutral">premier snapshot</span>
            {/if}
          </h3>
          {#each detailFamilies as family (family.title)}
            <h4>{family.title}</h4>
            <table class="data-table">
              <thead>
                <tr>
                  <th class="col-key">Observable</th>
                  <th class="col-num">Courant</th>
                  <th class="col-num">Précédent</th>
                  <th class="col-num">Delta</th>
                  <th class="col-note">Note</th>
                </tr>
              </thead>
              <tbody>
                {#each family.observations as obs (obs.key)}
                  <tr class:suspect={obs.suspect}>
                    <td class="col-key">{obs.label}</td>
                    <td class="col-num">{fmtValue(obs.current)}</td>
                    <td class="col-num">{fmtPrev(obs.previous)}</td>
                    <td class="col-num">
                      {obs.delta_pct === null ? "—" : `${obs.delta_pct >= 0 ? "+" : ""}${obs.delta_pct.toFixed(1)}%`}
                    </td>
                    <td class="col-note">{obs.threshold_note}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {/each}
        </div>

        {#if metricsRows.length > 0}
          <div class="section">
            <h3>Métriques par phase</h3>
            <table class="data-table">
              <thead>
                <tr>
                  <th class="col-key">Phase</th>
                  <th class="col-num">Durée</th>
                  <th class="col-num">Nouveaux</th>
                  <th class="col-num">Mis à jour</th>
                  <th class="col-num">Total</th>
                  <th class="col-num">Erreurs</th>
                </tr>
              </thead>
              <tbody>
                {#each metricsRows as row (row.phase)}
                  <tr>
                    <td class="col-key">{row.phase}</td>
                    <td class="col-num">{fmtDuration(row.duration_s)}</td>
                    <td class="col-num">{row.new}</td>
                    <td class="col-num">{row.updated}</td>
                    <td class="col-num">{row.total}</td>
                    <td class="col-num" class:error-cell={row.errors > 0}>{row.errors}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      {/if}
    </div>
  </div>
{:else}
  <div class="layout">
    <div class="report-list">
      {#if reports.length === 0}
        <p class="empty">Aucun rapport disponible.</p>
      {:else}
        {#each pagedReports as r (r.filename)}
          <button
            class="report-item"
            class:active={selectedReport === r.filename}
            onclick={() => selectReport(r.filename)}
          >
            {r.label}
          </button>
        {/each}
        {#if totalReportPages > 1}
          <div class="pager">
            <button class="pager-btn" disabled={reportPage === 1} onclick={() => (reportPage = Math.max(1, reportPage - 1))}>‹ Préc.</button>
            <span class="pager-info">{reportPage} / {totalReportPages}</span>
            <button class="pager-btn" disabled={reportPage === totalReportPages} onclick={() => (reportPage = Math.min(totalReportPages, reportPage + 1))}>Suiv. ›</button>
          </div>
        {/if}
      {/if}
    </div>

    <div class="report-content">
      {#if reportLoading}
        <p class="loading">Chargement...</p>
      {:else if reportRenderedHtml}
        {@html reportRenderedHtml}
      {:else}
        <p class="empty">Sélectionner un rapport dans la liste.</p>
      {/if}
    </div>
  </div>
{/if}

<style>
  .page-header {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 12px;
  }
  .page-header h2 {
    font-size: 1.2rem;
    margin: 0;
  }

  .tabs {
    display: flex;
    gap: 4px;
    margin-bottom: 12px;
    border-bottom: 1px solid var(--border);
  }
  .tab {
    padding: 6px 14px;
    font-size: 0.9rem;
    font-family: inherit;
    border: 1px solid transparent;
    border-bottom: none;
    background: transparent;
    cursor: pointer;
    color: var(--muted);
  }
  .tab:hover {
    color: var(--text, inherit);
  }
  .tab.active {
    background: var(--card);
    border-color: var(--border);
    color: var(--accent);
    position: relative;
    top: 1px;
  }

  .status-banner {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    margin-bottom: 12px;
    background: var(--accent-light, #e8f4f8);
    border: 1px solid var(--accent);
    border-radius: 6px;
    font-size: 0.85rem;
  }
  .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--accent);
    animation: pulse 1.5s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }

  .layout {
    display: flex;
    gap: 16px;
    align-items: flex-start;
  }

  .run-list, .report-list {
    width: 240px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .run-item, .report-item {
    display: block;
    width: 100%;
    padding: 6px 10px;
    text-align: left;
    font-size: 0.85rem;
    font-family: inherit;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--card);
    cursor: pointer;
  }
  .run-item:hover, .report-item:hover {
    background: var(--hover);
  }
  .run-item.active, .report-item.active {
    background: var(--accent);
    color: white;
    border-color: var(--accent);
  }
  .run-item-row {
    display: flex;
    justify-content: space-between;
    font-weight: 600;
  }
  .run-mode {
    text-transform: uppercase;
    font-size: 0.75rem;
    letter-spacing: 0.05em;
  }
  .run-duration {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.75rem;
  }
  .run-date {
    font-size: 0.75rem;
    opacity: 0.85;
    margin-top: 2px;
  }

  .run-detail, .report-content {
    flex: 1;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px 20px;
    min-height: 300px;
  }

  .run-meta {
    display: grid;
    grid-template-columns: 160px 1fr;
    row-gap: 4px;
    column-gap: 12px;
    margin-bottom: 20px;
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
  }

  .section {
    margin-top: 20px;
  }
  .section h3 {
    font-size: 1rem;
    margin: 0 0 12px;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .section h4 {
    font-size: 0.85rem;
    color: var(--muted);
    margin: 16px 0 6px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .badge-suspect, .badge-ok, .badge-neutral {
    font-size: 0.7rem;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .badge-suspect {
    background: #fde2e2;
    color: #a40000;
    border: 1px solid #f5b5b5;
  }
  .badge-ok {
    background: #e0f5e0;
    color: #006400;
    border: 1px solid #b5e2b5;
  }
  .badge-neutral {
    background: var(--hover);
    color: var(--muted);
    border: 1px solid var(--border);
  }

  .data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
    margin-bottom: 12px;
  }
  .data-table th {
    padding: 6px 8px;
    border-bottom: 2px solid var(--border);
    font-size: 0.75rem;
    color: var(--muted);
    text-transform: uppercase;
    text-align: left;
  }
  .data-table td {
    padding: 4px 8px;
    border-bottom: 1px solid var(--border);
  }
  .data-table tr.suspect td {
    background: #fef5f5;
  }
  .data-table tr.suspect td.col-key {
    font-weight: 600;
    color: #a40000;
  }
  .col-key {
    text-align: left;
  }
  .col-num {
    text-align: right;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.8rem;
    white-space: nowrap;
  }
  .col-note {
    text-align: left;
    font-size: 0.75rem;
    color: var(--muted);
  }
  .error-cell {
    color: #a40000;
    font-weight: 600;
  }

  /* ── Rapports markdown (préservé) ────────────────────────────────── */
  .report-content :global(h2) {
    font-size: 1.1rem;
    margin: 0 0 12px;
  }
  .report-content :global(h3) {
    font-size: 0.95rem;
    margin: 16px 0 8px;
    color: var(--accent);
  }
  .report-content :global(ul) {
    margin: 0 0 12px;
    padding-left: 20px;
  }
  .report-content :global(li) {
    font-size: 0.9rem;
    margin-bottom: 2px;
  }
  .report-content :global(p) {
    font-size: 0.9rem;
    margin: 4px 0;
  }
  :global(.report-table) {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
    margin: 4px 0 12px;
    table-layout: fixed;
  }
  :global(.report-table th) {
    padding: 4px 8px;
    border-bottom: 2px solid var(--border);
    font-size: 0.75rem;
    color: var(--muted);
    text-transform: uppercase;
  }
  :global(.report-table th:first-child) {
    text-align: left;
    width: 45%;
  }
  :global(.report-table th:nth-child(n+2)) {
    text-align: right;
    width: 18%;
  }
  :global(.report-table td) {
    padding: 3px 8px;
    border-bottom: 1px solid var(--border);
  }
  :global(.report-table td:first-child) {
    text-align: left;
  }
  :global(.report-table td:nth-child(n+2)) {
    text-align: right;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.8rem;
  }
  .report-content :global(details) {
    margin: 8px 0 16px;
    border: 1px solid var(--border);
    border-radius: 4px;
  }
  .report-content :global(summary) {
    padding: 6px 10px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    background: var(--hover);
    border-radius: 4px;
  }
  .report-content :global(details[open] > summary) {
    border-bottom: 1px solid var(--border);
    border-radius: 4px 4px 0 0;
  }
  .report-content :global(h4) {
    font-size: 0.85rem;
    margin: 12px 10px 4px;
    color: var(--muted);
  }
  .report-content :global(.log-block) {
    margin: 4px 10px 12px;
    padding: 8px 10px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.75rem;
    line-height: 1.5;
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .pager {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 4px;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid var(--border);
  }
  .pager-btn {
    padding: 4px 8px;
    font-size: 0.8rem;
    font-family: inherit;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--card);
    cursor: pointer;
  }
  .pager-btn:hover:not(:disabled) {
    background: var(--hover);
  }
  .pager-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .pager-info {
    font-size: 0.8rem;
    color: var(--muted);
    font-family: "JetBrains Mono", monospace;
  }

  .empty, .loading {
    color: var(--muted);
    font-size: 0.9rem;
  }
</style>
