<script lang="ts">
  import Breadcrumb from "#lib/components/Breadcrumb.svelte";
  import IconButton from "#lib/components/IconButton.svelte";
  import { pageTitle } from "#lib/institution.svelte.js";
  import { onMount, onDestroy } from "svelte";
  import { resolve } from "$app/paths";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { api, ApiError, nameForms, structures as structuresApi } from "#lib/api/index.js";
  import { rorFullUrl, rorShortId } from "#lib/utils.js";
  import { confirmDialog, toast } from "#lib/dialogs.svelte.js";
  import {
    API_SOURCES,
    ROR_FORMAT_ERROR,
    SHORT_FORM_MAX_LENGTH,
    buildApiIds,
    halCollectionUrl,
    normalizeRorId,
    type EditFormState,
    type NameForm,
    type Structure,
    type StructureDetail,
  } from "../types";
  import type { components } from "#lib/api/schema.js";
  import RelationsSection from "../RelationsSection.svelte";
  import NameFormsSection from "../NameFormsSection.svelte";
  import EditFormModal from "../EditFormModal.svelte";
  import StructureFormModal from "../StructureFormModal.svelte";

  type StructureDeletionImpact = components["schemas"]["StructureDeletionImpact"];

  /* ── State ── */

  const id = $derived(parseInt(page.params.id ?? ""));

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
    allStructuresCache = await api<Structure[]>("/api/structures");
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

  // Charge le détail de la structure de l'identifiant de la page.
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
  }

  async function deleteTutelle(tutelleId: number) {
    await structuresApi.deleteTutelle(tutelleId);
    await loadDetail();
    refreshCache();
  }

  function selectRelatedStructure(otherId: number) {
    goto(resolve(`admin/structures/${otherId}`));
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
    goto(resolve('admin/structures'));
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
    } catch (e: any) {
      const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
      toast("Erreur: " + msg, "error");
    }
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

<svelte:head>
  <title>{pageTitle("Admin - Structure")}</title>
</svelte:head>

<Breadcrumb trail={[{ label: "Structures", href: resolve("admin/structures") }]} current={detail?.structure.acronym || detail?.structure.name} />

{#if !detail}
  <p class="loading">Chargement…</p>
{:else}
  {@const s = detail.structure}
  <div>
    <div class="detail-header">
      <span class="structure-type structure-type-{s.type}">{s.type}</span>
      <h2>
        {#if s.acronym}<strong>{s.acronym}</strong> <span class="name-separator">·</span> {s.name}{:else}{s.name}{/if}
      </h2>
      <IconButton icon="edit" label="Modifier la structure" onclick={openEditModal} />
      <IconButton icon="delete" label="Supprimer la structure" onclick={deleteStructure} />
    </div>

    <h3 class="section-title">Détails</h3>
    <div class="details-inline">
      {#if s.ror_id}
        <span class="detail-item">
          <span class="field-label">ROR</span>
          <a href={rorFullUrl(s.ror_id)} target="_blank" rel="noopener" class="id-badge"
            >{rorShortId(s.ror_id)}</a
          >
        </span>
      {/if}
      {#if s.rnsr_id}
        <span class="detail-item">
          <span class="field-label">RNSR</span>
          <span>{s.rnsr_id}</span>
        </span>
      {/if}
      {#if s.hal_collection}
        <span class="detail-item">
          <span class="field-label">Collection HAL</span>
          <a
            href={halCollectionUrl(s.hal_collection)}
            target="_blank"
            rel="noopener"
            class="id-badge">{s.hal_collection}</a
          >
        </span>
      {/if}
    </div>
    {#if s.api_ids && Object.keys(s.api_ids).length}
      <div class="api-ids-display">
        <span class="field-label">Paramètres requête API :</span>
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
  </div>
{/if}

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

  .details-inline {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    margin-bottom: 8px;
    font-size: 0.9rem;
  }
  .detail-item {
    display: flex;
    align-items: center;
    gap: 5px;
  }
  .field-label {
    color: var(--muted);
    font-weight: 500;
    font-size: 0.8rem;
  }


  .detail-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 14px;
  }
  .detail-header h2 {
    flex: 1;
    margin: 0;
    font-size: 1.6rem;
    font-weight: 500;
    line-height: 1.25;
    letter-spacing: -0.01em;
  }
  .detail-header h2 strong {
    font-weight: 700;
  }
  .name-separator {
    color: var(--muted);
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
