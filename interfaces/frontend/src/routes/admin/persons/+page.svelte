<script lang="ts">
  import { onMount } from "svelte";
  import { base } from "$app/paths";
  import { replaceState } from "$app/navigation";
  import { api, ApiError, orphanAuthorships, persons as personsApi } from "$lib/api";
  import { useDebouncedSearch } from "$lib/composables/useDebouncedSearch.svelte";
  import { titleCase } from "$lib/utils";
  import type { FacetOption } from "$lib/components/FacetDropdown.svelte";
  import Pagination from "$lib/components/Pagination.svelte";
  import type {
    DetachModalState,
    EditNameState,
    IdFormState,
    OtherPerson,
    Person,
    PersonListResponse,
    PersonSearchResult,
    PersonStats,
  } from "./types";
  import PersonsToolbar from "./PersonsToolbar.svelte";
  import EditNameModal from "./EditNameModal.svelte";
  import DetachNameFormModal from "./DetachNameFormModal.svelte";
  import IdentifiersCell from "./IdentifiersCell.svelte";
  import MergeSearchCell from "./MergeSearchCell.svelte";

  /* ── State ── */

  let stats = $state<PersonStats | null>(null);
  let orphanCount = $state(0);

  type IdState = "all" | "yes" | "no";

  let search = $state("");
  let selectedDepts: string[] = $state([]);
  let selectedRoles: string[] = $state([]);
  let selectedRh: string[] = $state([]);
  let idStates = $state<Record<string, IdState>>({});

  let deptOptions: FacetOption[] = $state([]);
  let roleOptions: FacetOption[] = $state([]);
  let rhOptions: FacetOption[] = $state([
    { value: "yes", text: "Oui" },
    { value: "no", text: "Non" },
  ]);
  let idCounts: Record<string, { yes: number; no: number }> = $state({
    orcid: { yes: 0, no: 0 },
    idhal: { yes: 0, no: 0 },
    idref: { yes: 0, no: 0 },
  });

  const idQueryKey: Record<string, string> = {
    orcid: "has_orcid",
    idhal: "has_idhal",
    idref: "has_idref",
  };

  let currentPage = $state(1);
  let totalPages = $state(0);
  let totalCount = $state(0);
  let persons: Person[] = $state([]);
  let loading = $state(false);
  let sortField = $state("name");

  let searchTimeout: ReturnType<typeof setTimeout> | null = null;

  let idForms: Record<number, IdFormState> = $state({});

  let editNameModal: EditNameState | null = $state(null);
  let detachModal: DetachModalState | null = $state(null);

  let activeMergePersonId: number | null = $state(null);
  const mergeSearch = useDebouncedSearch<PersonSearchResult>({
    search: (q) => api<PersonSearchResult[]>(`/api/persons/search?q=${encodeURIComponent(q)}`),
    transform: (results) =>
      activeMergePersonId === null
        ? results
        : results.filter((r) => r.id !== activeMergePersonId),
  });

  /* ── Data loading ── */

  async function loadStats() {
    stats = await api<PersonStats>("/api/persons/stats", { key: "persons-stats" });
  }

  function buildFilterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (selectedDepts.length) params.set("department", selectedDepts.join(","));
    if (selectedRoles.length) params.set("role", selectedRoles.join(","));
    for (const [key, qk] of Object.entries(idQueryKey)) {
      const v = idStates[key];
      if (v === "yes" || v === "no") params.set(qk, v);
    }
    if (selectedRh.length === 1) params.set("has_rh", selectedRh[0]);
    return params;
  }

  async function loadFacets() {
    const params = buildFilterParams();
    const data = await api<{
      departments: { value: string; count: number }[];
      roles: { value: string; count: number }[];
      orcid: { yes: number; no: number };
      idhal: { yes: number; no: number };
      idref: { yes: number; no: number };
      rh: { yes: number; no: number };
    }>("/api/persons/facets?" + params, { key: "persons-facets" });
    deptOptions = data.departments.map((d) => ({ value: d.value, text: d.value, count: d.count }));
    roleOptions = data.roles.map((r) => ({ value: r.value, text: r.value, count: r.count }));
    rhOptions = [
      { value: "yes", text: "Oui", count: data.rh.yes },
      { value: "no", text: "Non", count: data.rh.no },
    ];
    idCounts = {
      orcid: { yes: data.orcid.yes, no: data.orcid.no },
      idhal: { yes: data.idhal.yes, no: data.idhal.no },
      idref: { yes: data.idref.yes, no: data.idref.no },
    };
  }

  async function loadTable() {
    loading = true;
    const params = new URLSearchParams({ page: String(currentPage), per_page: "50" });
    if (search.trim()) params.set("search", search.trim());
    if (selectedDepts.length === 1) params.set("department", selectedDepts[0]);
    if (selectedRoles.length === 1) params.set("role", selectedRoles[0]);
    for (const [key, qk] of Object.entries(idQueryKey)) {
      const v = idStates[key];
      if (v === "yes" || v === "no") params.set(qk, v);
    }
    if (selectedRh.length === 1) params.set("has_rh", selectedRh[0]);
    params.set("sort", sortField);

    const data = await api<PersonListResponse>("/api/persons?" + params, { key: "persons-list" });
    persons = data.persons;
    totalCount = data.total;
    totalPages = data.pages;
    currentPage = data.page;
    loading = false;
    updateUrl();
  }

  function toggleSort(field: string) {
    if (sortField === field) sortField = "-" + field;
    else if (sortField === "-" + field) sortField = field;
    else sortField = field;
    currentPage = 1;
    loadTable();
  }

  function sortIndicator(field: string): string {
    if (sortField === field) return " \u25B2";
    if (sortField === "-" + field) return " \u25BC";
    return "";
  }

  /* ── URL state ── */

  function updateUrl() {
    const url = new URL(window.location.href);
    const setOrDel = (key: string, val: string) => {
      if (val) url.searchParams.set(key, val);
      else url.searchParams.delete(key);
    };
    setOrDel("p", currentPage > 1 ? String(currentPage) : "");
    setOrDel("search", search);
    setOrDel("dept", selectedDepts.length === 1 ? selectedDepts[0] : "");
    setOrDel("role", selectedRoles.length === 1 ? selectedRoles[0] : "");
    setOrDel("rh", selectedRh.length === 1 ? selectedRh[0] : "");
    const idFilter = Object.entries(idStates)
      .filter(([, v]) => v === "yes" || v === "no")
      .map(([k, v]) => `${k}_${v}`)
      .join(",");
    setOrDel("id_filter", idFilter);
    replaceState(url, {});
  }

  function readUrlFilters() {
    const p = new URLSearchParams(window.location.search);
    if (p.get("p")) currentPage = Math.max(1, parseInt(p.get("p")!, 10) || 1);
    if (p.get("search")) search = p.get("search")!;
    if (p.get("dept")) selectedDepts = [p.get("dept")!];
    if (p.get("role")) selectedRoles = [p.get("role")!];
    if (p.get("rh")) selectedRh = [p.get("rh")!];
    const idFilter = p.get("id_filter");
    if (idFilter) {
      const states: Record<string, IdState> = {};
      for (const part of idFilter.split(",")) {
        const m = part.match(/^(orcid|idhal|idref)_(yes|no)$/);
        if (m) states[m[1]] = m[2] as IdState;
      }
      idStates = states;
    }
  }

  /* ── Event handlers ── */

  function handleSearch() {
    if (searchTimeout) clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      currentPage = 1;
      loadTable();
    }, 400);
  }

  function handleFilterChange() {
    currentPage = 1;
    loadTable();
    loadFacets();
  }

  function handlePageChange(p: number) {
    currentPage = p;
    loadTable();
    window.scrollTo(0, 0);
  }

  /* ── Identifiers ── */

  function toggleIdForm(personId: number) {
    if (personId in idForms) {
      const next = { ...idForms };
      delete next[personId];
      idForms = next;
    } else {
      idForms = { ...idForms, [personId]: { id_type: "orcid", id_value: "", error: "" } };
    }
  }

  async function addIdentifier(personId: number) {
    const form = idForms[personId];
    if (!form || !form.id_value.trim()) return;

    try {
      await personsApi.addIdentifier(personId, {
        id_type: form.id_type,
        id_value: form.id_value.trim(),
      });
    } catch (e) {
      const detail = e instanceof ApiError ? (e.detail as { detail?: string })?.detail : null;
      idForms = { ...idForms, [personId]: { ...form, error: detail || "Erreur inconnue" } };
      return;
    }

    const next = { ...idForms };
    delete next[personId];
    idForms = next;
    await loadTable();
  }

  async function setIdentifierStatus(identId: number, status: string) {
    await personsApi.setIdentifierStatus(identId, status);
    await loadTable();
  }

  /* ── Orphans ── */

  async function loadOrphanCount() {
    const data = await api<{ total: number }>("/api/admin/orphan-authorships/count");
    orphanCount = data.total;
  }

  /* ── Edit name ── */

  async function savePersonName() {
    if (!editNameModal) return;
    try {
      await personsApi.rename(
        editNameModal.personId,
        editNameModal.lastName,
        editNameModal.firstName,
      );
    } catch (e) {
      const status = e instanceof ApiError ? e.status : "?";
      const detail = e instanceof ApiError ? (e.detail as { detail?: string })?.detail : null;
      alert(detail || `Erreur ${status}`);
      return;
    }
    editNameModal = null;
    loadTable();
  }

  async function toggleRejectPerson(personId: number, rejected: boolean) {
    await personsApi.setRejected(personId, rejected);
    editNameModal = null;
    loadTable();
  }

  /* ── Detach modal ── */

  async function openDetachModal(personId: number, nameForm: string) {
    detachModal = { personId, nameForm, authorships: [], otherPersons: [], loading: true };
    const data = await api<{ authorships: any[]; other_persons: OtherPerson[] }>(
      `/api/persons/${personId}/name-form-authorships?name_form=${encodeURIComponent(nameForm)}`,
    );
    detachModal = {
      personId,
      nameForm,
      loading: false,
      authorships: data.authorships.map((r) => ({ ...r, checked: true })),
      otherPersons: data.other_persons,
    };
  }

  async function confirmDetach() {
    if (!detachModal) return;
    const toDetach = detachModal.authorships.filter((a) => a.checked);
    if (toDetach.length === 0) {
      detachModal = null;
      return;
    }
    await personsApi.detachAuthorships(detachModal.personId, {
      authorships: toDetach.map((a) => ({ source: a.source, authorship_id: a.authorship_id })),
      name_form: detachModal.nameForm,
    });
    detachModal = null;
    loadStats();
    loadTable();
  }

  async function detachNameForm() {
    if (!detachModal) return;
    await personsApi.detachNameForm(detachModal.personId, { name_form: detachModal.nameForm });
    detachModal = null;
    loadStats();
    loadTable();
  }

  /* ── Merge ── */

  function openMergeSearch(personId: number) {
    activeMergePersonId = personId;
    mergeSearch.clear();
  }

  function closeMergeSearch() {
    activeMergePersonId = null;
    mergeSearch.clear();
  }

  async function mergeInto(targetId: number, sourceId: number) {
    await personsApi.merge(targetId, sourceId);
    closeMergeSearch();
    loadStats();
    loadTable();
  }

  async function mergeFromModal(sourceId: number) {
    if (!detachModal) return;
    const targetId = detachModal.personId;
    await personsApi.merge(targetId, sourceId);
    detachModal = null;
    loadStats();
    loadTable();
  }

  /* ── Lifecycle ── */

  onMount(() => {
    readUrlFilters();
    loadFacets();
    loadTable();
    loadOrphanCount();
  });
