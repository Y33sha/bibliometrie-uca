<script lang="ts">
  import { onMount } from "svelte";
  import { base } from "$app/paths";
  import { replaceState } from "$app/navigation";
  import { api, nameForms } from "$lib/api";
  import { esc, deriveStructDetectionStatus } from "$lib/utils";
  import { structDetectionClasses, structDetectionLabels } from "$lib/labels";
  import Pagination from "$lib/components/Pagination.svelte";
  import { confirmDialog, toast } from '$lib/dialogs.svelte';

  // ---------- Types ----------

  import type { components } from "$lib/api/schema";
  type FeedbackStats = components["schemas"]["FeedbackStats"];
  type LabDetected = components["schemas"]["FeedbackLabDetected"];
  type MatchedForm = components["schemas"]["FeedbackMatchedForm"];
  type FeedbackAddress = components["schemas"]["FeedbackAddressItem"];
  type FeedbackPage = components["schemas"]["FeedbackAddressesResponse"];
  type Structure = components["schemas"]["FeedbackStructureItem"];

  type GroupedStructures = Record<string, Structure[]>;

  interface NameForm {
    id: number;
    requires_context_of: (string | number)[];
  }

  // ---------- Constants ----------

  // Libellés d'affichage pour les groupes de structures. L'ordre des
  // clés sert aussi d'ordre d'affichage dans le picker. Les types
  // éligibles et la sélection par défaut (UCA) sont décidés côté API
  // par /api/admin/feedback/structures.
  const TYPE_LABELS: Record<string, string> = {
    universite: "Universités",
    onr: "Organismes de recherche",
    chu: "CHU",
    ecole: "Écoles",
    labo: "Laboratoires",
  };
  const TYPE_ORDER = Object.keys(TYPE_LABELS);

  // ---------- URL params helpers ----------

  function readUrlParams(): { tab: Tab; search: string; p: number; structureId: number | null } {
    const sp = new URLSearchParams(window.location.search);
    const tab = sp.get("tab") === "fp" ? "fp" : "fn";
    return {
      tab,
      search: sp.get("search") || "",
      p: parseInt(sp.get("page") || "1") || 1,
      structureId: sp.has("structure_id") ? parseInt(sp.get("structure_id")!) || null : null,
    };
  }

  function syncUrl(): void {
    const sp = new URLSearchParams();
    if (currentStructureId) sp.set("structure_id", String(currentStructureId));
    if (currentTab !== "fn") sp.set("tab", currentTab);
    if (search) sp.set("search", search);
    if (currentPage > 1) sp.set("page", String(currentPage));
    const qs = sp.toString();
    const newUrl = window.location.pathname + (qs ? "?" + qs : "");
    replaceState(newUrl, {});
  }

  // ---------- State ----------

  type Tab = "fn" | "fp";

  let currentStructureId = $state<number | null>(null);
  let structures = $state<GroupedStructures>({});
  let allStructures = $state<Structure[]>([]);

  let stats: FeedbackStats | null = $state(null);
  let currentTab: Tab = $state("fn");
  let currentPage = $state(1);
  let pages = $state(0);
  let total = $state(0);
  let addresses: FeedbackAddress[] = $state([]);
  let search = $state("");
  let searchTimeout: ReturnType<typeof setTimeout> | null = $state(null);

  // Context picker state
  let ctxPicker: { formId: number; x: number; y: number } | null = $state(null);
  let ctxSearch = $state("");

  const ctxFilteredStructures = $derived.by(() => {
    const q = ctxSearch.toLowerCase();
    return allStructures.filter((s) => s.name.toLowerCase().includes(q) || (s.acronym || "").toLowerCase().includes(q) || s.code.toLowerCase().includes(q)).slice(0, 8);
  });

  const helpText = $derived.by(() => {
    if (currentTab === "fn") {
      return {
        title: "Faux négatifs",
        body: "Adresses reliées manuellement à cette structure mais non détectées par le script. Ajouter des formes de nom et relancer la détection.",
      };
    }
    return {
      title: "Faux positifs",
      body: "Adresses détectées par le script pour cette structure mais rejetées manuellement. La forme ayant matché est affichée \u2014 vous pouvez la supprimer ou lui ajouter un contexte contraignant, puis relancer la détection.",
    };
  });


  // ---------- Data loading ----------

  async function loadStructures(): Promise<void> {
    // L'API filtre les types éligibles et choisit la structure par
    // défaut (UCA ou fallback selon la règle métier côté backend).
    const data = await api<components["schemas"]["FeedbackStructuresResponse"]>(
      "/api/admin/feedback/structures"
    );
    structures = data.by_type;
    allStructures = Object.values(data.by_type).flat();
    if (data.default_structure_id) {
      currentStructureId = data.default_structure_id;
    }
  }

  async function loadStats() {
    if (!currentStructureId) return;
    stats = await api<FeedbackStats>(`/api/admin/feedback/stats?structure_id=${currentStructureId}`, { key: "feedback-stats" });
  }

  async function loadTable() {
    if (!currentStructureId) return;
    syncUrl();
    const endpoint = currentTab === "fn" ? "/api/admin/feedback/false-negatives" : "/api/admin/feedback/false-positives";
    const params = new URLSearchParams({
      structure_id: String(currentStructureId),
      page: String(currentPage),
      per_page: "50",
    });
    if (search) params.set("search", search);

    const data = await api<FeedbackPage>(endpoint + "?" + params, { key: "feedback-table" });
    addresses = data.addresses;
    total = data.total;
    pages = data.pages;
    currentPage = data.page;
  }

  function switchTab(tab: Tab) {
    currentTab = tab;
    currentPage = 1;
    search = "";
    loadTable();
  }

  function onSearchInput() {
    if (searchTimeout) clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      currentPage = 1;
      loadTable();
    }, 400);
  }

  function onPageChange(p: number) {
    currentPage = p;
    loadTable();
    window.scrollTo(0, 0);
  }

  function onStructureChange(e: Event) {
    currentStructureId = parseInt((e.target as HTMLSelectElement).value);
    localStorage.setItem('admin_structure_id', String(currentStructureId));
    currentPage = 1;
    loadStats();
    loadTable();
  }

  // ---------- Form actions (FP) ----------

  async function deleteForm(formId: number) {
    if (!(await confirmDialog({ message: "Supprimer cette forme de nom ? Cela affectera la détection après relance.", danger: true }))) return;
    try {
      await nameForms.remove(formId);
      loadTable();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      toast("Erreur : " + msg, 'error');
    }
  }

  function openCtxPicker(formId: number, event: MouseEvent) {
    event.stopPropagation();
    const btn = event.target as HTMLElement;
    const rect = btn.getBoundingClientRect();
    ctxSearch = "";
    ctxPicker = {
      formId,
      x: Math.min(rect.left, window.innerWidth - 340),
      y: rect.bottom + 4,
    };
  }

  function closeCtxPicker() {
    ctxPicker = null;
  }

  async function addCtxToForm(item: string | number) {
    if (!ctxPicker) return;
    const formId = ctxPicker.formId;
    closeCtxPicker();

    try {
      const formData = await api<NameForm>("/api/name-forms/" + formId);
      const ctx = formData.requires_context_of || [];
      if (!ctx.includes(item)) ctx.push(item);

      await nameForms.update(formId, { requires_context_of: ctx });
      loadTable();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      toast("Erreur : " + msg, 'error');
    }
  }

  function handleOutsideClick(event: MouseEvent) {
    if (!ctxPicker) return;
    const target = event.target as HTMLElement;
    const picker = document.getElementById("form-ctx-picker");
    if (picker && !picker.contains(target) && !target.classList.contains("form-action")) {
      closeCtxPicker();
    }
  }

  // ---------- Helpers ----------

  function uniqueForms(forms: MatchedForm[]): MatchedForm[] {
    const seen = new Set<number>();
    return forms.filter((f) => {
      if (seen.has(f.form_id)) return false;
      seen.add(f.form_id);
      return true;
    });
  }

  function structDetectionStatus(l: LabDetected): 'confirmed' | 'rejected' | 'detected' | 'manual' {
    return deriveStructDetectionStatus(l.is_confirmed, l.is_detected);
  }

  function structTagTitle(l: LabDetected): string {
    return `${l.name} (${structDetectionLabels[structDetectionStatus(l)]})`;
  }

  function formatCtx(ctx: (string | number)[]): string {
    return ctx.map((x) => (x === "tutelles" ? "\uD83D\uDD17tut." : String(x))).join(", ");
  }

  // ---------- Init ----------

  onMount(async () => {
    const url = readUrlParams();
    currentTab = url.tab;
    search = url.search;
    currentPage = url.p;

    await loadStructures();
    if (url.structureId) {
      currentStructureId = url.structureId;
    } else {
      const saved = localStorage.getItem('admin_structure_id');
      if (saved) currentStructureId = parseInt(saved);
    }
    loadStats();
    loadTable();
  });
