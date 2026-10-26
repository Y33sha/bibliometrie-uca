<script lang="ts">
  import Breadcrumb from '#lib/components/Breadcrumb.svelte';
  import ResultCount from '#lib/components/ResultCount.svelte';
  import { pageTitle } from '#lib/institution.svelte.js';
  import { onMount } from "svelte";
  import { replaceState } from "$app/navigation";
  import { api, nameForms, structures as structuresApi } from "#lib/api/index.js";
  import { deriveStructDetectionStatus } from "#lib/utils.js";
  import { structureLabel } from "#lib/structureLabels.js";
  import { groupStructuresByType, structureGroupLabel } from "#lib/structureTypes.js";
  import { structDetectionClasses, structDetectionLabels } from "#lib/labels.js";
  import ListStatus from "#lib/components/ListStatus.svelte";
  import Pagination from "#lib/components/Pagination.svelte";
  import { usePaginatedFetch } from "#lib/composables/usePaginatedFetch.svelte.js";
  import { autofocus } from "#lib/actions/focus.js";
  import { confirmDialog, toast } from '#lib/dialogs.svelte.js';

  // ---------- Types ----------

  import type { components } from "#lib/api/schema.js";
  type FeedbackStats = components["schemas"]["FeedbackStats"];
  type AddressStructure = components["schemas"]["AddressStructureSummary"];
  type MatchedForm = components["schemas"]["FeedbackMatchedForm"];
  type FeedbackAddress = components["schemas"]["FeedbackAddressItem"];
  type Structure = components["schemas"]["StructureListItem"];

  interface NameForm {
    id: number;
    requires_context_of: (string | number)[];
  }

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
    if (list.page > 1) sp.set("page", String(list.page));
    const qs = sp.toString();
    const newUrl = window.location.pathname + (qs ? "?" + qs : "");
    replaceState(newUrl, {});
  }

  // ---------- State ----------

  type Tab = "fn" | "fp";

  let currentStructureId = $state<number | null>(null);
  let allStructures = $state<Structure[]>([]);
  const structureGroups = $derived(groupStructuresByType(allStructures));

  let stats: FeedbackStats | null = $state(null);
  let currentTab: Tab = $state("fn");
  let search = $state("");
  let searchTimeout: ReturnType<typeof setTimeout> | null = $state(null);
  const list = usePaginatedFetch<FeedbackAddress>({
    endpoint: () =>
      currentTab === "fn" ? "/api/feedback/false-negatives" : "/api/feedback/false-positives",
    itemsKey: "addresses",
    apiKey: "feedback-table",
    buildParams() {
      const params = new URLSearchParams({ structure_id: String(currentStructureId) });
      if (search) params.set("search", search);
      return params;
    },
  });
  const addresses = $derived(list.items);

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
    allStructures = await structuresApi.listDetectable();
    // À défaut de choix dans l'URL, la première structure du premier groupe affiché.
    currentStructureId ??= structureGroups[0]?.[1][0].id ?? null;
  }

  async function loadStats() {
    if (!currentStructureId) return;
    stats = await api<FeedbackStats>(`/api/feedback/stats?structure_id=${currentStructureId}`, { key: "feedback-stats" });
  }

  function loadTable() {
    if (!currentStructureId) return;
    syncUrl();
    list.load();
  }

  function switchTab(tab: Tab) {
    currentTab = tab;
    list.page = 1;
    search = "";
    loadTable();
  }

  function onSearchInput() {
    if (searchTimeout) clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      list.page = 1;
      loadTable();
    }, 400);
  }

  function onPageChange(p: number) {
    list.goToPage(p);
    syncUrl();
  }

  function onStructureChange(e: Event) {
    currentStructureId = parseInt((e.target as HTMLSelectElement).value);
    localStorage.setItem('admin_structure_id', String(currentStructureId));
    list.page = 1;
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
      const formData = await api<NameForm>("/api/structures/name-forms/" + formId);
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

  function structDetectionStatus(l: AddressStructure): 'confirmed' | 'rejected' | 'detected' | 'manual' {
    return deriveStructDetectionStatus(l.is_confirmed, l.is_detected);
  }

  function structTagTitle(l: AddressStructure): string {
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
    list.page = url.p;

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
  <title>{pageTitle("Admin - Qualité détection")}</title>
</svelte:head>

<svelte:window onclick={handleOutsideClick} />

<div class="page-feedback">
  <Breadcrumb
    trail={[{ label: "Affiliations", path: currentStructureId ? `admin/addresses?structure_id=${currentStructureId}` : "admin/addresses" }]}
    current="Qualité de la détection"
  />
  <h1>Qualité de la détection</h1>

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
  <div class="info-box">
    <strong>{helpText.title}</strong> &mdash; {helpText.body}
  </div>

  <!-- Toolbar -->
  <div class="toolbar">
    <select class="structure-filter" value={currentStructureId ?? ""} onchange={onStructureChange}>
      {#each structureGroups as [type, group] (type)}
        <optgroup label={structureGroupLabel(type)}>
          {#each group as s (s.id)}
            <option value={s.id}>{structureLabel(s)}</option>
          {/each}
        </optgroup>
      {/each}
    </select>

    <div class="toolbar-sep"></div>

    <div class="tab-group">
      <button class="tab-btn" class:active={currentTab === "fn"} onclick={() => switchTab("fn")}> Faux négatifs </button>
      <button class="tab-btn" class:active={currentTab === "fp"} onclick={() => switchTab("fp")}> Faux positifs </button>
    </div>
    <input type="search" placeholder="Rechercher dans les adresses..." bind:value={search} onkeydown={(e) => { if (e.key === 'Escape') { search = ''; onSearchInput(); } }} oninput={onSearchInput} />
    <ResultCount {list} one="adresse" many="adresses" />
  </div>

  <!-- Table -->
  <ListStatus {list} emptyText="Aucune adresse trouvée — la détection est parfaite pour ce cas !">
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
            <td class="addr-text">{a.raw_text}</td>
            <td class="num">{a.publication_count}</td>
            <td>
              {#if a.structures && a.structures.length > 0}
                {#each a.structures as l}
                  <span class={structDetectionClasses[structDetectionStatus(l)]} title={structTagTitle(l)}>
                    {structureLabel(l)}
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
                      <span class="form-struct">{structureLabel(f.structure)} &rarr;</span>
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

    <Pagination page={list.page} pages={list.pages} onchange={onPageChange} />
  </ListStatus>

  <!-- Context picker -->
  {#if ctxPicker}
    <div class="ctx-picker-inline" id="form-ctx-picker" style="top:{ctxPicker.y}px;left:{ctxPicker.x}px" onclick={(e) => e.stopPropagation()} onkeydown={(e) => { if (e.key === 'Escape') { e.preventDefault(); closeCtxPicker(); } }} role="dialog">
      <div class="picker-shortcuts">
        <button onclick={() => addCtxToForm("tutelles")}>{"\uD83D\uDD17"} tutelles</button>
      </div>
      <input type="text" placeholder="Rechercher une structure..." bind:value={ctxSearch} use:autofocus />
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
  h1 {
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
    border-radius: var(--radius);
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

  /* Toolbar */
  .toolbar {
    margin-bottom: 16px;
  }
  .structure-filter {
    padding: 6px 10px;
    border: 1px solid var(--accent);
    border-radius: var(--radius);
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--accent);
    background: var(--card);
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
    background: var(--card);
    font-size: 0.95rem;
    cursor: pointer;
    font-family: inherit;
  }
  .tab-btn:first-child {
    border-radius: var(--radius) 0 0 var(--radius);
  }
  .tab-btn:last-child {
    border-radius: 0 var(--radius) var(--radius) 0;
  }
  .tab-btn:not(:first-child) {
    border-left: none;
  }
  .tab-btn.active {
    background: var(--accent);
    color: white;
    border-color: var(--accent);
  }

  .toolbar input[type="search"] {
    width: 250px;
  }

  /* Table */
  .addr-text {
    font-family: var(--mono);
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
    border-radius: var(--radius-pill);
    font-weight: 500;
    margin: 1px 2px;
  }
  .struct-confirmed {
    background: var(--success-light);
    color: var(--success);
  }
  .struct-detected {
    background: var(--warning-light);
    color: var(--warning-text);
  }
  .struct-manual {
    background: var(--accent-light);
    color: var(--accent);
    border: 1px dashed color-mix(in srgb, var(--accent) 40%, white);
  }
  .struct-rejected {
    background: var(--surface);
    color: var(--muted);
    text-decoration: line-through;
  }

  /* Form info (FP tab) */
  .form-info {
    font-size: 0.8rem;
    margin-top: 4px;
    padding: 4px 8px;
    background: var(--warning-light);
    border: 1px solid color-mix(in srgb, var(--warning) 40%, white);
    border-radius: var(--radius);
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .form-struct {
    color: var(--muted);
  }
  .form-text {
    font-family: var(--mono);
    font-weight: 600;
    color: var(--warning-text);
  }
  .form-ctx {
    color: var(--muted);
  }
  .form-action {
    padding: 1px 6px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--card);
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
    background: var(--card);
    border: 1px solid var(--accent);
    border-radius: var(--radius);
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
  .picker-item:hover,
  .picker-item:focus-visible {
    background: var(--accent-light);
    outline: none;
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
    border-radius: var(--radius);
    background: var(--card);
    font-size: 0.8rem;
    cursor: pointer;
    font-family: inherit;
  }
  .picker-shortcuts button:hover {
    background: var(--accent-light);
  }
</style>
