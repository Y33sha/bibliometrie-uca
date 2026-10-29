<script lang="ts">
  import TableScroll from '#lib/components/TableScroll.svelte';
  import IconButton from "#lib/components/IconButton.svelte";
  import PageHeader from "#lib/components/PageHeader.svelte";
  import TabNav from "#lib/components/TabNav.svelte";
  import { page } from "$app/state";
  import { onMount } from "svelte";
  import { api, errorMessage, latestRequest, config as configApi, perimeters as perimetersApi } from "#lib/api/index.js";
  import { STRUCTURE_TYPES } from "#lib/structureTypes.js";
  import { structureLabel } from "#lib/structureLabels.js";
  import { confirmDialog, toast } from "#lib/dialogs.svelte.js";
  import Modal from "#lib/components/Modal.svelte";
  import Tooltip from "#lib/components/Tooltip.svelte";
  import { autofocus } from "#lib/actions/focus.js";
  import { applyBrandHue, defaultSiteTitle, institution, previewBrandHue } from "#lib/institution.svelte.js";
  import type { components } from "#lib/api/schema.js";

  type StructureListItem = components["schemas"]["StructureListItem"];
  type StructureListResponse = components["schemas"]["StructureListResponse"];

  type ConfigItem = components["schemas"]["ConfigItem"];

  // Rôles des périmètres : quel périmètre pilote chaque phase. Descriptions en langage utilisateur (schéma masqué), affichées en infobulle au survol du libellé.
  const PERIMETER_ROLES = [
    {
      key: "perimeter_extraction",
      label: "Extraction",
      hint: "Structures dont on moissonne les publications et qu'on reconnaît dans les affiliations des auteurs.",
    },
    {
      key: "perimeter_persons",
      label: "Publications et personnes",
      hint: "Une publication est retenue, et ses auteurs créés comme personnes, dès qu'au moins un auteur est affilié à l'une de ces structures.",
    },
  ];
  type PerimeterStructure = components["schemas"]["PerimeterStructureItem"];
  type Perimeter = components["schemas"]["PerimeterOut"];

  let configs: ConfigItem[] = $state([]);
  let perimeters: Perimeter[] = $state([]);
  let editingKey: string | null = $state(null);
  // Un champ numérique lié par `bind:value` renvoie un nombre, ou `null` vide.
  let editValue: string | number | null = $state("");
  let saving = $state(false);

  // Perimeter CRUD
  let perimModal: {
    mode: "create" | "edit";
    id: number | null;
    code: string;
    name: string;
    structSearch: string;
    structResults: any[];
    structure_ids: number[];
    structures: PerimeterStructure[];
  } | null = $state(null);

  function openPerimCreate() {
    perimModal = { mode: "create", id: null, code: "", name: "", structSearch: "", structResults: [], structure_ids: [], structures: [] };
  }

  function openPerimEdit(p: Perimeter) {
    perimModal = {
      mode: "edit",
      id: p.id,
      code: p.code,
      name: p.name,
      structSearch: "",
      structResults: [],
      structure_ids: [...p.root_structure_ids],
      structures: [...p.structures],
    };
  }

  async function savePerimeter() {
    if (!perimModal) return;
    try {
      if (perimModal.mode === "create") {
        await perimetersApi.create({
          code: perimModal.code,
          name: perimModal.name,
          root_structure_ids: perimModal.structure_ids,
        });
      } else {
        await perimetersApi.update(perimModal.id!, {
          name: perimModal.name,
          root_structure_ids: perimModal.structure_ids,
        });
      }
      perimModal = null;
      await load();
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  }

  async function deletePerimeter(id: number) {
    if (!(await confirmDialog({ message: "Supprimer ce périmètre ?", danger: true }))) return;
    try {
      await perimetersApi.remove(id);
      await load();
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  }

  // Chaque saisie relance la recherche : la requête précédente, encore en vol, est annulée.
  const structureSearch = latestRequest();

  async function perimSearchStructures() {
    if (!perimModal || perimModal.structSearch.length < 2) {
      if (perimModal) perimModal.structResults = [];
      return;
    }
    const found = await structureSearch<StructureListResponse>(`/api/structures?per_page=20&search=${encodeURIComponent(perimModal.structSearch)}`);
    perimModal.structResults = found.structures;
  }

  function perimAddStruct(s: any) {
    if (!perimModal || perimModal.structure_ids.includes(s.id)) return;
    perimModal.structure_ids = [...perimModal.structure_ids, s.id];
    perimModal.structures = [...perimModal.structures, { id: s.id, name: s.name, acronym: s.acronym, code: s.code }];
    perimModal.structSearch = "";
    perimModal.structResults = [];
  }

  function perimRemoveStruct(sid: number) {
    if (!perimModal) return;
    perimModal.structure_ids = perimModal.structure_ids.filter((id) => id !== sid);
    perimModal.structures = perimModal.structures.filter((s) => s.id !== sid);
  }

  /** Plafonds d'interrogation des API, dont le champ vidé retire la borne. */
  const CAPS = [
    { key: "fetch_missing_max_per_source", label: "Imports par DOI : max par source" },
    { key: "unpaywall_max_per_run", label: "Unpaywall" },
    { key: "sudoc_max_per_run", label: "Sudoc : revues vérifiées" },
  ];
  const CAP_KEYS = new Set(CAPS.map((cap) => cap.key));

  /** Délais au-delà desquels le pipeline interroge de nouveau une source, en jours. */
  const DELAYS = [
    { key: "fetch_stale_after_days", label: "Documents non revus" },
    { key: "fetch_missing_retry_after_days", label: "Recherches infructueuses" },
    { key: "unpaywall_recheck_after_days", label: "Statut open access (Unpaywall)" },
    { key: "doaj_refresh_after_days", label: "Fichier du DOAJ" },
  ];
  const DELAY_KEYS = new Set(DELAYS.map((delay) => delay.key));

  const MIN_YEAR = 1970;
  const MAX_YEAR = 2100;

  const activeTab = $derived(page.url.searchParams.get("tab") === "display" ? "display" : "pipeline");

  const SITE_TITLE_KEY = "site_title";
  /** Clés dont la valeur est un texte libre, enregistré tel quel. */
  const TEXT_KEYS = new Set([SITE_TITLE_KEY]);

  /** Bornes du champ pour une clé numérique, `null` pour les autres. */
  function numericBounds(key: string): { min: number; max: number } | null {
    if (CAP_KEYS.has(key)) return { min: 0, max: 10_000_000 };
    if (DELAY_KEYS.has(key)) return { min: 1, max: 3650 };
    if (key === "pipeline_start_year_full") return { min: MIN_YEAR, max: MAX_YEAR };
    return null;
  }

  /** Plafond d'interrogations : zéro retire la borne. */
  function capLabel(value: number): string {
    return value > 0 ? `${value.toLocaleString("fr-FR")} par run` : "Illimité";
  }

  function delayLabel(value: number): string {
    return `${value} jour${value > 1 ? "s" : ""}`;
  }

  function configByKey(key: string): ConfigItem | undefined {
    return configs.find((c) => c.key === key);
  }

  // Types de structure affichés sur la page publique des laboratoires (clé de config éditable).
  const labDisplayTypes = $derived.by(() => {
    const v = configByKey("laboratories_display_types")?.value;
    return Array.isArray(v) ? (v as string[]) : [];
  });

  const siteTitleItem = $derived(configByKey(SITE_TITLE_KEY));

  // Teinte : le curseur prévisualise sur toute l'interface, le relâchement enregistre.
  const BRAND_HUE_KEY = "brand_hue";
  const brandHueItem = $derived(configByKey(BRAND_HUE_KEY));
  let hueDraft = $state<number | null>(null);
  const hueShown = $derived(hueDraft ?? (typeof brandHueItem?.value === "number" ? brandHueItem.value : 196));
  // Spectre du curseur, plus clair et plus saturé que --accent pour que chaque teinte se reconnaisse.
  const hueSpectrum = `linear-gradient(to right, ${Array.from({ length: 13 }, (_, i) => `oklch(0.75 0.11 ${i * 30})`).join(", ")})`;

  async function saveBrandHue() {
    if (hueDraft === null) return;
    try {
      const saved = await configApi.setValue(BRAND_HUE_KEY, hueDraft);
      applyBrandHue(saved.value as number);
      await load();
    } catch (e) {
      toast("Erreur : " + errorMessage(e), "error");
      if (institution.brandHue !== null) previewBrandHue(institution.brandHue);
    }
    hueDraft = null;
  }

  async function toggleLabType(type: string) {
    const next = labDisplayTypes.includes(type) ? labDisplayTypes.filter((t) => t !== type) : [...labDisplayTypes, type];
    await configApi.setValue("laboratories_display_types", next);
    await load();
  }

  async function load() {
    configs = await api<ConfigItem[]>("/api/config");
    perimeters = await api<Perimeter[]>("/api/perimeters");
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

  function cancelEdit() {
    editingKey = null;
  }

  /** Entrée valide, Échap annule — sur tous les éditeurs inline de config. */
  function editKeydown(e: KeyboardEvent, key: string) {
    if (e.key === "Enter") {
      e.preventDefault();
      save(key);
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancelEdit();
    }
  }

  async function save(key: string) {
    saving = true;
    try {
      const text = String(editValue ?? "");
      let parsed;
      if (CAP_KEYS.has(key) && text.trim() === "") {
        parsed = 0;
      } else if (TEXT_KEYS.has(key)) {
        parsed = text;
      } else {
        try {
          parsed = JSON.parse(text);
        } catch {
          parsed = text;
        }
      }
      const saved = await configApi.setValue(key, parsed);
      if (key === SITE_TITLE_KEY) institution.title = (saved.value as string) || null;
      editingKey = null;
      await load();
    } catch (e) {
      toast("Erreur : " + errorMessage(e), "error");
    }
    saving = false;
  }

  onMount(load);
</script>

<PageHeader title="Configuration" />

<!-- Éditeur inline partagé par toutes les valeurs de configuration scalaires : focus + sélection à l'ouverture, Entrée valide, Échap annule. -->
{#snippet inlineEdit(key: string)}
  {@const bornes = numericBounds(key)}
  <input class="config-editor-inline" class:text={TEXT_KEYS.has(key)} bind:value={editValue} use:autofocus={{ select: true }}
    type={bornes ? "number" : "text"} min={bornes?.min} max={bornes?.max} step={bornes ? 1 : undefined}
    onkeydown={(e) => editKeydown(e, key)} />
  <span class="config-actions-inline">
    <button class="btn btn-sm btn-primary" onclick={() => save(key)} disabled={saving}>OK</button>
    <button class="btn btn-sm" onclick={cancelEdit}>Annuler</button>
  </span>
{/snippet}

<div class="config-page">
  <TabNav
    tabs={[
      { id: "pipeline", label: "Pipeline" },
      { id: "display", label: "Affichage" },
    ]}
  />

  {#if activeTab === "pipeline"}
  <!-- ═══ ANNÉES ═══ -->
  <h2 class="section-title">Options d'extraction</h2>
  <div class="config-grid">
    {#each ["pipeline_start_year_full"] as key}
      {@const item = configByKey(key)}
      {#if item}
        <div class="config-row">
          <span class="config-label">Année de début</span>
          {#if editingKey === key}
            {@render inlineEdit(key)}
          {:else}
            <span class="config-value-inline">{item.value}</span>
            <IconButton icon="edit" label="Modifier" onclick={() => startEdit(key)} />
          {/if}
        </div>
      {/if}
    {/each}
    {#each CAPS as cap (cap.key)}
      {@const item = configByKey(cap.key)}
      {#if item}
        <div class="config-row">
          <span class="config-label">{cap.label}</span>
          {#if editingKey === cap.key}
            {@render inlineEdit(cap.key)}
          {:else}
            <span class="config-value-inline">{typeof item.value === "number" ? capLabel(item.value) : item.value}</span>
            <IconButton icon="edit" label="Modifier" onclick={() => startEdit(cap.key)} />
          {/if}
        </div>
      {/if}
    {/each}
  </div>

  <!-- ═══ DÉLAIS ═══ -->
  <h2 class="section-title">Délais de réinterrogation</h2>
  <p class="info-box">Au-delà de ces délais, le pipeline interroge de nouveau la source.</p>
  <div class="config-grid">
    {#each DELAYS as delay (delay.key)}
      {@const item = configByKey(delay.key)}
      {#if item}
        <div class="config-row">
          <span class="config-label">{delay.label}</span>
          {#if editingKey === delay.key}
            {@render inlineEdit(delay.key)}
          {:else}
            <span class="config-value-inline">{typeof item.value === "number" ? delayLabel(item.value) : item.value}</span>
            <IconButton icon="edit" label="Modifier" onclick={() => startEdit(delay.key)} />
          {/if}
        </div>
      {/if}
    {/each}
  </div>

  <!-- ═══ PÉRIMÈTRES ═══ -->
  <h2 class="section-title">Périmètres</h2>

  <h3 class="subsection-title">Définition des périmètres</h3>
  <p class="info-box">Chaque périmètre est défini par une liste de structures racines. Les sous-structures en tutelle sont incluses récursivement.</p>
  <TableScroll>
    <table class="data-table perimeters-table">
      <thead>
        <tr>
          <th>Code</th>
          <th>Nom</th>
          <th class="perim-structs">Structures racines</th>
          <th class="num">Total</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {#each perimeters as perim (perim.id)}
          <tr>
            <td class="perim-code">{perim.code}</td>
            <td class="perim-name">{perim.name}</td>
            <td class="perim-structs">
              <div class="perimeter-rules">
                {#each perim.structures as struct (struct.id)}
                  <span class="tag">{structureLabel(struct)}</span>
                {/each}
              </div>
            </td>
            <td class="num">{perim.structure_count}</td>
            <td class="perim-actions">
              <IconButton icon="edit" label="Modifier le périmètre" onclick={() => openPerimEdit(perim)} />
              <IconButton icon="delete" label="Supprimer le périmètre" onclick={() => deletePerimeter(perim.id)} />
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </TableScroll>
  <div class="perim-new">
    <button class="btn btn-sm btn-primary" onclick={openPerimCreate}>+ Nouveau périmètre</button>
  </div>

  <h3 class="subsection-title">Rôle des périmètres</h3>
  <div class="config-grid">
    {#each PERIMETER_ROLES as role (role.key)}
      {@const item = configByKey(role.key)}
      {#if item}
        <div class="config-row">
          <span class="config-label">
            <Tooltip text={role.hint}><span class="role-phase">{role.label}</span></Tooltip>
          </span>
          <select
            class="select"
            aria-label="Périmètre : {role.label}"
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
        </div>
      {/if}
    {/each}
  </div>
  {:else}
  <div class="config-grid">
    {#if siteTitleItem}
      <div class="config-row">
        <span class="config-label">Titre de l'application</span>
        {#if editingKey === SITE_TITLE_KEY}
          {@render inlineEdit(SITE_TITLE_KEY)}
        {:else}
          {#if siteTitleItem.value}
            <span class="config-value-inline">{siteTitleItem.value}</span>
          {:else}
            <span class="config-value-inline default-value">{defaultSiteTitle()} (par défaut)</span>
          {/if}
          <IconButton icon="edit" label="Modifier" onclick={() => startEdit(SITE_TITLE_KEY)} />
        {/if}
      </div>
    {/if}
    {#if brandHueItem}
      <div class="config-row stacked">
        <label class="config-label" for="brand-hue">Teinte de l'interface</label>
        <div class="hue-control">
          <input
            id="brand-hue"
            class="hue-slider"
            type="range"
            min="0"
            max="359"
            step="1"
            value={hueShown}
            style:background={hueSpectrum}
            oninput={(e) => {
              hueDraft = Number((e.target as HTMLInputElement).value);
              previewBrandHue(hueDraft);
            }}
            onchange={saveBrandHue}
          />
          <span class="config-value-inline">{hueShown}°</span>
        </div>
      </div>
    {/if}
    <div class="config-row stacked">
      <span class="config-label">Types de structures affichés sur la page Laboratoires</span>
      <div class="type-checks">
        {#each STRUCTURE_TYPES as t (t.value)}
          <label class="type-check">
            <input type="checkbox" checked={labDisplayTypes.includes(t.value)} onchange={() => toggleLabType(t.value)} />
            {t.label}
          </label>
        {/each}
      </div>
    </div>
  </div>
  {/if}
</div>

{#if perimModal}
  <Modal title={perimModal.mode === "create" ? "Nouveau périmètre" : "Modifier le périmètre"} maxWidth="460px" onclose={() => (perimModal = null)}>
    <label>Code <input bind:value={perimModal.code} disabled={perimModal.mode === "edit"} placeholder="ex: alliance_uca" /></label>
    <label>Nom <input bind:value={perimModal.name} placeholder="ex: périmètre élargi" /></label>
    <label for="perim-struct-search">Structures racines</label>
    <div class="perimeter-rules" style="margin: 4px 0 8px;">
      {#each perimModal.structures as struct (struct.id)}
        <span class="tag">
          {structureLabel(struct)}
          <button class="remove" onclick={() => perimRemoveStruct(struct.id)}>x</button>
        </span>
      {/each}
    </div>
    <input id="perim-struct-search" type="search" placeholder="Rechercher une structure" bind:value={perimModal.structSearch} oninput={perimSearchStructures} autocomplete="off" />
    {#if perimModal.structResults.length > 0}
      <div class="perim-search-results">
        {#each perimModal.structResults.slice(0, 8) as s (s.id)}
          <button class="picker-item" onclick={() => perimAddStruct(s)}>
            {s.acronym ? s.acronym + " — " : ""}{s.name}
          </button>
        {/each}
      </div>
    {/if}
    {#snippet actions()}
      <button class="btn" onclick={() => (perimModal = null)}>Annuler</button>
      <button class="btn btn-primary" onclick={savePerimeter}>
        {perimModal?.mode === "create" ? "Créer" : "Enregistrer"}
      </button>
    {/snippet}
  </Modal>
{/if}

<style>
  .config-page {
    max-width: 800px;
    margin-inline: auto;
  }
  .section-title {
    margin: 24px 0 8px;
  }
  .perim-new {
    margin-top: 8px;
  }
  .info-box {
    margin: 4px 0 12px;
  }
  .subsection-title {
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--muted);
    margin: 16px 0 6px;
  }

  /* Une liste par section, réglages séparés par des filets. */
  .config-grid {
    display: flex;
    flex-direction: column;
    margin-bottom: 8px;
  }
  /* Libellé à gauche ; valeur et bouton au bord droit. Le bouton Annuler de l'édition prend la place du bouton de modification. */
  .config-row {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 44px;
    padding: 4px 0;
    border-bottom: 1px solid var(--border-subtle);
  }
  .config-row:last-child {
    border-bottom: none;
  }
  /* Contrôle trop large pour tenir à côté du libellé : il passe dessous. */
  .config-row.stacked {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
    padding: 12px 0;
  }
  .config-label {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-md);
  }
  .config-value-inline {
    font-size: var(--fs-md);
    font-variant-numeric: tabular-nums;
  }
  .config-editor-inline {
    width: 100px;
    font-family: var(--mono);
    font-size: var(--fs-sm);
    padding: 3px 6px;
    border: 1px solid var(--accent);
    border-radius: var(--radius);
  }
  .config-editor-inline.text {
    width: 320px;
    font-family: inherit;
  }
  .default-value {
    color: var(--muted);
  }
  .config-actions-inline {
    display: flex;
    gap: 4px;
  }

  .perimeters-table {
    margin-bottom: 10px;
  }
  .perimeters-table td {
    vertical-align: middle;
  }
  .perimeters-table td.num {
    color: var(--accent);
  }
  /* La colonne des structures racines absorbe la largeur disponible : les colonnes suivantes (Total, actions) se réduisent à leur contenu et se collent au bord droit. */
  .perimeters-table .perim-structs {
    width: 100%;
  }
  .perimeters-table .perimeter-rules {
    margin: 0;
  }
  .perim-code {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    color: var(--muted);
    white-space: nowrap;
  }
  .perim-name {
    font-weight: 600;
  }
  .perim-actions {
    text-align: right;
    white-space: nowrap;
  }
  .perim-actions .btn {
    margin-left: 4px;
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
    font-size: var(--fs-sm);
    padding: 2px 8px;
    border-radius: var(--radius-pill);
    background: var(--surface);
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
    border-radius: var(--radius);
    margin-top: 4px;
    max-height: 200px;
    overflow-y: auto;
    background: var(--card);
  }
  .picker-item {
    display: block;
    width: 100%;
    padding: 6px 10px;
    font-size: var(--fs-md);
    cursor: pointer;
    background: none;
    border: none;
    text-align: left;
    font-family: inherit;
  }
  .picker-item:hover {
    background: var(--accent-light);
  }
  /* Libellé de phase : le pointillé + le curseur d'aide signalent l'infobulle de description. */
  .role-phase {
    border-bottom: 1px dotted var(--muted);
    cursor: help;
  }
  .hue-control {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .hue-slider {
    flex: 1;
    height: 12px;
    border-radius: 6px;
    appearance: none;
    cursor: pointer;
  }
  .type-checks {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 16px;
  }
  .type-check {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: var(--fs-md);
    font-weight: 400;
    cursor: pointer;
  }
</style>
