<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { base } from "$app/paths";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import { api, ApiError, nameForms, structures as structuresApi } from "$lib/api";
  import { confirmDialog, toast } from "$lib/dialogs.svelte";
  import {
    API_SOURCES,
    halCollectionUrl,
    rorFullUrl,
    rorShortId,
    type EditFormState,
    type NameForm,
    type Structure,
    type StructureDetail,
  } from "../types";
  import RelationsSection from "../RelationsSection.svelte";
  import NameFormsSection from "../NameFormsSection.svelte";
  import EditFormModal from "../EditFormModal.svelte";
  import StructureFormModal from "../StructureFormModal.svelte";

  /* ── State ── */

  const id = $derived(parseInt($page.params.id ?? ""));

  let allStructuresCache: Structure[] = $state([]);
  let detail = $state<StructureDetail | null>(null);

  // Relation picker state
  let relationPickerOpen = $state(false);
  let relationPickerSearch = $state("");
  let pickerRelType = $state("");
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

  const tutelles = $derived(
    detail ? detail.parents.filter((p) => p.relation_type === "est_tutelle_de") : [],
  );
  const tutellesDe = $derived(
    detail ? detail.children.filter((c) => c.relation_type === "est_tutelle_de") : [],
  );
  const partenaires = $derived.by(() => {
    if (!detail) return [];
    return [
      ...detail.parents
        .filter((p) => p.relation_type === "est_partenaire_de")
        .map((p) => ({ ...p, id_struct: p.id })),
      ...detail.children
        .filter((c) => c.relation_type === "est_partenaire_de")
        .map((c) => ({ ...c, id_struct: c.id })),
    ];
  });

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

  // Reload detail when navigating between /admin/structures/{id1} et /{id2}
  $effect(() => {
    if (!isNaN(id)) loadDetail();
  });

  /* ── Relation picker ── */

  function openPicker(relType: string, direction: string, structId: number) {
    pickerRelType = relType;
    pickerDirection = direction;
    pickerStructId = structId;
    relationPickerSearch = "";
    relationPickerOpen = true;
    ctxPickerOpen = false;
  }

  async function pickStructure(otherId: number) {
    const parentId = pickerDirection === "parent" ? otherId : pickerStructId!;
    const childId = pickerDirection === "parent" ? pickerStructId! : otherId;
    await structuresApi.createRelation({
      parent_id: parentId,
      child_id: childId,
      relation_type: pickerRelType,
    });
    relationPickerOpen = false;
    await loadDetail();
    refreshCache();
  }

  async function deleteRelation(relId: number) {
    await structuresApi.deleteRelation(relId);
    await loadDetail();
    refreshCache();
  }

  function selectRelatedStructure(otherId: number) {
    goto(`${base}/admin/structures/${otherId}`);
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
        is_word_boundary: addFormWordBoundary || text.length <= 6,
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
      is_word_boundary: editFormModal.is_word_boundary || text.length <= 6,
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
    requestAnimationFrame(() => {
      ctxPickerEl?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
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
    if (
      !(await confirmDialog({
        message: "Supprimer cette structure et toutes ses formes/relations ?",
        danger: true,
      }))
    )
      return;
    await structuresApi.remove(id);
    goto(`${base}/admin/structures`);
  }

  /* ── Edit modal ── */

  function normalizeRor(): boolean {
    let ror = mRor.trim();
    if (!ror) return true;
    if (/^0[a-z0-9]{8}$/.test(ror)) ror = "https://ror.org/" + ror;
    if (!/^https:\/\/ror\.org\/0[a-z0-9]{8}$/.test(ror)) {
      toast("Format ROR invalide. Attendu : https://ror.org/0xxxxxxxxx", "error");
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

  function buildApiIds(): Record<string, string[]> | null {
    const result: Record<string, string[]> = {};
    let hasAny = false;
    for (const src of API_SOURCES) {
      const raw = (mApiIds[src] || "").trim();
      if (raw) {
        result[src] = raw
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
        hasAny = true;
      }
    }
    return hasAny ? result : null;
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
    data.api_ids = buildApiIds();

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
      !target.classList.contains("btn-add-tiny")
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

<svelte:window
  onkeydown={(e) => {
    if (e.key === "Escape") {
      if (editFormModal) {
        editFormModal = null;
        e.preventDefault();
      } else if (editModalOpen) {
        editModalOpen = false;
        e.preventDefault();
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      if (editFormModal) {
        e.preventDefault();
        saveEditForm();
      } else if (editModalOpen) {
        e.preventDefault();
        submitEdit();
      }
    }
  }}
/>

<svelte:head>
  <title>Admin - Structure - Bibliométrie UCA</title>
</svelte:head>

<p class="back-link"><a href="{base}/admin/structures">← Retour aux structures</a></p>

{#if !detail}
  <p class="loading">Chargement…</p>
{:else}
  {@const s = detail.structure}
  <div class="panel">
    <div class="detail-header">
      <span class="type-badge type-{s.type}">{s.type}</span>
      <h2>
        {#if s.acronym}<strong>{s.acronym}</strong> · {s.name}{:else}{s.name}{/if}
      </h2>
      <button class="btn btn-sm" onclick={openEditModal}>Éditer</button>
      <button class="btn btn-danger btn-sm" onclick={deleteStructure}>Supprimer</button>
    </div>

    <h3 class="section-title">Détails</h3>
    <div class="details-inline">
      {#if s.ror_id}
        <span class="detail-item">
          <span class="detail-label">ROR</span>
          <a href={rorFullUrl(s.ror_id)} target="_blank" rel="noopener" class="id-badge"
            >{rorShortId(s.ror_id)}</a
          >
        </span>
      {/if}
      {#if s.rnsr_id}
        <span class="detail-item">
          <span class="detail-label">RNSR</span>
          <span>{s.rnsr_id}</span>
        </span>
      {/if}
      {#if s.hal_collection}
        <span class="detail-item">
          <span class="detail-label">Collection HAL</span>
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
        <span class="detail-label">Paramètres requête API :</span>
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
      {partenaires}
      {relationPickerOpen}
      {relationPickerResults}
      bind:relationPickerSearch
      bind:relationPickerEl
      onselect={selectRelatedStructure}
      ondeleteRelation={deleteRelation}
      onopenPicker={openPicker}
      onpickStructure={pickStructure}
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
  .loading {
    color: var(--muted);
  }

  .panel {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 14px;
  }
  .panel h2 {
    margin: 0 0 10px;
    font-size: 1.05rem;
    font-weight: 600;
  }

  .section-title {
    margin: 20px -14px 10px !important;
    padding: 6px 14px !important;
    background: #5b9ea0;
    color: white !important;
    font-size: 0.75rem !important;
    border-radius: 3px;
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
  .detail-label {
    color: var(--muted);
    font-weight: 500;
    font-size: 0.8rem;
  }

  .type-badge {
    font-size: 0.7rem;
    padding: 1px 6px;
    border-radius: 8px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    white-space: nowrap;
  }
  :global(.type-universite) {
    background: #e8d4f0;
    color: #6b2e8a;
  }
  :global(.type-onr) {
    background: #d4e8f0;
    color: #2e6b8a;
  }
  :global(.type-chu) {
    background: #f0d4d4;
    color: #8a2e2e;
  }
  :global(.type-ecole) {
    background: #f0e8d4;
    color: #8a6b2e;
  }
  :global(.type-labo) {
    background: var(--accent-light);
    color: var(--accent);
  }
  :global(.type-site) {
    background: var(--success-light);
    color: var(--success);
  }
  :global(.type-autre) {
    background: #f0f0f0;
    color: #555;
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
    font-size: 1.3rem;
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