</script>

<svelte:head>
  <title>Admin - Personnes - Bibliom&eacute;trie UCA</title>
</svelte:head>

<PersonsToolbar
  bind:search
  bind:selectedDepts
  bind:selectedRoles
  bind:selectedRh
  bind:idStates
  {deptOptions}
  {roleOptions}
  {rhOptions}
  {idCounts}
  {totalCount}
  onsearch={handleSearch}
  onfilterchange={handleFilterChange}
/>

{#if orphanCount > 0}
  <a href="{base}/admin/orphan-authorships" class="orphan-link">
    {orphanCount} authorship{orphanCount > 1 ? "s" : ""} UCA orpheline{orphanCount > 1
      ? "s"
      : ""} (non reliée{orphanCount > 1 ? "s" : ""} à une personne)
  </a>
{/if}

{#if persons.length === 0 && !loading}
  <div class="empty">Aucune personne trouv&eacute;e.</div>
{:else}
  <table class="data-table">
    <thead>
      <tr>
        <th class="sortable col-name" onclick={() => toggleSort("name")}
          >Nom{sortIndicator("name")}</th
        >
        <th class="sortable" onclick={() => toggleSort("pubs")}
          >Publis{sortIndicator("pubs")}</th
        >
        <th class="sortable" onclick={() => toggleSort("uca_pubs")}
          >UCA{sortIndicator("uca_pubs")}</th
        >
        <th>Identifiants</th>
        <th>Formes de noms</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>
      {#each persons as p (p.id)}
        <tr class:rejected={p.rejected}>
          <td class="td-name">
            <button
              class="btn-edit-name"
              title="Modifier le nom"
              onclick={() => {
                editNameModal = {
                  personId: p.id,
                  lastName: p.last_name,
                  firstName: p.first_name,
                  rejected: p.rejected ?? false,
                };
              }}
              ><svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                ><path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" /><path
                  d="m15 5 4 4"
                /></svg
              ></button
            >
            <a href="{base}/persons/{p.id}" class="person-name">
              <span class="person-last">{titleCase(p.last_name)}</span>
              {titleCase(p.first_name)}
            </a>
            {#if p.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
          </td>
          <td>{p.pub_count ?? 0}</td>
          <td>{p.uca_pub_count ?? 0}</td>
          <td>
            <IdentifiersCell
              person={p}
              form={idForms[p.id] ?? null}
              onadd={addIdentifier}
              ontoggleForm={toggleIdForm}
              onsetStatus={setIdentifierStatus}
            />
          </td>
          <td>
            {#if p.name_forms?.length}
              <div class="name-forms-list">
                {#each p.name_forms as nf}
                  <button
                    class="name-form-tag"
                    class:ambiguous={nf.ambiguous}
                    onclick={() => openDetachModal(p.id, nf.name_form)}
                  >
                    {nf.name_form}
                  </button>
                {/each}
              </div>
            {:else}
              <span class="tag tag-unlinked">aucune</span>
            {/if}
          </td>
          <td>
            <MergeSearchCell
              targetPersonId={p.id}
              active={activeMergePersonId === p.id}
              {mergeSearch}
              onopen={openMergeSearch}
              onclose={closeMergeSearch}
              onmerge={mergeInto}
            />
          </td>
        </tr>
      {/each}
    </tbody>
  </table>

  <Pagination page={currentPage} pages={totalPages} onchange={handlePageChange} />
{/if}

{#if detachModal}
  <DetachNameFormModal
    bind:state={detachModal}
    onclose={() => {
      detachModal = null;
    }}
    onconfirmDetach={confirmDetach}
    ondetachNameForm={detachNameForm}
    onmerge={mergeFromModal}
  />
{/if}

{#if editNameModal}
  <EditNameModal
    bind:state={editNameModal}
    onsave={savePersonName}
    ontoggleReject={toggleRejectPerson}
    onclose={() => {
      editNameModal = null;
    }}
  />
{/if}

<style>
  .data-table {
    overflow: visible;
  }
  /* ── Tags ── */
  .tag {
    display: inline-block;
    font-size: 0.8rem;
    padding: 1px 7px;
    border-radius: 10px;
    font-weight: 500;
    margin: 1px 2px;
  }
  .tag-unlinked {
    background: var(--warning-light);
    color: #8a6d10;
  }
  .sortable:hover {
    color: #2563eb;
  }
  .col-name {
    min-width: 200px;
  }
  .td-name {
    position: relative;
    padding-left: 30px !important;
  }
  .person-name {
    font-weight: 500;
    color: inherit;
    text-decoration: none;
  }
  .person-name:hover {
    color: #2563eb;
    text-decoration: underline;
  }
  .person-last {
    font-weight: 600;
  }
  /* ── Name forms ── */
  .name-forms-list {
    display: flex;
    flex-direction: column;
    gap: 2px;
    align-items: flex-start;
  }
  .name-form-tag {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    background: #f0f4f8;
    border: 1px solid #d0d8e0;
    border-radius: 3px;
    padding: 1px 6px;
    font-size: 0.78rem;
    cursor: pointer;
    transition: background 0.15s;
    text-align: left;
  }
  .name-form-tag:hover {
    background: #e0e8f0;
    border-color: #a0b0c0;
  }
  .name-form-tag.ambiguous {
    background: #fff3e0;
    border-color: #e0c080;
    color: #8a6d3b;
  }
  .name-form-tag.ambiguous:hover {
    background: #ffe8cc;
    border-color: #d0a050;
  }
  /* ── Edit name trigger ── */
  .btn-edit-name {
    background: none;
    border: none;
    cursor: pointer;
    padding: 2px;
    color: #bbb;
    opacity: 0.4;
    transition:
      opacity 0.15s,
      color 0.15s;
    position: absolute;
    left: 8px;
    top: 8px;
  }
  .btn-edit-name:hover {
    color: var(--accent, #1976d2);
    opacity: 1;
  }
  /* ── Rejected persons ── */
  tr.rejected {
    opacity: 0.45;
  }
  tr.rejected:hover {
    opacity: 0.7;
  }
  tr.rejected .person-name {
    text-decoration: line-through;
  }
  /* ── Orphans ── */
  .orphan-link {
    display: block;
    width: 100%;
    padding: 10px 16px;
    margin-bottom: 12px;
    background: #fff3e0;
    border: 1px solid #ffcc80;
    border-radius: 6px;
    color: #e65100;
    font-size: 0.9rem;
    font-weight: 500;
    cursor: pointer;
    text-align: left;
    transition: background 0.15s;
  }
  .orphan-link:hover {
    background: #ffe0b2;
  }
</style>
