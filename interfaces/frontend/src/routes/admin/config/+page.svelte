<script lang="ts">
  import { onMount } from "svelte";
  import { base } from "$app/paths";
  import { api, ApiError, config as configApi, perimeters as perimetersApi } from "$lib/api";

  interface ConfigItem {
    key: string;
    value: any;
    description: string | null;
    updated_at: string;
  }
  interface PerimeterStructure {
    id: number;
    name: string;
    acronym: string | null;
    code: string;
  }
  interface Perimeter {
    id: number;
    code: string;
    name: string;
    description: string | null;
    structure_ids: number[];
    structures: PerimeterStructure[];
    structure_count: number;
  }
  interface HalCollections {
    collections: Record<string, string>;
    count: number;
  }

  let configs: ConfigItem[] = $state([]);
  let perimeters: Perimeter[] = $state([]);
  let halCollections: HalCollections = $state({ collections: {}, count: 0 });
  let editingKey: string | null = $state(null);
  let editValue = $state("");
  let saving = $state(false);

  // Perimeter CRUD
  let perimModal: {
    mode: 'create' | 'edit';
    id: number | null;
    code: string;
    name: string;
    description: string;
    structSearch: string;
    structResults: any[];
    structure_ids: number[];
    structures: PerimeterStructure[];
  } | null = $state(null);

  function openPerimCreate() {
    perimModal = { mode: 'create', id: null, code: '', name: '', description: '',
                   structSearch: '', structResults: [], structure_ids: [], structures: [] };
  }

  function openPerimEdit(p: Perimeter) {
    perimModal = { mode: 'edit', id: p.id, code: p.code, name: p.name,
                   description: p.description || '',
                   structSearch: '', structResults: [],
                   structure_ids: [...p.structure_ids],
                   structures: [...p.structures] };
  }

  function extractDetail(e: unknown): string {
    if (e instanceof ApiError) {
      const d = (e.detail as { detail?: string })?.detail;
      return d || `Erreur ${e.status}`;
    }
    return (e as Error)?.message || 'Erreur';
  }

  async function savePerimeter() {
    if (!perimModal) return;
    try {
      if (perimModal.mode === 'create') {
        const { id } = await perimetersApi.create({
          code: perimModal.code,
          name: perimModal.name,
          description: perimModal.description,
        });
        for (const sid of perimModal.structure_ids) {
          await perimetersApi.addStructure(id, sid);
        }
      } else {
        await perimetersApi.update(perimModal.id!, {
          name: perimModal.name,
          description: perimModal.description,
          structure_ids: perimModal.structure_ids,
        });
      }
      perimModal = null;
      await load();
    } catch (e) { alert(extractDetail(e)); }
  }

  async function deletePerimeter(id: number) {
    if (!confirm('Supprimer ce périmètre ?')) return;
    try {
      await perimetersApi.remove(id);
      await load();
    } catch (e) { alert(extractDetail(e)); }
  }

  async function perimSearchStructures() {
    if (!perimModal || perimModal.structSearch.length < 2) {
      if (perimModal) perimModal.structResults = [];
      return;
    }
    perimModal.structResults = await api<any[]>(`/api/structures?search=${encodeURIComponent(perimModal.structSearch)}`);
  }

  function perimAddStruct(s: any) {
    if (!perimModal || perimModal.structure_ids.includes(s.id)) return;
    perimModal.structure_ids = [...perimModal.structure_ids, s.id];
    perimModal.structures = [...perimModal.structures, { id: s.id, name: s.name, acronym: s.acronym, code: s.code }];
    perimModal.structSearch = '';
    perimModal.structResults = [];
  }

  function perimRemoveStruct(sid: number) {
    if (!perimModal) return;
    perimModal.structure_ids = perimModal.structure_ids.filter(id => id !== sid);
    perimModal.structures = perimModal.structures.filter(s => s.id !== sid);
  }


  function currentYear(): number {
    return new Date().getFullYear();
  }

  function computeYears(offset: number): string {
    const y = currentYear();
    return Array.from({ length: offset + 1 }, (_, i) => y - offset + i).join(", ");
  }

  function configByKey(key: string): ConfigItem | undefined {
    return configs.find((c) => c.key === key);
  }

  async function load() {
    configs = await api<ConfigItem[]>("/api/config");
    perimeters = await api<Perimeter[]>("/api/perimeters");
    halCollections = await api<HalCollections>("/api/config/hal-collections");
  }

  function startEdit(key: string) {
    const item = configByKey(key);
    if (!item) return;
    editingKey = key;
    if (typeof item.value === "string") {
      editValue = item.value;
    } else {
      editValue = JSON.stringify(item.value, null, typeof item.value === "object" ? 2 : undefined);
    }
  }

  async function save(key: string) {
    saving = true;
    try {
      let parsed;
      try {
        parsed = JSON.parse(editValue);
      } catch {
        parsed = editValue;
      }
      await configApi.setValue(key, parsed);
      editingKey = null;
      await load();
    } catch (e) {
      alert("Erreur : " + extractDetail(e));
    }
    saving = false;
  }

  onMount(load);
