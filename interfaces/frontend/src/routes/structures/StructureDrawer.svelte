<script lang="ts">
  // Volet d'édition d'une structure, réservé à la session admin : identifiants, tutelles et formes de nom.
  import Drawer from "#lib/components/Drawer.svelte";
  import IconButton from "#lib/components/IconButton.svelte";
  import { onMount, onDestroy } from "svelte";
  import { resolve } from "$app/paths";
  import { api, ApiError, nameForms, structures as structuresApi } from "#lib/api/index.js";
  import { confirmDialog, toast } from "#lib/dialogs.svelte.js";
  import {
    API_SOURCES,
    ROR_FORMAT_ERROR,
    SHORT_FORM_MAX_LENGTH,
    buildApiIds,
    normalizeRorId,
    type EditFormState,
    type NameForm,
    type Structure,
    type StructureDetail,
  } from "./types";
  import type { components } from "#lib/api/schema.js";
  import RelationsSection from "./RelationsSection.svelte";
  import NameFormsSection from "./NameFormsSection.svelte";
  import EditFormModal from "./EditFormModal.svelte";
  import StructureFormModal from "./StructureFormModal.svelte";

  type StructureDeletionImpact = components["schemas"]["StructureDeletionImpact"];

  let {
    id,
    onclose,
    onchange,
    onopenStructure,
    ondeleted,
  }: {
    id: number;
    onclose: () => void;
    /** Appelé après une modification ou une suppression de la structure, pour que la page hôte recharge sa liste. */
    onchange: () => void;
    /** Ouvre le volet d'une autre structure. */
    onopenStructure: (id: number) => void;
    /** Appelé après la suppression de la structure, à la place de `onchange` et `onclose`. */
    ondeleted?: () => void;
  } = $props();

  /* ── State ── */

  let allStructuresCache: Structure[] = $state([]);
  let detail = $state<StructureDetail | null>(null);

  // Relation picker state
  let relationPickerOpen = $state(false);
  let relationPickerSearch = $state("");
  let pickerDirection = $state("");
  let pickerStructId: number | null = $state(null);
  let relationPickerEl: HTMLDivElement | undefined = $state();

  // Context picker state
  let ctxPickerOpen = $state(false);
  let ctxPickerSearch = $state("");
  let ctxPickerFormId: number | null = $state(null);
  let ctxPickerCurrentCtx: (number | string)[] = $state([]);
  let ctxPickerEl: HTMLDivElement | undefined = $state();

  // New form state
  let addFormText = $state("");
  let addFormWordBoundary = $state(false);
  let addFormExcluding = $state(false);
  let editFormModal: EditFormState | null = $state(null);
  let newFormCtx: (number | string)[] = $state([]);

  let formsHelpOpen = $state(false);

  // Edit modal state
  let editModalOpen = $state(false);
  let mCode = $state("");
  let mName = $state("");
  let mAcronym = $state("");
  let mType = $state("labo");
  let mRor = $state("");
  let mHal = $state("");
  let mApiIds: Record<string, string> = $state({});

  // Forms data lookup (for context editing)
  let formsData: Record<number, (number | string)[]> = $state({});

  // Related IDs set for picker exclusion
  let pickerExclude: Set<number> = $state(new Set());

  /* ── Derived ── */

  const structLookup = $derived.by(() => {
    const lookup: Record<number, string> = {};
    for (const s of allStructuresCache) {
      lookup[s.id] = s.acronym || s.code || s.name;
    }
    return lookup;
  });

  const relationPickerResults = $derived.by(() => {
    const q = relationPickerSearch.toLowerCase();
    return allStructuresCache
      .filter(
        (s) =>
          !pickerExclude.has(s.id) &&
          (s.name.toLowerCase().includes(q) ||
            (s.acronym || "").toLowerCase().includes(q) ||
            s.code.toLowerCase().includes(q)),
      )
      .slice(0, 12);
  });

  const ctxPickerResults = $derived.by(() => {
    const q = ctxPickerSearch.toLowerCase();
    const existing = new Set(ctxPickerCurrentCtx.map((x) => String(x)));
    return allStructuresCache
      .filter(
        (s) =>
          !existing.has(String(s.id)) &&
          (s.name.toLowerCase().includes(q) ||
            (s.acronym || "").toLowerCase().includes(q) ||
            s.code.toLowerCase().includes(q)),
      )
      .slice(0, 10);
  });

  const tutelles = $derived(detail ? detail.parents : []);
  const tutellesDe = $derived(detail ? detail.children : []);

  /* ── Data loading ── */

  async function refreshCache() {
    allStructuresCache = await api<Structure[]>("/api/structures/all");
  }

  async function loadDetail() {
    localStorage.setItem("admin_structure_id", String(id));
    const data = await api<StructureDetail>("/api/structures/" + id);
    detail = data;

    const fd: Record<number, (number | string)[]> = {};
    for (const f of data.forms) {
      fd[f.id] = f.requires_context_of || [];
    }
    formsData = fd;

    pickerExclude = new Set<number>([
      ...data.parents.map((p) => p.id),
      ...data.children.map((c) => c.id),
      data.structure.id,
    ]);

    relationPickerOpen = false;
    ctxPickerOpen = false;
    formsHelpOpen = false;
    newFormCtx = [];
  }

  // Charge le détail de la structure du volet.
  $effect(() => {
    if (!isNaN(id)) loadDetail();
  });

  /* ── Relation picker ── */

  function openPicker(direction: string, structId: number) {
    pickerDirection = direction;
    pickerStructId = structId;
    relationPickerSearch = "";
    relationPickerOpen = true;
    ctxPickerOpen = false;
  }

  async function pickStructure(otherId: number) {
    const parentId = pickerDirection === "parent" ? otherId : pickerStructId!;
    const childId = pickerDirection === "parent" ? pickerStructId! : otherId;
    await structuresApi.createTutelle({
      parent_id: parentId,
      child_id: childId,
    });
    relationPickerOpen = false;
    await loadDetail();
    refreshCache();
    onchange();
  }

  async function deleteTutelle(tutelleId: number) {
    await structuresApi.deleteTutelle(tutelleId);
    await loadDetail();
    refreshCache();
    onchange();
  }

  function selectRelatedStructure(otherId: number) {
    onopenStructure(otherId);
  }

  /* ── Forms ── */

  async function addForm(structId: number) {
    const text = addFormText.trim();
    if (!text) return;
    const ctx = newFormCtx.length ? newFormCtx : null;

    try {
      await nameForms.create({
        structure_id: structId,
        form_text: text,
        is_word_boundary: addFormWordBoundary || text.length <= SHORT_FORM_MAX_LENGTH,
        is_excluding: addFormExcluding,
        requires_context_of: ctx,
      });
    } catch (e) {
      if (e instanceof ApiError) {
        const detailMsg = (e.detail as { detail?: string })?.detail;
        toast(detailMsg || `Erreur ${e.status}`, "error");
        return;
      }
      toast((e as Error).message, "error");
      return;
    }
    addFormText = "";
    addFormWordBoundary = false;
    addFormExcluding = false;
    newFormCtx = [];
    await loadDetail();
  }

  async function deleteForm(formId: number) {
    if (!(await confirmDialog({ message: "Supprimer cette forme ?", danger: true }))) return;
    try {
      await nameForms.remove(formId);
    } catch (e) {
      const msg = e instanceof ApiError ? JSON.stringify(e.detail) : (e as Error).message;
      toast("Erreur suppression: " + msg, "error");
      return;
    }
    await loadDetail();
  }

  function openEditFormModal(f: NameForm) {
    editFormModal = {
      id: f.id,
      form_text: f.form_text,
      is_word_boundary: f.is_word_boundary,
      is_excluding: f.is_excluding,
    };
  }

  async function saveEditForm() {
    if (!editFormModal) return;
    const text = editFormModal.form_text.trim();
    await nameForms.update(editFormModal.id, {
      form_text: text,
      is_word_boundary: editFormModal.is_word_boundary || text.length <= SHORT_FORM_MAX_LENGTH,
      is_excluding: editFormModal.is_excluding,
    });
    editFormModal = null;
    await loadDetail();
  }

  /* ── Context picker ── */

  function openCtxPicker(formId: number | null) {
    const currentCtx = formId === null ? [...newFormCtx] : [...(formsData[formId] || [])];
    ctxPickerFormId = formId;
    ctxPickerCurrentCtx = currentCtx;
    ctxPickerSearch = "";
    ctxPickerOpen = true;
    relationPickerOpen = false;
  }

  async function pickCtx(item: number | string) {
    if (!ctxPickerCurrentCtx.includes(item)) {
      ctxPickerCurrentCtx = [...ctxPickerCurrentCtx, item];
    }
    ctxPickerOpen = false;

    if (ctxPickerFormId === null) {
      newFormCtx = [...ctxPickerCurrentCtx];
    } else {
      await nameForms.update(ctxPickerFormId, {
        requires_context_of: ctxPickerCurrentCtx,
      });
      await loadDetail();
    }
  }

  async function pickCtxClear() {
    ctxPickerOpen = false;

    if (ctxPickerFormId === null) {
      newFormCtx = [];
    } else {
      await nameForms.update(ctxPickerFormId, { requires_context_of: [] });
      await loadDetail();
    }
  }

  function pickCtxShortcutTutelles() {
    for (const t of tutelles) pickCtx(t.id);
  }

  async function removeCtx(formId: number, itemToRemove: number | string) {
    const currentCtx = formsData[formId] || [];
    const newCtx = currentCtx.filter((x) => x !== itemToRemove);
    await nameForms.update(formId, { requires_context_of: newCtx });
    await loadDetail();
  }

  function removeNewCtx(item: number | string) {
    newFormCtx = newFormCtx.filter((x) => x !== item);
  }

  function ctxLabel(x: number | string): string {
    return structLookup[x as number] || "id:" + x;
  }

  /* ── Delete structure ── */

  async function deleteStructure() {
    const impact = await api<StructureDeletionImpact>(
      `/api/structures/${id}/deletion-impact`,
    );
    const lines = [
      `${impact.name_forms} forme(s) de nom`,
      `${impact.tutelles} tutelle(s)`,
      `${impact.confirmed_links} lien(s) adresse-structure confirmé(s)`,
      `${impact.rejected_links} lien(s) adresse-structure rejeté(s)`,
    ];
    if (impact.perimeter_codes.length)
      lines.push(`racine des périmètres : ${impact.perimeter_codes.join(", ")}`);
    if (
      !(await confirmDialog({
        message: `Supprimer cette structure ? La suppression emporte :\n${lines.map((l) => `• ${l}`).join("\n")}`,
        danger: true,
      }))
    )
      return;
    await structuresApi.remove(id);
    if (ondeleted) {
      ondeleted();
      return;
    }
    onchange();
    onclose();
  }

  /* ── Edit modal ── */

  function normalizeRor(): boolean {
    const ror = normalizeRorId(mRor);
    if (ror === null) {
      toast(ROR_FORMAT_ERROR, "error");
      return false;
    }
    mRor = ror;
    return true;
  }

  function openEditModal() {
    if (!detail) return;
    const s = detail.structure;
    mCode = s.code || "";
    mName = s.name || "";
    mAcronym = s.acronym || "";
    mType = s.type || "labo";
    mRor = s.ror_id || "";
    mHal = s.hal_collection || "";
    mApiIds = {};
    for (const src of API_SOURCES) {
      mApiIds[src] = (s.api_ids?.[src] || []).join(", ");
    }
    editModalOpen = true;
  }

  async function submitEdit() {
    if (!normalizeRor()) return;
    const data: Record<string, any> = {};
    if (mName.trim()) data.name = mName.trim();
    if (mAcronym.trim() !== (detail?.structure.acronym || ""))
      data.acronym = mAcronym.trim() || null;
    if (mType) data.type = mType;
    if (mRor.trim() !== (detail?.structure.ror_id || "")) data.ror_id = mRor.trim() || null;
    if (mHal.trim() !== (detail?.structure.hal_collection || ""))
      data.hal_collection = mHal.trim() || null;
    data.api_ids = buildApiIds(mApiIds);

    try {
      await structuresApi.update(id, data);
      editModalOpen = false;
      await loadDetail();
      refreshCache();
      onchange();
    } catch (e: any) {
      const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
      toast("Erreur: " + msg, "error");
    }
  }

  // Échap ferme d'abord un sélecteur ouvert, puis le volet.
  function onescape() {
    if (relationPickerOpen) relationPickerOpen = false;
    else if (ctxPickerOpen) ctxPickerOpen = false;
    else onclose();
  }

  /* ── Click-outside handling ── */

  function handleDocumentClick(e: MouseEvent) {
    const target = e.target as HTMLElement;
    if (
      relationPickerOpen &&
      relationPickerEl &&
      !relationPickerEl.contains(target) &&
      !target.classList.contains("btn-add")
    ) {
      relationPickerOpen = false;
    }
    if (
      ctxPickerOpen &&
      ctxPickerEl &&
      !ctxPickerEl.contains(target) &&
      !target.classList.contains("btn-add")
    ) {
      ctxPickerOpen = false;
    }
  }

  /* ── Lifecycle ── */

  onMount(() => {
    refreshCache();
    document.addEventListener("click", handleDocumentClick);
  });

  onDestroy(() => {
    document.removeEventListener("click", handleDocumentClick);
  });
