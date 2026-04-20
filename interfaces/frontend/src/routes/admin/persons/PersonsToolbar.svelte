<script lang="ts">
  import FacetDropdown from "$lib/components/FacetDropdown.svelte";
  import type { FacetOption } from "$lib/components/FacetDropdown.svelte";

  let {
    search = $bindable(),
    selectedDepts = $bindable(),
    selectedRoles = $bindable(),
    selectedLinked = $bindable(),
    selectedOrcid = $bindable(),
    selectedIdhal = $bindable(),
    selectedRh = $bindable(),
    deptOptions,
    roleOptions,
    linkedOptions,
    orcidOptions,
    idhalOptions,
    rhOptions,
    totalCount,
    onsearch,
    onfilterchange,
  }: {
    search: string;
    selectedDepts: string[];
    selectedRoles: string[];
    selectedLinked: string[];
    selectedOrcid: string[];
    selectedIdhal: string[];
    selectedRh: string[];
    deptOptions: FacetOption[];
    roleOptions: FacetOption[];
    linkedOptions: FacetOption[];
    orcidOptions: FacetOption[];
    idhalOptions: FacetOption[];
    rhOptions: FacetOption[];
    totalCount: number;
    onsearch: () => void;
    onfilterchange: () => void;
  } = $props();
</script>

<div class="toolbar">
  <input
    type="text"
    placeholder="Rechercher (nom, email, d&eacute;partement)…"
    bind:value={search}
    oninput={onsearch}
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
  <FacetDropdown
    label="Rattachement"
    options={linkedOptions}
    bind:selected={selectedLinked}
    onchange={onfilterchange}
  />
  <FacetDropdown
    label="ORCID"
    options={orcidOptions}
    bind:selected={selectedOrcid}
    onchange={onfilterchange}
  />
  <FacetDropdown
    label="idHAL"
    options={idhalOptions}
    bind:selected={selectedIdhal}
    onchange={onfilterchange}
  />
  <FacetDropdown
    label="Base RH"
    options={rhOptions}
    bind:selected={selectedRh}
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