</script>

<svelte:head><title>Configuration — Bibliométrie UCA</title></svelte:head>

<h2>Configuration du pipeline</h2>
<p class="subtitle">Les modifications prennent effet au prochain lancement du pipeline.</p>

<!-- ═══ API ═══ -->
<h3 class="section-title">API</h3>
<div class="config-grid">
  {#each ["openalex_api_key", "openalex_email", "wos_api_key", "scanr_username", "scanr_password"] as key}
    {@const isSecret = key === "wos_api_key" || key === "scanr_password" || key === "openalex_api_key"}
    {#if configByKey(key)}
      <div class="config-row">
        <span class="config-label"
          >{key === "openalex_api_key"
            ? "OpenAlex — Clé API"
            : key === "openalex_email"
            ? "OpenAlex — Email (fallback)"
            : key === "wos_api_key"
              ? "WoS — Clé API"
              : key === "scanr_username"
                ? "ScanR — Identifiant"
                : key === "scanr_password"
                  ? "ScanR — Mot de passe"
                  : key}</span
        >
        {#if editingKey === key}
          <input
            class="config-editor-inline"
            style="width: 300px;"
            bind:value={editValue}
            onkeydown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                save(key);
              }
            }}
          />
          <span class="config-actions-inline">
            <button class="btn btn-sm btn-primary" onclick={() => save(key)} disabled={saving}>OK</button>
            <button
              class="btn btn-sm"
              onclick={() => {
                editingKey = null;
              }}>Annuler</button
            >
          </span>
        {:else}
          <span class="config-value-inline">{isSecret ? "••••••••" : configByKey(key)?.value || "(non défini)"}</span>
          <button class="btn btn-sm" onclick={() => startEdit(key)}>Modifier</button>
        {/if}
      </div>
    {/if}
  {/each}
</div>

<!-- ═══ ANNÉES ═══ -->
<h3 class="section-title">Années d'extraction</h3>
<div class="config-grid">
  {#each ["pipeline_years_full", "pipeline_years_weekly"] as key}
    {@const item = configByKey(key)}
    {#if item}
      <div class="config-row">
        <span class="config-label">{key === "pipeline_years_full" ? "Mode full / monthly" : "Mode weekly"}</span>
        {#if editingKey === key}
          <input
            class="config-editor-inline"
            bind:value={editValue}
            onkeydown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                save(key);
              }
            }}
          />
          <button class="btn btn-sm btn-primary" onclick={() => save(key)} disabled={saving}>OK</button>
          <button
            class="btn btn-sm"
            onclick={() => {
              editingKey = null;
            }}>Annuler</button
          >
        {:else}
          <span class="config-value-inline"
            >{typeof item.value === "number" ? `Année en cours${item.value > 0 ? ` + ${item.value} an${item.value > 1 ? "s" : ""}` : ""} → ${computeYears(item.value)}` : item.value}</span
          >
          <button class="btn btn-sm" onclick={() => startEdit(key)}>Modifier</button>
        {/if}
      </div>
    {/if}
  {/each}
</div>

<!-- ═══ PÉRIMÈTRES ═══ -->
<h3 class="section-title">Périmètres</h3>