</script>

<svelte:head>
  <title>Admin - Qualité détection - Bibliométrie UCA</title>
</svelte:head>

<svelte:window onclick={handleOutsideClick} />

<div class="page-feedback">
  <p class="back-link"><a href="{base}/admin/addresses{currentStructureId ? '?structure_id=' + currentStructureId : ''}">← Affiliations des adresses</a></p>
  <h2>Qualité de la détection</h2>

  <!-- Stats row -->
  {#if stats}
    <div class="stats-row">
      <div class="stat-card highlight-success">
        <div class="value val-success">
          {stats.detection_rate !== null ? stats.detection_rate + "%" : "\u2014"}
        </div>
        <div class="label">Taux de concordance</div>
      </div>
      <div class="stat-card">
        <div class="value">{stats.total_reviewed}</div>
        <div class="label">Adresses examinées</div>
      </div>
      <div class="stat-card highlight-warning">
        <div class="value val-warning">{stats.false_negatives}</div>
        <div class="label">Faux négatifs</div>
      </div>
      <div class="stat-card highlight-danger">
        <div class="value val-danger">{stats.false_positives}</div>
        <div class="label">Faux positifs</div>
      </div>
      <div class="stat-card">
        <div class="value">{stats.concordant_valid}</div>
        <div class="label">Vrais positifs</div>
      </div>
      <div class="stat-card">
        <div class="value">{stats.pending}</div>
        <div class="label">En attente</div>
      </div>
    </div>
  {/if}

  <!-- Help text -->
  <div class="help-text">
    <strong>{helpText.title}</strong> &mdash; {helpText.body}
  </div>

  <!-- Toolbar -->
  <div class="toolbar">
    <select class="structure-filter" value={currentStructureId ?? ""} onchange={onStructureChange}>
      {#each TYPE_ORDER as type}
        {#if structures[type]?.length}
          <optgroup label={TYPE_LABELS[type]}>
            {#each structures[type] as s (s.id)}
              <option value={s.id}>{s.acronym || s.name}</option>
            {/each}
          </optgroup>
        {/if}
      {/each}
    </select>

    <div class="toolbar-sep"></div>

    <div class="tab-group">
      <button class="tab-btn" class:active={currentTab === "fn"} onclick={() => switchTab("fn")}> Faux négatifs </button>
      <button class="tab-btn" class:active={currentTab === "fp"} onclick={() => switchTab("fp")}> Faux positifs </button>
    </div>
    <input type="text" placeholder="Rechercher dans les adresses..." bind:value={search} oninput={onSearchInput} />
    <span class="count">{total} adresses</span>
  </div>

  <!-- Table -->
  {#if addresses.length === 0}
    <div class="empty">Aucune adresse trouvée &mdash; la détection est parfaite pour ce cas !</div>
  {:else}
    <table class="data-table">
      <thead>
        <tr>
          <th>Adresse</th>
          <th class="num" style="width:60px">Publis</th>
          <th style="width:200px">Structures liées</th>
          {#if currentTab === "fp"}
            <th style="width:280px">Forme ayant matché</th>
          {/if}
        </tr>
      </thead>
      <tbody>
        {#each addresses as a (a.id)}
          <tr>
            <td class="addr-text">{@html esc(a.raw_text)}</td>
            <td class="num">{a.pub_count}</td>
            <td>
              {#if a.labs && a.labs.length > 0}
                {#each a.labs as l}
                  <span class={structDetectionClasses[structDetectionStatus(l)]} title={structTagTitle(l)}>
                    {l.acronym || l.name}
                  </span>
                {/each}
              {:else}
                <span class="muted-small">aucune</span>
              {/if}
            </td>

            {#if currentTab === "fp"}
              <!-- FP: matched forms -->
              <td>
                {#if a.matched_forms && a.matched_forms.length > 0}
                  {#each uniqueForms(a.matched_forms) as f (f.form_id)}
                    <div class="form-info">
                      <span class="form-struct">{f.structure_name} &rarr;</span>
                      <span class="form-text">{f.form_text}</span>
                      {#if f.requires_context_of && f.requires_context_of.length}
                        <span class="form-ctx">
                          (ctx: {formatCtx(f.requires_context_of)})
                        </span>
                      {/if}
                      <button class="form-action" title="Ajouter un contexte contraignant" onclick={(e) => openCtxPicker(f.form_id, e)}> + ctx </button>
                      <button class="form-action danger" title="Supprimer cette forme" onclick={() => deleteForm(f.form_id)}> suppr. </button>
                    </div>
                  {/each}
                {:else}
                  <span class="muted-small">forme inconnue</span>
                {/if}
              </td>
            {/if}
          </tr>
        {/each}
      </tbody>
    </table>

    <Pagination page={currentPage} {pages} onchange={onPageChange} />
  {/if}

  <!-- Context picker -->
  {#if ctxPicker}
    <div class="ctx-picker-inline" id="form-ctx-picker" style="top:{ctxPicker.y}px;left:{ctxPicker.x}px" onclick={(e) => e.stopPropagation()} onkeydown={() => {}} role="dialog">
      <div class="picker-shortcuts">
        <button onclick={() => addCtxToForm("tutelles")}>{"\uD83D\uDD17"} tutelles</button>
      </div>
      <input type="text" placeholder="Rechercher une structure..." bind:value={ctxSearch} />
      <div class="picker-results">
        {#each ctxFilteredStructures as s (s.id)}
          <button class="picker-item" onclick={() => addCtxToForm(s.id)}>
            <span class="picker-type">{s.type}</span>
            {s.acronym ? s.acronym + " \u2014 " : ""}{s.name}
          </button>
        {/each}
        {#if ctxFilteredStructures.length === 0}
          <div class="picker-item-empty">Aucun résultat</div>
        {/if}
      </div>
    </div>
  {/if}
</div>

<style>
  h2 {
    font-size: 1.2rem;
    font-weight: 600;
    margin: 0 0 16px;
  }

  /* Stats row */
  .stats-row {
    display: flex;
    gap: 10px;
    margin-bottom: 20px;
    flex-wrap: wrap;
  }

  .stat-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px 18px;
    text-align: center;
    flex: 1;
    min-width: 120px;
  }

  .stat-card .value {
    font-size: 1.55rem;
    font-weight: 700;
    line-height: 1.2;
  }

  .stat-card .label {
    font-size: 0.8rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .stat-card.highlight-danger {
    border-left: 3px solid var(--danger);
  }
  .stat-card.highlight-warning {
    border-left: 3px solid var(--warning);
  }
  .stat-card.highlight-success {
    border-left: 3px solid var(--success);
  }
  .val-danger {
    color: var(--danger);
  }
  .val-warning {
    color: var(--warning);
  }
  .val-success {
    color: var(--success);
  }

  /* Help text */
  .back-link {
    margin: 0 0 4px;
    font-size: 0.85rem;
  }
  .back-link a {
    color: var(--accent);
    text-decoration: none;
  }
  .back-link a:hover {
    text-decoration: underline;
  }
  .help-text {
    background: var(--accent-light);
    border: 1px solid #c4d8ed;
    border-radius: 5px;
    padding: 10px 14px;
    margin-bottom: 16px;
    font-size: 0.95rem;
    color: #2c3e50;
    line-height: 1.5;
  }

  /* Toolbar */
  .toolbar {
    margin-bottom: 16px;
  }
  .structure-filter {
    padding: 6px 10px;
    border: 1px solid var(--accent);
    border-radius: 4px;
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--accent);
    background: white;
    font-family: inherit;
  }

  .toolbar-sep {
    width: 1px;
    height: 24px;
    background: var(--border);
    margin: 0 4px;
  }

  .tab-group {
    display: flex;
    gap: 0;
    margin-right: 4px;
  }

  .tab-btn {
    padding: 6px 14px;
    border: 1px solid var(--border);
    background: white;
    font-size: 0.95rem;
    cursor: pointer;
    font-family: inherit;
  }
  .tab-btn:first-child {
    border-radius: 4px 0 0 4px;
  }
  .tab-btn:last-child {
    border-radius: 0 4px 4px 0;
  }
  .tab-btn:not(:first-child) {
    border-left: none;
  }
  .tab-btn.active {
    background: var(--accent);
    color: white;
    border-color: var(--accent);
  }

  .toolbar input[type="text"] {
    width: 250px;
    background: white;
  }

  /* Table */
  .addr-text {
    font-family: "SF Mono", "Consolas", monospace;
    font-size: 0.85rem;
    line-height: 1.4;
    word-break: break-word;
    max-width: 600px;
  }
  .muted-small {
    color: var(--muted);
    font-size: 0.8rem;
  }

  /* Structure tags */
  .struct-tag {
    display: inline-block;
    font-size: 0.8rem;
    padding: 1px 7px;
    border-radius: 10px;
    font-weight: 500;
    margin: 1px 2px;
  }
  .struct-confirmed {
    background: var(--success-light);
    color: var(--success);
  }
  .struct-detected {
    background: var(--warning-light);
    color: #8a6d10;
  }
  .struct-manual {
    background: var(--accent-light);
    color: #2c5e8a;
    border: 1px dashed #a0c0e0;
  }
  .struct-rejected {
    background: #f5f5f5;
    color: #999;
    text-decoration: line-through;
  }

  /* Form info (FP tab) */
  .form-info {
    font-size: 0.8rem;
    margin-top: 4px;
    padding: 4px 8px;
    background: #fef8e8;
    border: 1px solid #f0e4b8;
    border-radius: 4px;
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .form-struct {
    color: var(--muted);
  }
  .form-text {
    font-family: "SF Mono", "Consolas", monospace;
    font-weight: 600;
    color: #8a6d10;
  }
  .form-ctx {
    color: var(--muted);
  }
  .form-action {
    padding: 1px 6px;
    border: 1px solid var(--border);
    border-radius: 3px;
    background: white;
    font-size: 0.7rem;
    cursor: pointer;
    font-weight: 500;
    font-family: inherit;
  }
  .form-action:hover {
    background: var(--accent-light);
  }
  .form-action.danger {
    border-color: var(--danger);
    color: var(--danger);
  }
  .form-action.danger:hover {
    background: var(--danger-light);
  }

  /* Context picker */
  .ctx-picker-inline {
    position: fixed;
    z-index: 100;
    background: white;
    border: 1px solid var(--accent);
    border-radius: 5px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
    width: 320px;
  }
  .ctx-picker-inline input {
    width: 100%;
    padding: 6px 10px;
    border: none;
    border-bottom: 1px solid var(--border);
    border-radius: 0;
    font-size: 0.85rem;
    outline: none;
  }
  .picker-results {
    max-height: 180px;
    overflow-y: auto;
  }
  .picker-item {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 5px 10px;
    font-size: 0.85rem;
    cursor: pointer;
    background: none;
    border: none;
    width: 100%;
    text-align: left;
    font-family: inherit;
  }
  .picker-item:hover {
    background: var(--accent-light);
  }
  .picker-type {
    font-size: 0.65rem;
    color: var(--muted);
  }
  .picker-item-empty {
    padding: 5px 10px;
    font-size: 0.85rem;
    color: var(--muted);
  }
  .picker-shortcuts {
    padding: 4px 8px;
    border-bottom: 1px solid var(--border);
    display: flex;
    gap: 4px;
  }
  .picker-shortcuts button {
    padding: 2px 8px;
    border: 1px solid var(--border);
    border-radius: 3px;
    background: white;
    font-size: 0.8rem;
    cursor: pointer;
    font-family: inherit;
  }
  .picker-shortcuts button:hover {
    background: var(--accent-light);
  }
</style>
