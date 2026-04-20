<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { api } from "$lib/api";

  import type { components } from "$lib/api/schema";
  type Report = components["schemas"]["PipelineReportItem"];
  type PipelineStatus = components["schemas"]["PipelineStatus"];

  let reports: Report[] = $state([]);
  let selectedReport: string | null = $state(null);
  let reportContent: string = $state("");
  let renderedHtml: string = $state("");
  let loading = $state(false);
  let pipelineStatus: PipelineStatus | null = $state(null);
  let statusInterval: ReturnType<typeof setInterval> | null = null;
  let activeTab: "reports" | "logs" = $state("reports");
  let cronLog: string = $state("");
  let logInterval: ReturnType<typeof setInterval> | null = null;

  async function pollStatus() {
    try {
      pipelineStatus = await api<PipelineStatus | null>("/api/admin/pipeline/status");
    } catch { pipelineStatus = null; }
  }

  async function loadLogs() {
    try {
      const data = await api<{ content: string }>("/api/admin/pipeline/logs?lines=200");
      cronLog = data.content;
    } catch { cronLog = ""; }
  }

  function switchTab(tab: "reports" | "logs") {
    activeTab = tab;
    if (tab === "logs") {
      loadLogs();
      logInterval = setInterval(loadLogs, 5000);
    } else {
      if (logInterval) { clearInterval(logInterval); logInterval = null; }
    }
  }

  function elapsed(isoDate: string): string {
    const seconds = Math.floor((Date.now() - new Date(isoDate).getTime()) / 1000);
    if (seconds < 60) return `${seconds}s`;
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m} min ${s}s`;
  }

  async function loadList() {
    reports = await api<Report[]>("/api/admin/pipeline/reports");
  }

  async function selectReport(filename: string) {
    loading = true;
    selectedReport = filename;
    const data = await api<{ content: string }>(`/api/admin/pipeline/reports/${filename}`);
    reportContent = data.content;
    renderedHtml = markdownToHtml(reportContent);
    loading = false;
  }

  function markdownToHtml(md: string): string {
    const lines = md.split("\n");
    const out: string[] = [];
    let i = 0;

    while (i < lines.length) {
      const line = lines[i];

      // Lignes vides
      if (line.trim() === "") { i++; continue; }

      // <details> / <summary> — parser le contenu Markdown à l'intérieur
      if (line.trim().startsWith("<details")) {
        out.push(lines[i]); i++; // <details>
        // Passer les lignes HTML telles quelles (<summary>, etc.)
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
        if (i < lines.length) { out.push(lines[i]); i++; } // </details>
        continue;
      }

      // Blocs de code (```)
      if (line.trim().startsWith("```")) {
        const codeLines: string[] = [];
        i++; // sauter la ligne d'ouverture
        while (i < lines.length && !lines[i].trim().startsWith("```")) {
          codeLines.push(escapeHtml(lines[i]));
          i++;
        }
        if (i < lines.length) i++; // sauter la ligne de fermeture
        out.push(`<pre class="log-block">${codeLines.join("\n")}</pre>`);
        continue;
      }

      // Titres
      if (line.startsWith("# ")) { out.push(`<h2>${line.slice(2)}</h2>`); i++; continue; }
      if (line.startsWith("## ")) { out.push(`<h3>${line.slice(3)}</h3>`); i++; continue; }
      if (line.startsWith("### ")) { out.push(`<h4>${line.slice(4)}</h4>`); i++; continue; }

      // Tableau (collecte toutes les lignes consécutives avec |)
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

      // Liste
      if (line.startsWith("- ")) {
        const items: string[] = [];
        while (i < lines.length && lines[i].startsWith("- ")) {
          items.push(lines[i].slice(2));
          i++;
        }
        out.push(`<ul>${items.map((it) => `<li>${formatInline(it)}</li>`).join("")}</ul>`);
        continue;
      }

      // Paragraphe
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

  onMount(() => {
    loadList();
    pollStatus();
    statusInterval = setInterval(pollStatus, 10000);
  });

  onDestroy(() => {
    if (statusInterval) clearInterval(statusInterval);
    if (logInterval) clearInterval(logInterval);
  });
</script>

<svelte:head><title>Pipeline — Bibliométrie UCA</title></svelte:head>

<div class="page-header">
  <h2>Pipeline</h2>
  <div class="tabs">
    <button class="tab" class:active={activeTab === "reports"} onclick={() => switchTab("reports")}>Rapports</button>
    <button class="tab" class:active={activeTab === "logs"} onclick={() => switchTab("logs")}>Logs</button>
  </div>
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

{#if activeTab === "reports"}
  <div class="layout">
    <div class="report-list">
      {#if reports.length === 0}
        <p class="empty">Aucun rapport disponible.</p>
      {:else}
        {#each reports as r (r.filename)}
          <button
            class="report-item"
            class:active={selectedReport === r.filename}
            onclick={() => selectReport(r.filename)}
          >
            {r.label}
          </button>
        {/each}
      {/if}
    </div>

    <div class="report-content">
      {#if loading}
        <p class="loading">Chargement...</p>
      {:else if renderedHtml}
        {@html renderedHtml}
      {:else}
        <p class="empty">Sélectionner un rapport dans la liste.</p>
      {/if}
    </div>
  </div>
{:else}
  <div class="log-container">
    {#if cronLog}
      <pre class="cron-log">{cronLog}</pre>
    {:else}
      <p class="empty">Aucun log disponible.</p>
    {/if}
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
  }
  .tab {
    padding: 4px 12px;
    font-size: 0.8rem;
    font-family: inherit;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--card);
    cursor: pointer;
  }
  .tab:hover { background: var(--hover); }
  .tab.active {
    background: var(--accent);
    color: white;
    border-color: var(--accent);
  }
  .layout {
    display: flex;
    gap: 16px;
    align-items: flex-start;
  }
  .report-list {
    width: 200px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .report-item {
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
  .report-item:hover {
    background: var(--hover);
  }
  .report-item.active {
    background: var(--accent);
    color: white;
    border-color: var(--accent);
  }
  .report-content {
    flex: 1;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px 20px;
    min-height: 300px;
  }
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
  .log-container {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px;
    min-height: 300px;
  }
  .cron-log {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.75rem;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-all;
    margin: 0;
  }
  .empty, .loading {
    color: var(--muted);
    font-size: 0.9rem;
  }
</style>