<h4 class="subsection-title">Définition des périmètres</h4>
<p class="help-text">Chaque périmètre est défini par une liste de structures racines. Les sous-structures en tutelle sont incluses récursivement.</p>
{#each perimeters as perim (perim.id)}
  <div class="perimeter-card">
    <div class="perimeter-header">
      <strong>{perim.name}</strong>
      <span class="perimeter-code">{perim.code}</span>
      <span class="perimeter-count">{perim.structure_count} structures</span>
      <span style="margin-left:auto; display:flex; gap:4px;">
        <button class="btn btn-sm" onclick={() => openPerimEdit(perim)}>Modifier</button>
        <button class="btn btn-sm btn-danger" onclick={() => deletePerimeter(perim.id)}>Supprimer</button>
      </span>
    </div>
    {#if perim.description}
      <p class="perimeter-desc">{perim.description}</p>
    {/if}
    <div class="perimeter-rules">
      {#each perim.structures as struct (struct.id)}
        <span class="tag">{struct.acronym || struct.name}</span>
      {/each}
    </div>
  </div>
{/each}
<button class="btn btn-sm" style="margin: 0 auto; display:block; max-width:800px;" onclick={openPerimCreate}>+ Nouveau périmètre</button>

<h4 class="subsection-title">Rôle des périmètres</h4>
<div class="config-grid">
  {#each [
    { key: "perimeter_extraction", label: "Phase extraction", hint: "Structures interrogées par les API (identifiants dans api_ids + collections HAL)" },
    { key: "perimeter_affiliations", label: "Phase affiliations", hint: "Résolution structure_ids sur les authorships sources" },
    { key: "perimeter_persons", label: "Phases publications + persons", hint: "Détermine in_perimeter : seuls les documents avec au moins une authorship in_perimeter génèrent des publications et des personnes" },
  ] as role}
    {@const item = configByKey(role.key)}
    {#if item}
      <div class="config-row" style="flex-wrap: wrap;">
        <span class="config-label">{role.label}</span>
        <select
          class="config-select"
          value={item.value}
          onchange={async (e) => {
            const target = e.target as HTMLSelectElement;
            try {
              await configApi.setValue(role.key, target.value);
              await load();
            } catch {}
          }}
        >
          {#each perimeters as p (p.id)}
            <option value={p.code}>{p.name} ({p.code})</option>
          {/each}
        </select>
        <span class="config-hint" style="width: 100%;">{role.hint}</span>
      </div>
    {/if}
  {/each}
</div>

<!-- ═══ HAL ═══ -->
<h3 class="section-title">HAL</h3>
<div class="config-grid">
  {#each [{ key: "hal_extra_collections", label: "Collections supplémentaires" }] as field}
    {@const item = configByKey(field.key)}
    {#if item}
      <div class="config-row">
        <span class="config-label">{field.label}</span>
        {#if editingKey === field.key}
          <input class="config-editor-inline" bind:value={editValue} onkeydown={(e) => { if (e.key === "Enter") { e.preventDefault(); save(field.key); } }} />
          <span class="config-actions-inline">
            <button class="btn btn-sm btn-primary" onclick={() => save(field.key)} disabled={saving}>OK</button>
            <button class="btn btn-sm" onclick={() => { editingKey = null; }}>Annuler</button>
          </span>
        {:else}
          <span class="config-value-inline">{Array.isArray(item.value) && item.value.length ? item.value.join(", ") : "(aucune)"}</span>
          <button class="btn btn-sm" onclick={() => startEdit(field.key)}>Modifier</button>
        {/if}
      </div>
    {/if}
  {/each}
  <div class="config-row" style="flex-wrap: wrap;">
    <span class="config-label">Collections (périmètre)</span>
    <div class="hal-coll-list">
      {#each Object.entries(halCollections.collections) as [code, label]}
        <span class="hal-coll-tag">{code} <span class="hal-coll-label">({label})</span></span>
      {/each}
      {#if Object.keys(halCollections.collections).length === 0}
        <span class="none-text">Aucune collection</span>
      {/if}
    </div>
    <span class="config-hint">Dérivées des structures du périmètre ayant un champ "Collection HAL" renseigné (<a href="{base}/admin/structures">structures</a>).</span>
  </div>
</div>

{#if perimModal}
<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
<div class="modal-bg" onclick={() => perimModal = null}>
  <!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
  <div class="modal" onclick={(e) => e.stopPropagation()}>
    <h3>{perimModal.mode === 'create' ? 'Nouveau périmètre' : 'Modifier le périmètre'}</h3>
    <label>Code</label>
    <input bind:value={perimModal.code} disabled={perimModal.mode === 'edit'} placeholder="ex: uca_wide" />
    <label>Nom</label>
    <input bind:value={perimModal.name} placeholder="ex: UCA large" />
    <label>Description</label>
    <input bind:value={perimModal.description} />
    <label>Structures racines</label>
    <div class="perimeter-rules" style="margin: 4px 0 8px;">
      {#each perimModal.structures as struct (struct.id)}
        <span class="tag">
          {struct.acronym || struct.name}
          <button class="remove" onclick={() => perimRemoveStruct(struct.id)}>x</button>
        </span>
      {/each}
    </div>
    <input type="text" placeholder="Rechercher une structure..." bind:value={perimModal.structSearch}
      oninput={perimSearchStructures} autocomplete="off" />
    {#if perimModal.structResults.length > 0}
      <div class="perim-search-results">
        {#each perimModal.structResults.slice(0, 8) as s (s.id)}
          <button class="picker-item" onclick={() => perimAddStruct(s)}>
            {s.acronym ? s.acronym + ' — ' : ''}{s.name}
          </button>
        {/each}
      </div>
    {/if}
    <div class="modal-actions">
      <button class="btn" onclick={() => perimModal = null}>Annuler</button>
      <button class="btn btn-primary" onclick={savePerimeter}>
        {perimModal.mode === 'create' ? 'Créer' : 'Enregistrer'}
      </button>
    </div>
  </div>
</div>
{/if}

<style>
  h2 {
    font-size: 1.2rem;
    font-weight: 600;
    margin: 0 auto 4px;
    max-width: 800px;
  }
  .subtitle {
    color: var(--muted);
    font-size: 0.9rem;
    margin: 0 auto 20px;
    max-width: 800px;
  }
  .section-title {
    margin: 24px auto 8px;
    padding: 4px 10px;
    background: none;
    color: #5b9ea0;
    font-size: 0.8rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 2px solid #5b9ea0;
    max-width: 800px;
  }
  .help-text {
    background: var(--accent-light);
    border: 1px solid #c4d8ed;
    border-radius: 5px;
    padding: 8px 12px;
    margin: 4px auto 12px;
    max-width: 800px;
    font-size: 0.85rem;
    color: #2c3e50;
    line-height: 1.5;
  }
  .subsection-title {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--muted);
    margin: 16px auto 6px;
    max-width: 800px;
  }

  .config-grid {
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-width: 800px;
    margin: 0 auto 8px;
  }
  .config-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 5px;
  }
  .config-label {
    font-weight: 600;
    font-size: 0.9rem;
    min-width: 180px;
  }
  .config-value-inline {
    font-size: 0.9rem;
    flex: 1;
  }
  .config-editor-inline {
    width: 80px;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.85rem;
    padding: 3px 6px;
    border: 1px solid var(--accent);
    border-radius: 3px;
    flex: 1;
  }
  .config-actions-inline {
    display: flex;
    gap: 4px;
    margin-left: auto;
  }

  .hal-coll-list {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-bottom: 8px;
  }
  .hal-coll-tag {
    font-size: 0.8rem;
    padding: 2px 8px;
    background: #e8f0e8;
    color: #2e6b2e;
    border-radius: 10px;
  }
  .hal-coll-label {
    color: #555;
  }

  .perimeter-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px 16px;
    margin: 0 auto 10px;
    max-width: 800px;
  }
  .perimeter-header {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .perimeter-code {
    font-size: 0.75rem;
    color: var(--muted);
    font-family: monospace;
  }
  .perimeter-count {
    font-size: 0.8rem;
    color: var(--accent);
    margin-left: auto;
  }
  .perimeter-desc {
    font-size: 0.85rem;
    color: var(--muted);
    margin: 4px 0 8px;
  }
  .perimeter-rules {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin: 6px 0;
  }
  .tag {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.85rem;
    padding: 2px 8px;
    border-radius: 10px;
    background: #f0f0f0;
  }

  .remove {
    cursor: pointer;
    color: var(--danger);
    font-weight: bold;
    background: none;
    border: none;
    padding: 0;
    font-family: inherit;
  }
  .perim-search-results {
    border: 1px solid var(--border);
    border-radius: 4px;
    margin-top: 4px;
    max-height: 200px;
    overflow-y: auto;
    background: white;
  }
  .picker-item {
    display: block;
    width: 100%;
    padding: 6px 10px;
    font-size: 0.9rem;
    cursor: pointer;
    background: none;
    border: none;
    text-align: left;
    font-family: inherit;
  }
  .picker-item:hover {
    background: var(--accent-light);
  }
  .config-hint {
    font-size: 0.8rem;
    color: var(--muted);
    width: 100%;
    margin-top: 4px;
  }
  .config-select {
    padding: 3px 6px;
    font-size: 0.9rem;
    font-family: inherit;
    border: 1px solid var(--border);
    border-radius: 3px;
  }
  .config-hint a {
    color: var(--accent);
  }
  .none-text {
    font-size: 0.85rem;
    color: var(--muted);
  }
</style>
