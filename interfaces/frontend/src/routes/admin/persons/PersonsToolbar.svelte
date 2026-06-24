<script lang="ts">
  import { autofocus } from "$lib/actions/focus";
  import FacetDropdown from "$lib/components/FacetDropdown.svelte";
  import type { FacetOption } from "$lib/components/FacetDropdown.svelte";
  import PresenceFilterToggle from "$lib/components/PresenceFilterToggle.svelte";
  import { IDENTIFIER_ITEMS } from "$lib/filterItems";

  type IdState = "all" | "yes" | "no";

  let {
    search = $bindable(),
    selectedDepts = $bindable(),
    selectedRoles = $bindable(),
    selectedRh = $bindable(),
    idStates = $bindable(),
    deptOptions,
    roleOptions,
    rhOptions,
    idCounts,
    totalCount,
    onsearch,
    onfilterchange,
  }: {
    search: string;
    selectedDepts: string[];
    selectedRoles: string[];
    selectedRh: string[];
    idStates: Record<string, IdState>;
    deptOptions: FacetOption[];
    roleOptions: FacetOption[];
    rhOptions: FacetOption[];
    idCounts: Record<string, { yes: number; no: number }>;
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
