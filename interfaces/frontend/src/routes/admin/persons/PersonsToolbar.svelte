<script lang="ts">
  import { autofocus } from "$lib/actions/focus";
  import FacetDropdown from "$lib/components/FacetDropdown.svelte";
  import type { FacetOption } from "$lib/components/FacetDropdown.svelte";
  import PresenceFilterToggle from "$lib/components/PresenceFilterToggle.svelte";
  import { IDENTIFIER_ITEMS, PENDING_ITEMS } from "$lib/filterItems";
  import { personExclusionLabels } from "$lib/labels";

  // `none` désigne les personnes retenues, comme dans le paramètre `exclusion` de l'API.
  const exclusionOptions: FacetOption[] = [
    { value: "none", text: "Retenue" },
    ...Object.entries(personExclusionLabels).map(([value, text]) => ({ value, text })),
  ];

  type IdState = "all" | "yes" | "no";

  let {
    search = $bindable(),
    selectedDepts = $bindable(),
    selectedRoles = $bindable(),
    selectedRh = $bindable(),
    selectedExclusions = $bindable(),
    idStates = $bindable(),
    pendingStates = $bindable(),
    deptOptions,
    roleOptions,
    rhOptions,
    idCounts,
    pendingCounts,
    totalCount,
    onsearch,
    onfilterchange,
  }: {
    search: string;
    selectedDepts: string[];
    selectedRoles: string[];
    selectedRh: string[];
    selectedExclusions: string[];
    idStates: Record<string, IdState>;
    pendingStates: Record<string, IdState>;
    deptOptions: FacetOption[];
    roleOptions: FacetOption[];
    rhOptions: FacetOption[];
    idCounts: Record<string, { yes: number; no: number }>;
    pendingCounts: Record<string, { yes: number; no: number }>;
    totalCount: number;
    onsearch: () => void;
    onfilterchange: () => void;
  } = $props();
</script>

<div class="toolbar">
  <input
    type="search"
    placeholder="Rechercher (nom, email)…"
    bind:value={search}
    use:autofocus
    onkeydown={(e) => { if (e.key === 'Escape') { search = ''; onsearch(); } }}
    oninput={onsearch}
  />
  <FacetDropdown
    label="Base RH"
    options={rhOptions}
    bind:selected={selectedRh}
    onchange={onfilterchange}
  />
  <FacetDropdown
    label="Département"
    options={deptOptions}
    searchable
    bind:selected={selectedDepts}
    onchange={onfilterchange}
  />
  <FacetDropdown
    label="Rôle"
    options={roleOptions}
    searchable
    bind:selected={selectedRoles}
    onchange={onfilterchange}
  />
  <PresenceFilterToggle
    label="Identifiants"
    items={IDENTIFIER_ITEMS}
    bind:states={idStates}
    counts={idCounts}
    onchange={onfilterchange}
  />
  <PresenceFilterToggle
    label="À confirmer"
    items={PENDING_ITEMS}
    bind:states={pendingStates}
    counts={pendingCounts}
    onchange={onfilterchange}
  />
  <FacetDropdown
    label="Exclusion"
    options={exclusionOptions}
    allLabel="Toutes"
    bind:selected={selectedExclusions}
    onchange={onfilterchange}
  />
  <span class="count">{totalCount} personnes</span>
</div>

<style>
  .toolbar {
    margin-bottom: 16px;
  }
  .toolbar input {
    width: 250px;
    background: white;
  }
</style>
