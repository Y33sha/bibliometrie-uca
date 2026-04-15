<script lang="ts">
  import { onMount } from "svelte";
  import { base } from "$app/paths";
  import { replaceState } from "$app/navigation";
  import { api } from "$lib/api";
  import { sanitizeTitle, titleCase } from "$lib/utils";
  import FacetDropdown from "$lib/components/FacetDropdown.svelte";
  import type { FacetOption } from "$lib/components/FacetDropdown.svelte";
  import Pagination from "$lib/components/Pagination.svelte";

  /* ── Types ── */

  interface PersonStats {
    total_persons: number;
    linked_persons: number;
    linked_authors: number;
    departments: number;
  }

  interface LinkedAuthor {
    id: number;
    source: string;
    full_name: string;
    orcid?: string;
    idhal?: string;
  }

  interface PersonIdentifier {
    id: number;
    id_type: string;
    id_value: string;
    source: string;
    status: "pending" | "confirmed" | "rejected";
  }

  interface NameForm {
    name_form: string;
    ambiguous: boolean;
  }
  interface Person {
    id: number;
    first_name: string;
    last_name: string;
    department_name?: string;
    role_title?: string;
    start_date?: string;
    end_date?: string;
    has_rh?: boolean;
    rejected?: boolean;
    pub_count?: number;
    uca_pub_count?: number;
    linked_authors?: LinkedAuthor[];
    identifiers?: PersonIdentifier[];
    name_forms?: NameForm[];
  }

  interface PersonListResponse {
    total: number;
    page: number;
    pages: number;
    persons: Person[];
  }

  /* ── State ── */

  let stats = $state<PersonStats | null>(null);
  let orphanCount = $state(0);
  let showOrphans = $state(false);
  let orphanSearch = $state("");
  let orphanPage = $state(1);
  let orphanPages = $state(1);
  let orphanTotal = $state(0);
  let orphans: any[] = $state([]);
  let orphanAssignSearch: Record<number, { query: string; results: any[]; loading: boolean }> = $state({});
  let orphanTimers: Record<number, ReturnType<typeof setTimeout>> = {};

  let search = $state("");
  let selectedDepts: string[] = $state([]);
  let selectedRoles: string[] = $state([]);
  let selectedLinked: string[] = $state([]);
  let selectedOrcid: string[] = $state([]);
  let selectedIdhal: string[] = $state([]);
  let selectedRh: string[] = $state([]);

  let deptOptions: FacetOption[] = $state([]);
  let roleOptions: FacetOption[] = $state([]);
  let linkedOptions: FacetOption[] = $state([
    { value: "yes", text: "Rattachées" },
    { value: "no", text: "Non rattachées" },
  ]);
  let orcidOptions: FacetOption[] = $state([
    { value: "yes", text: "Avec ORCID" },
    { value: "no", text: "Sans ORCID" },
  ]);
  let idhalOptions: FacetOption[] = $state([
    { value: "yes", text: "Avec idHAL" },
    { value: "no", text: "Sans idHAL" },
  ]);
  let rhOptions: FacetOption[] = $state([
    { value: "yes", text: "Oui" },
    { value: "no", text: "Non" },
  ]);

  let currentPage = $state(1);
  let totalPages = $state(0);
  let totalCount = $state(0);
  let persons: Person[] = $state([]);
  let loading = $state(false);
  let sortField = $state("name"); // 'name' | '-name' | 'pubs' | '-pubs'

  let searchTimeout: ReturnType<typeof setTimeout> | null = null;

  /* Expanded author details keyed by "source-authorId" */
  /* Identifier add form state: personId → { open, id_type, id_value, error } */
  let idForms: Record<number, { id_type: string; id_value: string; error: string }> = $state({});

  /* Edit name modal state */
  let editNameModal: { personId: number; lastName: string; firstName: string; rejected: boolean } | null = $state(null);

  /* Detach modal state */
  interface DetachAuthorship {
    source: string;
    authorship_id: number;
    pub_id: number;
    title: string;
    pub_year: number | null;
    doi: string | null;
    checked: boolean;
  }
  interface OtherPerson {
    id: number;
    first_name: string;
    last_name: string;
    department_name: string | null;
    has_rh: boolean;
  }
  let detachModal: { personId: number; nameForm: string; authorships: DetachAuthorship[]; otherPersons: OtherPerson[]; loading: boolean } | null = $state(null);

  /* Merge search state */
  interface MergeSearch {
    query: string;
    results: { id: number; first_name: string; last_name: string; department_name: string | null; has_rh: boolean }[];
    loading: boolean;
  }
  let mergeSearches: Record<number, MergeSearch> = $state({});
  let mergeTimers: Record<number, ReturnType<typeof setTimeout>> = {};

  /* ── Derived ── */

  const unlinkedCount = $derived(stats ? stats.total_persons - stats.linked_persons : 0);

  /* ── Data loading ── */

  async function loadStats() {
    stats = await api<PersonStats>("/api/persons/stats", { key: "persons-stats" });
  }

  function buildFilterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (selectedDepts.length) params.set("department", selectedDepts.join(","));
    if (selectedRoles.length) params.set("role", selectedRoles.join(","));
    if (selectedLinked.length === 1) params.set("linked", selectedLinked[0]);
    if (selectedOrcid.length === 1) params.set("has_orcid", selectedOrcid[0]);
    if (selectedIdhal.length === 1) params.set("has_idhal", selectedIdhal[0]);
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
      rh: { yes: number; no: number };
      linked: { yes: number; no: number } | null;
    }>("/api/persons/facets?" + params, { key: "persons-facets" });
    deptOptions = data.departments.map((d) => ({
      value: d.value,
      text: d.value,
      count: d.count,
    }));
    roleOptions = data.roles.map((r) => ({
      value: r.value,
      text: r.value,
      count: r.count,
    }));
    orcidOptions = [
      { value: "yes", text: "Avec ORCID", count: data.orcid.yes },
      { value: "no", text: "Sans ORCID", count: data.orcid.no },
    ];
    idhalOptions = [
      { value: "yes", text: "Avec idHAL", count: data.idhal.yes },
      { value: "no", text: "Sans idHAL", count: data.idhal.no },
    ];
    rhOptions = [
      { value: "yes", text: "Oui", count: data.rh.yes },
      { value: "no", text: "Non", count: data.rh.no },
    ];
    if (data.linked) {
      linkedOptions = [
        { value: "yes", text: "Rattachées", count: data.linked.yes },
        { value: "no", text: "Non rattachées", count: data.linked.no },
      ];
    }
  }

  async function loadTable() {
    loading = true;
    const params = new URLSearchParams({
      page: String(currentPage),
      per_page: "50",
    });
    if (search.trim()) params.set("search", search.trim());
    if (selectedDepts.length === 1) params.set("department", selectedDepts[0]);
    if (selectedRoles.length === 1) params.set("role", selectedRoles[0]);
    if (selectedLinked.length === 1) params.set("linked", selectedLinked[0]);
    if (selectedOrcid.length === 1) params.set("has_orcid", selectedOrcid[0]);
    if (selectedIdhal.length === 1) params.set("has_idhal", selectedIdhal[0]);
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
    setOrDel("linked", selectedLinked.length === 1 ? selectedLinked[0] : "");
    setOrDel("orcid", selectedOrcid.length === 1 ? selectedOrcid[0] : "");
    setOrDel("idhal", selectedIdhal.length === 1 ? selectedIdhal[0] : "");
    setOrDel("rh", selectedRh.length === 1 ? selectedRh[0] : "");
    replaceState(url, {});
  }

  function readUrlFilters() {
    const p = new URLSearchParams(window.location.search);
    if (p.get("p")) currentPage = Math.max(1, parseInt(p.get("p")!, 10) || 1);
    if (p.get("search")) search = p.get("search")!;
    if (p.get("dept")) selectedDepts = [p.get("dept")!];
    if (p.get("role")) selectedRoles = [p.get("role")!];
    if (p.get("linked")) selectedLinked = [p.get("linked")!];
    if (p.get("orcid")) selectedOrcid = [p.get("orcid")!];
    if (p.get("idhal")) selectedIdhal = [p.get("idhal")!];
    if (p.get("rh")) selectedRh = [p.get("rh")!];
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

    const resp = await fetch(`${base}/api/persons/${personId}/identifier`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id_type: form.id_type, id_value: form.id_value.trim() }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "Erreur inconnue" }));
      idForms = { ...idForms, [personId]: { ...form, error: err.detail || `Erreur ${resp.status}` } };
      return;
    }

    // Fermer le formulaire et rafraîchir la ligne
    const next = { ...idForms };
    delete next[personId];
    idForms = next;
    await loadTable();
  }

  async function removeIdentifier(personId: number, idType: string, idValue: string) {
    await fetch(`${base}/api/persons/${personId}/identifier/${idType}/${encodeURIComponent(idValue)}`, {
      method: "DELETE",
    });
    await loadTable();
  }

  async function setIdentifierStatus(identId: number, status: string) {
    await fetch(`${base}/api/person-identifiers/${identId}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    await loadTable();
  }

  /* ── Reassign identifier ── */
  let reassignState: Record<number, string> = $state({});

  async function reassignIdentifier(identId: number) {
    const targetIdStr = reassignState[identId]?.trim();
    if (!targetIdStr) return;
    const targetPersonId = parseInt(targetIdStr);
    if (isNaN(targetPersonId)) return;
    const resp = await fetch(`${base}/api/person-identifiers/${identId}/reassign`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ person_id: targetPersonId }),
    });
    if (resp.ok) {
      delete reassignState[identId];
      reassignState = reassignState;
      await loadTable();
    } else {
      const err = await resp.json().catch(() => null);
      alert(err?.detail || "Erreur");
    }
  }

  /* ── Orphans ── */

  async function loadOrphanCount() {
    const data = await api<{ total: number }>("/api/admin/orphan-authorships/count");
    orphanCount = data.total;
  }

  async function loadOrphans() {
    const params = new URLSearchParams({ page: String(orphanPage), per_page: "50" });
    if (orphanSearch.trim()) params.set("search", orphanSearch.trim());
    const data = await api<{ total: number; page: number; pages: number; authorships: any[] }>("/api/admin/orphan-authorships?" + params, { key: "orphans" });
    orphans = data.authorships;
    orphanTotal = data.total;
    orphanPages = data.pages;
    orphanPage = data.page;
  }

  function openOrphanAssign(idx: number) {
    orphanAssignSearch = { [idx]: { query: "", results: [], loading: false } };
  }

  function handleOrphanSearchInput(idx: number, query: string) {
    orphanAssignSearch = { ...orphanAssignSearch, [idx]: { ...orphanAssignSearch[idx], query } };
    if (orphanTimers[idx]) clearTimeout(orphanTimers[idx]);
    if (query.trim().length < 2) {
      orphanAssignSearch = { ...orphanAssignSearch, [idx]: { ...orphanAssignSearch[idx], results: [], loading: false } };
      return;
    }
    orphanTimers[idx] = setTimeout(async () => {
      orphanAssignSearch = { ...orphanAssignSearch, [idx]: { ...orphanAssignSearch[idx], loading: true } };
      const results = await api<any[]>(`/api/persons/search?q=${encodeURIComponent(query.trim())}`);
      orphanAssignSearch = { ...orphanAssignSearch, [idx]: { ...orphanAssignSearch[idx], results, loading: false } };
    }, 300);
  }

  async function assignOrphan(orphan: any, personId: number) {
    await fetch(`${base}/api/admin/orphan-authorships/assign`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: orphan.source, authorship_id: orphan.authorship_id, person_id: personId }),
    });
    orphanAssignSearch = {};
    loadOrphans();
    loadOrphanCount();
  }

  async function createAndAssignOrphan(orphan: any) {
    const parts = orphan.full_name.includes(",")
      ? orphan.full_name.split(",").map((s: string) => s.trim())
      : [orphan.full_name.split(" ").slice(-1)[0], orphan.full_name.split(" ").slice(0, -1).join(" ")];
    const lastName = parts[0] || orphan.full_name;
    const firstName = parts[1] || "";
    await fetch(`${base}/api/admin/orphan-authorships/assign`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: orphan.source,
        authorship_id: orphan.authorship_id,
        create_person: { last_name: lastName, first_name: firstName },
      }),
    });
    orphanAssignSearch = {};
    loadOrphans();
    loadOrphanCount();
  }

  /* ── Edit name ── */

  async function savePersonName() {
    if (!editNameModal) return;
    const resp = await fetch(`${base}/api/persons/${editNameModal.personId}/name`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ last_name: editNameModal.lastName, first_name: editNameModal.firstName }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: `Erreur ${resp.status}` }));
      alert(err.detail || `Erreur ${resp.status}`);
      return;
    }
    editNameModal = null;
    loadTable();
  }

  async function toggleRejectPerson(personId: number, rejected: boolean) {
    await fetch(`${base}/api/persons/${personId}/reject`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rejected }),
    });
    editNameModal = null;
    loadTable();
  }

  /* ── Detach modal ── */

  async function openDetachModal(personId: number, nameForm: string) {
    detachModal = { personId, nameForm, authorships: [], otherPersons: [], loading: true };
    const data = await api<{ authorships: any[]; other_persons: OtherPerson[] }>(`/api/persons/${personId}/name-form-authorships?name_form=${encodeURIComponent(nameForm)}`);
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

    await fetch(`${base}/api/persons/${detachModal.personId}/detach-authorships`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        authorships: toDetach.map((a) => ({ source: a.source, authorship_id: a.authorship_id })),
        name_form: detachModal.nameForm,
      }),
    });
    detachModal = null;
    loadStats();
    loadTable();
  }

  async function detachNameForm() {
    if (!detachModal) return;
    await fetch(`${base}/api/persons/${detachModal.personId}/detach-name-form`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name_form: detachModal.nameForm }),
    });
    detachModal = null;
    loadStats();
    loadTable();
  }

  /* ── Merge ── */

  function openMergeSearch(personId: number) {
    // Close all other merge searches
    for (const id of Object.keys(mergeTimers)) {
      clearTimeout(mergeTimers[Number(id)]);
    }
    mergeSearches = { [personId]: { query: "", results: [], loading: false } };
  }

  function closeMergeSearch(personId: number) {
    const next = { ...mergeSearches };
    delete next[personId];
    mergeSearches = next;
    if (mergeTimers[personId]) clearTimeout(mergeTimers[personId]);
  }

  function handleMergeSearchInput(personId: number, query: string) {
    mergeSearches = { ...mergeSearches, [personId]: { ...mergeSearches[personId], query } };
    if (mergeTimers[personId]) clearTimeout(mergeTimers[personId]);
    if (query.trim().length < 2) {
      mergeSearches = { ...mergeSearches, [personId]: { ...mergeSearches[personId], results: [], loading: false } };
      return;
    }
    mergeTimers[personId] = setTimeout(async () => {
      mergeSearches = { ...mergeSearches, [personId]: { ...mergeSearches[personId], loading: true } };
      const results = await api<MergeSearch["results"]>(`/api/persons/search?q=${encodeURIComponent(query.trim())}`);
      // Exclude self from results
      mergeSearches = { ...mergeSearches, [personId]: { ...mergeSearches[personId], results: results.filter((r) => r.id !== personId), loading: false } };
    }, 300);
  }

  async function mergeInto(targetId: number, sourceId: number) {
    await fetch(`${base}/api/persons/${targetId}/merge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_id: sourceId }),
    });
    closeMergeSearch(targetId);
    loadStats();
    loadTable();
  }

  async function mergeFromModal(sourceId: number) {
    if (!detachModal) return;
    const targetId = detachModal.personId;
    await fetch(`${base}/api/persons/${targetId}/merge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_id: sourceId }),
    });
    detachModal = null;
    loadStats();
    loadTable();
  }

  /* ── Helpers ── */

  function formatPeriod(p: Person): string {
    const parts: string[] = [];
    if (p.start_date) parts.push(p.start_date.substring(0, 10));
    if (p.start_date || p.end_date) {
      parts.push("\u2192");
      parts.push(p.end_date ? p.end_date.substring(0, 10) : "\u2026");
    }
    return parts.join(" ");
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

<!-- Toolbar -->
<div class="toolbar">
  <input type="text" placeholder="Rechercher (nom, email, d&eacute;partement)…" bind:value={search} oninput={handleSearch} />
  <FacetDropdown label="Département" options={deptOptions} searchable bind:selected={selectedDepts} onchange={handleFilterChange} />
  <FacetDropdown label="Rôle" options={roleOptions} searchable bind:selected={selectedRoles} onchange={handleFilterChange} />
  <FacetDropdown label="Rattachement" options={linkedOptions} bind:selected={selectedLinked} onchange={handleFilterChange} />
  <FacetDropdown label="ORCID" options={orcidOptions} bind:selected={selectedOrcid} onchange={handleFilterChange} />
  <FacetDropdown label="idHAL" options={idhalOptions} bind:selected={selectedIdhal} onchange={handleFilterChange} />
  <FacetDropdown label="Base RH" options={rhOptions} bind:selected={selectedRh} onchange={handleFilterChange} />
  <span class="count">{totalCount} personnes</span>
</div>

{#if orphanCount > 0}
  <a href="{base}/admin/orphan-authorships" class="orphan-link">
    {orphanCount} authorship{orphanCount > 1 ? "s" : ""} UCA orpheline{orphanCount > 1 ? "s" : ""} (non reliée{orphanCount > 1 ? "s" : ""} à une personne)
  </a>
{/if}

<!-- Table -->
{#if persons.length === 0 && !loading}
  <div class="empty">Aucune personne trouv&eacute;e.</div>
{:else}
  <table class="data-table">
    <thead>
      <tr>
        <th class="sortable col-name" onclick={() => toggleSort("name")}>Nom{sortIndicator("name")}</th>
        <th class="sortable" onclick={() => toggleSort("pubs")}>Publis{sortIndicator("pubs")}</th>
        <th class="sortable" onclick={() => toggleSort("uca_pubs")}>UCA{sortIndicator("uca_pubs")}</th>
        <th>Identifiants</th>
        <th>Formes de noms</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>
      {#each persons as p (p.id)}
        {@const linked = p.linked_authors ?? []}
        <tr class:rejected={p.rejected}>
          <td class="td-name">
            <button
              class="btn-edit-name"
              title="Modifier le nom"
              onclick={() => {
                editNameModal = { personId: p.id, lastName: p.last_name, firstName: p.first_name, rejected: p.rejected ?? false };
              }}
              ><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                ><path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" /><path d="m15 5 4 4" /></svg
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
          <!-- Identifiants -->
          <td>
            {#if p.identifiers?.length}
              <div class="identifiers-row">
                {#each p.identifiers as ident}
                  <span class="identifier-tag" class:rejected={ident.status === "rejected"} class:confirmed={ident.status === "confirmed"}>
                    <span class="tag tag-id" title="{ident.id_type} ({ident.source}) — {ident.status === 'rejected' ? 'rejeté' : ident.status === 'confirmed' ? 'confirmé' : 'en attente'}">
                      {ident.id_type === "orcid" ? "ORCID" : ident.id_type === "idhal" ? "idHAL" : ident.id_type}: {ident.id_value}
                    </span>
                    <button
                      class="btn-status"
                      class:active={ident.status === "confirmed"}
                      title={ident.status === "confirmed" ? "Retirer la confirmation" : "Confirmer"}
                      onclick={() => setIdentifierStatus(ident.id, ident.status === "confirmed" ? "pending" : "confirmed")}>&#x2713;</button
                    >
                    <button
                      class="btn-status btn-reject"
                      class:active={ident.status === "rejected"}
                      title={ident.status === "rejected" ? "Retirer le rejet" : "Rejeter"}
                      onclick={() => setIdentifierStatus(ident.id, ident.status === "rejected" ? "pending" : "rejected")}>&#x2717;</button
                    >
                  </span>
                {/each}
              </div>
            {/if}
            {#if p.id in idForms}
              {@const form = idForms[p.id]}
              <div class="id-form">
                <select
                  value={form.id_type}
                  onchange={(e) => {
                    idForms = { ...idForms, [p.id]: { ...form, id_type: (e.target as HTMLSelectElement).value, error: "" } };
                  }}
                >
                  <option value="orcid">ORCID</option>
                  <option value="idhal">idHAL</option>
                  <option value="idref">IdRef</option>
                </select>
                <input
                  type="text"
                  placeholder={form.id_type === "orcid" ? "0000-0000-0000-0000" : form.id_type === "idhal" ? "identifiant-hal" : "identifiant idref"}
                  value={form.id_value}
                  oninput={(e) => {
                    idForms = { ...idForms, [p.id]: { ...form, id_value: (e.target as HTMLInputElement).value, error: "" } };
                  }}
                  onkeydown={(e) => {
                    if (e.key === "Enter") addIdentifier(p.id);
                  }}
                />
                <button class="btn btn-link" onclick={() => addIdentifier(p.id)}>OK</button>
                <button class="btn" onclick={() => toggleIdForm(p.id)}>&times;</button>
                {#if form.error}
                  <span class="id-error">{form.error}</span>
                {/if}
              </div>
            {:else}
              <button class="btn btn-add-id" title="Ajouter un identifiant" onclick={() => toggleIdForm(p.id)}>+ Identifiant</button>
            {/if}
          </td>
          <!-- Formes de noms -->
          <td>
            {#if p.name_forms?.length}
              <div class="name-forms-list">
                {#each p.name_forms as nf}
                  <button class="name-form-tag" class:ambiguous={nf.ambiguous} onclick={() => openDetachModal(p.id, nf.name_form)}>
                    {nf.name_form}
                  </button>
                {/each}
              </div>
            {:else}
              <span class="tag tag-unlinked">aucune</span>
            {/if}
          </td>
          <!-- Actions -->
          <td>
            {#if p.id in mergeSearches}
              {@const ms = mergeSearches[p.id]}
              <div class="merge-search">
                <div class="merge-input-row">
                  <input type="text" placeholder="Nom à absorber…" value={ms.query} oninput={(e) => handleMergeSearchInput(p.id, (e.target as HTMLInputElement).value)} />
                  <button class="btn" onclick={() => closeMergeSearch(p.id)}>&times;</button>
                </div>
                {#if ms.loading}
                  <div class="merge-results"><span class="loading-text">Recherche…</span></div>
                {:else if ms.results.length}
                  <div class="merge-results">
                    {#each ms.results as r}
                      <button class="merge-result" onclick={() => mergeInto(p.id, r.id)}>
                        <strong>{r.last_name}</strong>
                        {r.first_name}
                        {#if r.department_name}<span class="merge-dept">{r.department_name}</span>{/if}
                        {#if r.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
                      </button>
                    {/each}
                  </div>
                {:else if ms.query.trim().length >= 2}
                  <div class="merge-results"><span class="loading-text">Aucun résultat</span></div>
                {/if}
              </div>
            {:else}
              <button class="btn btn-merge-inline" onclick={() => openMergeSearch(p.id)}>Fusionner…</button>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>

  <Pagination page={currentPage} pages={totalPages} onchange={handlePageChange} />
{/if}

<!-- Modal de détachement -->
{#if detachModal}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="modal-overlay"
    onclick={() => {
      detachModal = null;
    }}
  >
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="modal-content" onclick={(e) => e.stopPropagation()}>
      <h3>Forme de nom : « {detachModal.nameForm} »</h3>
      {#if detachModal.loading}
        <p>Chargement…</p>
      {:else}
        {#if detachModal.otherPersons.length > 0}
          <div class="other-persons-section">
            <h4>Autres personnes partageant cette forme de nom</h4>
            <div class="other-persons-list">
              {#each detachModal.otherPersons as op}
                <div class="other-person-row">
                  <span class="other-person-name">
                    {op.first_name} <strong>{op.last_name}</strong>
                    {#if op.department_name}<span class="other-person-dept">({op.department_name})</span>{/if}
                    {#if op.has_rh}<span class="tag tag-rh">RH</span>{/if}
                  </span>
                  <button class="btn btn-sm btn-merge-modal" onclick={() => mergeFromModal(op.id)}> ← Fusionner </button>
                </div>
              {/each}
            </div>
          </div>
        {/if}
        {#if detachModal.authorships.length === 0}
          <p>Aucune authorship liée.</p>
          <div class="modal-actions">
            <button
              class="btn"
              onclick={() => {
                detachModal = null;
              }}>Annuler</button
            >
            <button class="btn btn-danger" onclick={detachNameForm}> Détacher cette forme </button>
          </div>
        {:else}
          <p>Cochez les authorships à détacher de cette personne :</p>
          <div class="detach-list">
            {#each detachModal.authorships as a, i}
              <label class="detach-item">
                <input type="checkbox" bind:checked={detachModal.authorships[i].checked} />
                <span class="detach-source tag tag-source">{a.source === "openalex" ? "OA" : a.source === "hal" ? "HAL" : "WoS"}</span>
                <span class="detach-year">{a.pub_year ?? "?"}</span>
                <span class="detach-title">{@html sanitizeTitle(a.title)}</span>
              </label>
            {/each}
          </div>
          <div class="modal-actions">
            <button
              class="btn"
              onclick={() => {
                detachModal = null;
              }}>Annuler</button
            >
            <button class="btn btn-danger" onclick={confirmDetach}>
              Détacher {detachModal.authorships.filter((a) => a.checked).length} authorship{detachModal.authorships.filter((a) => a.checked).length > 1 ? "s" : ""}
            </button>
          </div>
        {/if}
      {/if}
    </div>
  </div>
{/if}

<!-- Modal édition nom -->
{#if editNameModal}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="modal-overlay"
    onclick={() => {
      editNameModal = null;
    }}
  >
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="modal-content modal-small" onclick={(e) => e.stopPropagation()}>
      <h3>Modifier le nom</h3>
      <div class="edit-name-form">
        <label>
          Nom
          <input
            type="text"
            bind:value={editNameModal.lastName}
            onkeydown={(e) => {
              if (e.key === "Enter") savePersonName();
            }}
          />
        </label>
        <label>
          Prénom
          <input
            type="text"
            bind:value={editNameModal.firstName}
            onkeydown={(e) => {
              if (e.key === "Enter") savePersonName();
            }}
          />
        </label>
      </div>
      <div class="modal-actions">
        {#if editNameModal.rejected}
          <button class="btn btn-restore" onclick={() => toggleRejectPerson(editNameModal!.personId, false)}>Restaurer</button>
        {:else}
          <button class="btn btn-danger" onclick={() => toggleRejectPerson(editNameModal!.personId, true)}>Rejeter (fausse entité)</button>
        {/if}
        <span style="flex:1"></span>
        <button
          class="btn"
          onclick={() => {
            editNameModal = null;
          }}>Annuler</button
        >
        <button class="btn btn-confirm" onclick={savePersonName}>Enregistrer</button>
      </div>
    </div>
  </div>
{/if}

<style>
  /* ── Stats row ── */
  .stats-row {
    display: flex;
    gap: 10px;
    margin-bottom: 20px;
    flex-wrap: wrap;
  }
  .stat-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px 18px;
    text-align: center;
    flex: 1;
    min-width: 120px;
  }
  .stat-card .value {
    font-size: 1.55rem;
    font-weight: 700;
    line-height: 1.2;
  }
  .stat-card .label {
    font-size: 0.8rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .stat-card.hl-success {
    border-left: 3px solid var(--success);
  }
  .stat-card.hl-warning {
    border-left: 3px solid var(--warning);
  }
  .value-success {
    color: var(--success);
  }
  .value-warning {
    color: var(--warning);
  }

  /* ── Toolbar ── */
  .toolbar {
    margin-bottom: 16px;
  }
  .toolbar input {
    width: 250px;
    background: white;
  }
  .data-table {
    overflow: visible;
  }
  .period-cell {
    font-size: 0.85rem;
    color: var(--text-muted);
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
  .tag-linked {
    background: var(--success-light);
    color: var(--success);
  }
  .tag-unlinked {
    background: var(--warning-light);
    color: #8a6d10;
  }
  .tag-role {
    background: #eee;
    color: #555;
  }
  .tag-id {
    background: var(--accent-light);
    color: var(--accent);
    font-family: "SF Mono", SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 0.7rem;
  }
  .tag-source {
    background: #eee;
    color: #555;
    font-size: 0.7rem;
  }
  .tag-small {
    font-size: 0.7rem;
  }

  /* ── Linked authors toggle ── */
  .btn-toggle-authors {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 0.8rem;
    color: var(--accent);
    padding: 2px 4px;
    font-family: inherit;
    font-weight: 500;
  }
  .btn-toggle-authors:hover {
    text-decoration: underline;
  }
  .toggle-arrow {
    font-size: 0.7rem;
    margin-left: 2px;
  }
  .linked-authors-list {
    margin-top: 4px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .linked-author {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin: 1px 0;
  }

  /* ── Merge search ── */
  .btn-merge-inline {
    padding: 2px 8px;
    border: 1px dashed var(--border);
    border-radius: 4px;
    background: none;
    font-size: 0.8rem;
    cursor: pointer;
    color: var(--text-muted);
    margin-top: 4px;
    font-family: inherit;
  }
  .btn-merge-inline:hover {
    background: var(--warning-light);
    color: var(--warning);
    border-color: var(--warning);
  }
  .merge-search {
    margin-top: 4px;
    position: relative;
  }
  .merge-input-row {
    display: flex;
    gap: 4px;
    align-items: center;
  }
  .merge-input-row input {
    padding: 3px 6px;
    border: 1px solid var(--warning);
    border-radius: 3px;
    font-size: 0.85rem;
    font-family: inherit;
    width: 220px;
  }
  .merge-results {
    position: absolute;
    top: 100%;
    left: 0;
    z-index: 10;
    background: white;
    border: 1px solid var(--border);
    border-radius: 4px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    min-width: 280px;
    max-height: 200px;
    overflow-y: auto;
    padding: 4px 0;
  }
  .merge-result {
    display: block;
    width: 100%;
    text-align: left;
    padding: 6px 10px;
    border: none;
    background: none;
    cursor: pointer;
    font-size: 0.85rem;
    font-family: inherit;
  }
  .merge-result:hover {
    background: var(--warning-light);
  }
  .merge-dept {
    font-size: 0.8rem;
    color: var(--text-muted);
    margin-left: 6px;
  }

  /* ── Buttons ── */
  .btn-expand {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 1rem;
    padding: 2px 6px;
    color: var(--accent);
    font-family: inherit;
  }
  .btn-link {
    border-color: var(--success);
    color: var(--success);
  }
  .btn-link:hover {
    background: var(--success);
    color: white;
  }
  .btn-unlink {
    border: 1px solid var(--danger);
    color: var(--danger);
    font-size: 0.7rem;
    background: none;
    border-radius: 4px;
    cursor: pointer;
    padding: 1px 5px;
    font-family: inherit;
  }
  .btn-unlink:hover {
    background: var(--danger);
    color: white;
  }
  .btn-detail {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 0.8rem;
    color: var(--accent);
    padding: 2px 4px;
    text-decoration: underline;
    font-family: inherit;
  }

  /* ── Publications ── */
  .pub-list {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .pub-list li {
    padding: 3px 0;
    border-bottom: 1px solid #f0efec;
  }
  .pub-list li:last-child {
    border-bottom: none;
  }
  .pub-year {
    font-size: 0.7rem;
    color: var(--text-muted);
    font-weight: 600;
    margin-right: 4px;
  }
  .btn-reassign {
    color: var(--accent);
  }
  .reassign-inline {
    display: inline-flex;
    gap: 4px;
    align-items: center;
    margin-left: 4px;
  }
  .reassign-input {
    width: 80px;
    padding: 2px 6px;
    font-size: 0.8rem;
    border: 1px solid var(--border);
    border-radius: 3px;
  }
  .pub-title {
    color: #333;
  }
  .pub-uca {
    color: var(--success);
    font-size: 0.7rem;
    font-weight: 600;
  }
  .pub-doi {
    font-size: 0.7rem;
    color: var(--accent);
    text-decoration: none;
    margin-left: 4px;
  }
  .pub-doi:hover {
    text-decoration: underline;
  }

  /* ── Identifiers ── */
  .identifiers-row {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-bottom: 4px;
  }
  .identifier-tag {
    display: inline-flex;
    align-items: center;
    gap: 2px;
  }
  .identifier-tag.rejected {
    opacity: 0.45;
    text-decoration: line-through;
  }
  .identifier-tag.confirmed .tag-id {
    background: #d4edda;
    color: #155724;
  }
  .identifier-tag.rejected .tag-id {
    background: #f8d7da;
    color: #721c24;
  }
  .btn-status {
    background: none;
    border: 1px solid #ccc;
    border-radius: 3px;
    cursor: pointer;
    font-size: 0.75rem;
    padding: 0 3px;
    line-height: 1.2;
    color: #999;
  }
  .btn-status:hover {
    background: #f0f0f0;
  }
  .btn-status.active {
    color: #28a745;
    border-color: #28a745;
    font-weight: bold;
  }
  .btn-status.btn-reject.active {
    color: #dc3545;
    border-color: #dc3545;
  }
  .btn-reject {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 0.85rem;
    padding: 0 2px;
    color: var(--text-muted);
    font-family: inherit;
  }
  .btn-reject:hover {
    color: #c0392b;
  }
  .btn-add-id {
    padding: 2px 8px;
    border: 1px dashed var(--border);
    border-radius: 4px;
    background: none;
    font-size: 0.8rem;
    cursor: pointer;
    color: var(--accent);
    margin-top: 4px;
    font-family: inherit;
  }
  .btn-add-id:hover {
    background: var(--accent-light);
    border-style: solid;
  }
  .id-form {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-top: 4px;
    flex-wrap: wrap;
  }
  .id-form select,
  .id-form input {
    padding: 3px 6px;
    border: 1px solid var(--border);
    border-radius: 3px;
    font-size: 0.85rem;
    font-family: inherit;
  }
  .id-form select {
    width: 80px;
  }
  .id-form input {
    width: 180px;
  }
  .id-error {
    font-size: 0.8rem;
    color: var(--danger);
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
  .uca-count {
    font-size: 0.85em;
    color: var(--muted);
  }
  /* ── Misc ── */
  .loading-text {
    color: var(--text-muted);
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
  .nf-sources {
    color: #888;
    font-size: 0.7rem;
  }

  /* ── Modal ── */
  .detach-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin: 12px 0;
  }
  .detach-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 8px;
    border-radius: 4px;
    cursor: pointer;
  }
  .detach-item:hover {
    background: #f5f5f5;
  }
  .detach-source {
    flex-shrink: 0;
  }
  .detach-year {
    color: #888;
    font-size: 0.8rem;
    min-width: 30px;
  }
  .detach-title {
    font-size: 0.85rem;
  }
  .other-persons-section {
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid #e0e0e0;
  }
  .other-persons-section h4 {
    margin: 0 0 8px;
    font-size: 0.9rem;
    color: #666;
  }
  .other-persons-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .other-person-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 4px 8px;
    border-radius: 4px;
  }
  .other-person-row:hover {
    background: #f5f5f5;
  }
  .other-person-name {
    font-size: 0.9rem;
  }
  .other-person-dept {
    color: #888;
    font-size: 0.8rem;
  }
  .btn-merge-modal {
    background: #1976d2;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
  }
  .btn-merge-modal:hover {
    background: #1565c0;
  }

  /* ── Edit name ── */
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
  .modal-small {
    max-width: 400px;
  }
  .edit-name-form {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin: 12px 0;
  }
  .edit-name-form label {
    display: flex;
    flex-direction: column;
    gap: 3px;
    font-size: 0.85rem;
    font-weight: 500;
  }
  .edit-name-form input {
    padding: 6px 8px;
    border: 1px solid #ccc;
    border-radius: 4px;
    font-size: 0.9rem;
  }
  .btn-restore {
    background: #4caf50;
    color: white;
    border: none;
    padding: 6px 14px;
    border-radius: 4px;
    cursor: pointer;
  }
  .btn-restore:hover {
    background: #388e3c;
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
  .orphan-panel {
    margin-bottom: 16px;
  }
  .orphan-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
  }
  .orphan-header h2 {
    margin: 0;
    font-size: 1.1rem;
  }
  .orphan-toolbar {
    margin-bottom: 10px;
  }
  .orphan-toolbar input {
    padding: 6px 10px;
    border: 1px solid #ccc;
    border-radius: 4px;
    width: 300px;
  }
  .orphan-assign {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    align-items: flex-start;
  }
  .orphan-assign input {
    padding: 4px 8px;
    border: 1px solid #ccc;
    border-radius: 4px;
    font-size: 0.85rem;
    width: 180px;
  }
  .orphan-results {
    display: flex;
    flex-direction: column;
    gap: 2px;
    width: 100%;
  }
  .pub-link {
    color: var(--accent);
    text-decoration: none;
    font-size: 0.85rem;
  }
  .pub-link:hover {
    text-decoration: underline;
  }
</style>
