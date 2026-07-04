<script lang="ts">
  import { onMount } from "svelte";
  import { autofocus } from "$lib/actions/focus";
  import { base } from "$app/paths";
  import { goto } from "$app/navigation";
  import { api, ApiError, structures as structuresApi } from "$lib/api";
  import { toast } from "$lib/dialogs.svelte";
  import { API_SOURCES, type StructureListItem, type Perimeter } from "./types";
  import StructureFormModal from "./StructureFormModal.svelte";

  let structures: StructureListItem[] = $state([]);
  let perimeters: Perimeter[] = $state([]);
  let search = $state("");
  let typeFilter = $state("");
  // "" = tous ; "none" = hors périmètre ; sinon id de périmètre (en chaîne).
  let perimeterFilter = $state("");
  let searchTimeout: ReturnType<typeof setTimeout> | null = null;

  // Affichage trié par acronyme (les structures sans acronyme retombent sur le nom),
  // comme la liste publique des laboratoires.
  const sorted = $derived(
    [...structures].sort((a, b) =>
      (a.acronym || a.name || "").localeCompare(b.acronym || b.name || "", "fr", {
        sensitivity: "base",
      }),
    ),
  );

  // Filtre d'appartenance à un périmètre, appliqué côté client sur la liste déjà chargée.
  const displayed = $derived.by(() => {
    if (perimeterFilter === "") return sorted;
    if (perimeterFilter === "none") return sorted.filter((s) => s.perimeter_ids.length === 0);
    const pid = Number(perimeterFilter);
    return sorted.filter((s) => s.perimeter_ids.includes(pid));
  });

  // Création modal
  let createModalOpen = $state(false);
  let mCode = $state("");
  let mName = $state("");
  let mAcronym = $state("");
  let mType = $state("labo");
  let mRor = $state("");
  let mHal = $state("");
  let mApiIds: Record<string, string> = $state({});

  async function loadList() {
    const params = new URLSearchParams();
    if (typeFilter) params.set("type", typeFilter);
    if (search) params.set("search", search);
    structures = await api<StructureListItem[]>("/api/structures?" + params);
  }

  function handleSearch() {
    if (searchTimeout) clearTimeout(searchTimeout);
    searchTimeout = setTimeout(loadList, 300);
  }

  function normalizeRor(): boolean {
    // Forme canonique stockée = ID court 9-char. On accepte une URL complète ou
    // un ID nu en saisie, mais on envoie toujours l'ID court (le backend
    // re-normalise de toute façon via le VO RorId).
    const ror = mRor.trim().replace(/^https?:\/\/ror\.org\//, "");
    if (!ror) return true;
    if (!/^0[a-z0-9]{8}$/.test(ror)) {
      toast("Format ROR invalide. Attendu : 0xxxxxxxxx (ou https://ror.org/0xxxxxxxxx)", "error");
      return false;
    }
    mRor = ror;
    return true;
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

  function openCreateModal() {
    mCode = "";
    mName = "";
    mAcronym = "";
    mType = "labo";
    mRor = "";
    mHal = "";
    mApiIds = {};
    for (const src of API_SOURCES) mApiIds[src] = "";
    createModalOpen = true;
  }

  async function submitCreate() {
    if (!normalizeRor()) return;
    const data: Record<string, any> = {
      code: mCode.trim(),
      name: mName.trim(),
      acronym: mAcronym.trim() || null,
      type: mType,
      ror_id: mRor.trim() || null,
      hal_collection: mHal.trim() || null,
      api_ids: buildApiIds(),
    };
    if (!data.code || !data.name) {
      toast("Code et nom requis", "error");
      return;
    }
    try {
      const created = (await structuresApi.create(data)) as { id: number };
      createModalOpen = false;
      goto(`${base}/admin/structures/${created.id}`);
    } catch (e: any) {
      const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
      toast("Erreur: " + msg, "error");
    }
  }

  onMount(async () => {
    await loadList();
    perimeters = await api<Perimeter[]>("/api/perimeters");
  });
</script>

<svelte:head>
  <title>Admin - Structures - Bibliométrie UCA</title>
</svelte:head>

<h2>Structures</h2>

<div class="toolbar">
  <input type="search" placeholder="Rechercher..." bind:value={search} use:autofocus onkeydown={(e) => { if (e.key === 'Escape') { search = ''; loadList(); } }} oninput={handleSearch} />
  <select bind:value={typeFilter} onchange={loadList}>
    <option value="">Tous types</option>
    <option value="labo">Laboratoires</option>
    <option value="universite">Universités</option>
    <option value="onr">ONR</option>
    <option value="chu">CHU</option>
    <option value="ecole">Écoles</option>
    <option value="site">Sites</option>
  </select>
  <select bind:value={perimeterFilter}>
    <option value="">Tous périmètres</option>
    <option value="none">— Hors périmètre —</option>
    {#each perimeters as p (p.id)}
      <option value={String(p.id)}>{p.name}</option>
    {/each}
  </select>
  <span class="count">{displayed.length} structures</span>
  <button class="btn btn-primary btn-sm" onclick={openCreateModal}>+ Nouvelle</button>
</div>

<div class="list">
  {#if displayed.length === 0}
    <div class="empty">Aucune structure</div>
  {:else}
    {#each displayed as s (s.id)}
      <a
        class="struct-item"
        class:orphan={s.perimeter_ids.length === 0}
        href="{base}/admin/structures/{s.id}"
      >
        <span class="type-badge type-{s.type}">{s.type}</span>
        <span class="name">
          {#if s.acronym}<strong>{s.acronym}</strong> · {s.name}{:else}{s.name}{/if}
        </span>
      </a>
    {/each}
  {/if}
</div>

{#if createModalOpen}
  <StructureFormModal
    editMode={false}
    bind:code={mCode}
    bind:name={mName}
    bind:acronym={mAcronym}
    bind:type={mType}
    bind:ror={mRor}
    bind:hal={mHal}
    bind:apiIds={mApiIds}
    onclose={() => (createModalOpen = false)}
    onsubmit={submitCreate}
  />
{/if}

<style>
  h2 {
    margin: 0 0 12px;
    font-size: 1.2rem;
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
  }
  .toolbar input,
  .toolbar select {
    padding: 5px 8px;
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 0.95rem;
    background: white;
    font-family: inherit;
  }
  .toolbar input {
    flex: 1;
    max-width: 360px;
  }
  .count {
    margin-left: auto;
    margin-right: 8px;
    font-size: 0.85rem;
    color: var(--muted);
  }
  .list {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
  }
  .empty {
    padding: 20px;
    text-align: center;
    color: var(--muted);
  }
  .struct-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-subtle);
    text-decoration: none;
    color: inherit;
  }
  .struct-item:last-child {
    border-bottom: none;
  }
  .struct-item:hover {
    background: var(--surface-hover);
  }
  /* Structures n'appartenant à aucun périmètre : légèrement estompées. */
  .struct-item.orphan {
    opacity: 0.55;
  }
  .struct-item.orphan:hover {
    opacity: 1;
  }
  .struct-item .name {
    font-size: 0.95rem;
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
</style>