</script>

<Drawer width="600px" {onclose} {onescape}>
  {#snippet head()}
    {#if detail}
      {@const s = detail.structure}
      <div class="structure-head">
        <a class="drawer-name-link" href={resolve(`structures/${s.id}`)} target="_blank" rel="noopener" title="Voir la fiche publique">
          {#if s.acronym}<span class="drawer-acronym">{s.acronym}</span>{/if}
          {s.name}
        </a>
        <div class="drawer-head-actions">
          <IconButton icon="edit" label="Modifier la structure" onclick={openEditModal} />
          <IconButton icon="delete" label="Supprimer la structure" onclick={deleteStructure} />
        </div>
      </div>
    {/if}
  {/snippet}

  {#if !detail}
    <p class="loading">Chargement…</p>
  {:else}
    {@const s = detail.structure}
    <div class="drawer-meta">
      <span class="structure-type structure-type-{s.type}">{s.type}</span>
      <span><span class="field-label">Code</span> {s.code}</span>
    </div>
    {#if s.api_ids && Object.keys(s.api_ids).length}
      <div class="api-ids-display">
        <span class="field-label">Paramètres requête API&nbsp;:</span>
        {#each Object.entries(s.api_ids) as [src, ids]}
          <span class="api-id-item">
            <span class="api-id-source">{src}</span>
            {(ids as string[]).join(", ")}
          </span>
        {/each}
      </div>
    {/if}

    <RelationsSection
      structureId={s.id}
      {tutelles}
      {tutellesDe}
      {relationPickerOpen}
      {pickerDirection}
      {relationPickerResults}
      bind:relationPickerSearch
      bind:relationPickerEl
      onselect={selectRelatedStructure}
      ondeleteTutelle={deleteTutelle}
      onopenPicker={openPicker}
      onpickStructure={pickStructure}
      onclosePicker={() => (relationPickerOpen = false)}
    />

    <NameFormsSection
      structureId={s.id}
      forms={detail.forms}
      bind:formsHelpOpen
      bind:addFormText
      bind:addFormWordBoundary
      bind:addFormExcluding
      {newFormCtx}
      {ctxPickerOpen}
      {ctxPickerFormId}
      {ctxPickerResults}
      bind:ctxPickerSearch
      bind:ctxPickerEl
      {ctxLabel}
      onaddForm={addForm}
      oneditForm={openEditFormModal}
      ondeleteForm={deleteForm}
      onremoveCtx={removeCtx}
      onremoveNewCtx={removeNewCtx}
      onopenCtxPicker={openCtxPicker}
      onpickCtx={pickCtx}
      onpickCtxShortcutTutelles={pickCtxShortcutTutelles}
      onpickCtxClear={pickCtxClear}
      oncloseCtxPicker={() => (ctxPickerOpen = false)}
    />
  {/if}
</Drawer>

{#if editFormModal}
  <EditFormModal
    bind:state={editFormModal}
    onsave={saveEditForm}
    onclose={() => (editFormModal = null)}
  />
{/if}

{#if editModalOpen}
  <StructureFormModal
    editMode={true}
    bind:code={mCode}
    bind:name={mName}
    bind:acronym={mAcronym}
    bind:type={mType}
    bind:ror={mRor}
    bind:hal={mHal}
    bind:apiIds={mApiIds}
    onclose={() => (editModalOpen = false)}
    onsubmit={submitEdit}
  />
{/if}

<style>
  .loading {
    color: var(--muted);
  }
  .structure-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }
  .drawer-name-link {
    font-size: 1.1rem;
    color: inherit;
    text-decoration: none;
  }
  .drawer-name-link:hover {
    color: var(--accent);
    text-decoration: underline;
  }
  .drawer-acronym {
    font-weight: 600;
    margin-right: 6px;
  }
  .drawer-head-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }
  .drawer-meta {
    display: flex;
    align-items: center;
    gap: 14px;
    margin-bottom: 8px;
    font-size: 0.9rem;
  }
  .field-label {
    color: var(--muted);
    font-weight: 500;
    font-size: 0.8rem;
  }

  .api-ids-display {
    margin-top: 8px;
    font-size: 0.85rem;
    color: var(--muted);
    display: flex;
    flex-wrap: wrap;
    gap: 4px 12px;
    align-items: baseline;
  }
  .api-id-item {
    color: var(--text);
  }
  .api-id-source {
    font-weight: 600;
    text-transform: uppercase;
    font-size: 0.75rem;
    color: var(--muted);
  }
</style>
