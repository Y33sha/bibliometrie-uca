<script lang="ts">
  import { onMount } from "svelte";
  import { base } from "$app/paths";
  import { replaceState } from "$app/navigation";
  import { api, ApiError, orphanAuthorships, persons as personsApi } from "$lib/api";
  import { toast } from "$lib/dialogs.svelte";
  import { useDebouncedSearch } from "$lib/composables/useDebouncedSearch.svelte";
  import { titleCase } from "$lib/utils";
  import type { FacetOption } from "$lib/components/FacetDropdown.svelte";
  import Pagination from "$lib/components/Pagination.svelte";
  import type {
    DetachModalState,
    DetachPublication,
    IdFormState,
    OtherPerson,
    Person,
    PersonListResponse,
    PersonSearchResult,
    PersonStats,
  } from "./types";
  import type { components } from "$lib/api/schema";
  type NameFormAuthorshipRef = components["schemas"]["NameFormAuthorshipRef"];
  import PersonsToolbar from "./PersonsToolbar.svelte";
  import DetachNameFormModal from "./DetachNameFormModal.svelte";
  import PersonDrawer from "./PersonDrawer.svelte";
  import AmbiguousFormsList from "./AmbiguousFormsList.svelte";
  import IdentifierConflictsList from "./IdentifierConflictsList.svelte";

  /* ── State ── */

  let stats = $state<PersonStats | null>(null);
  let orphanCount = $state(0);

  // Onglets du hub : liste maîtresse + files de triage.
  type TabKey = "all" | "ambiguous-forms" | "identifier-conflicts";
  let tab = $state<TabKey>("all");
  let ambiguousCount = $state(0);
  let identifierConflictCount = $state(0);
  // Bumpé après chaque action du drawer pour recharger la file de triage active.
  let reloadFiles = $state(0);

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

  let detachModal: DetachModalState | null = $state(null);

  // Drawer-personne : ouvert quand `?person=:id` est dans l'URL. La personne vient
  // de la liste chargée si elle y est, sinon d'un fetch dédié (ouverture depuis une
  // file de triage, où la liste maîtresse n'est pas chargée).
  let selectedPersonId: number | null = $state(null);
  let fetchedPerson: Person | null = $state(null);
  const selectedPerson = $derived.by(() => {
    if (selectedPersonId === null) return null;
    return (
      persons.find((p) => p.id === selectedPersonId) ??
      (fetchedPerson?.id === selectedPersonId ? fetchedPerson : null)
    );
  });

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
    setOrDel("person", selectedPersonId ? String(selectedPersonId) : "");
    setOrDel("tab", tab !== "all" ? tab : "");
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
    if (p.get("person")) selectedPersonId = parseInt(p.get("person")!, 10) || null;
    const t = p.get("tab");
    if (t === "ambiguous-forms" || t === "identifier-conflicts") tab = t;
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
    await refreshSelected();
  }

  async function setIdentifierStatus(identId: number, status: string) {
    await personsApi.setIdentifierStatus(identId, status);
    await loadTable();
    await refreshSelected();
  }

  /* ── Orphans ── */

  async function loadOrphanCount() {
    const data = await api<{ total: number }>("/api/admin/orphan-authorships/count");
    orphanCount = data.total;
  }

  /* ── Onglets / files de triage ── */

  async function loadAmbiguousCount() {
    const data = await api<{ total: number }>("/api/admin/ambiguous-name-forms/count");
    ambiguousCount = data.total;
  }

  async function loadIdentifierConflictCount() {
    const data = await api<{ total: number }>("/api/admin/identifier-conflicts/count");
    identifierConflictCount = data.total;
  }

  function selectTab(t: TabKey) {
    tab = t;
    updateUrl();
  }

  /* ── Edit name ── */

  async function renamePerson(
    personId: number,
    lastName: string,
    firstName: string,
  ): Promise<boolean> {
    try {
      await personsApi.rename(personId, lastName, firstName);
    } catch (e) {
      const status = e instanceof ApiError ? e.status : "?";
      const detail = e instanceof ApiError ? (e.detail as { detail?: string })?.detail : null;
      toast(detail || `Erreur ${status}`, "error");
      return false;
    }
    await loadTable();
    await refreshSelected();
    return true;
  }

  async function togglePersonReject(personId: number, rejected: boolean) {
    await personsApi.setRejected(personId, rejected);
    await loadTable();
    await refreshSelected();
  }

  /* ── Detach modal ── */

  async function openDetachModal(personId: number, nameForm: string) {
    detachModal = { personId, nameForm, publications: [], otherPersons: [], loading: true };
    const data = await api<{ authorships: NameFormAuthorshipRef[]; other_persons: OtherPerson[] }>(
      `/api/persons/${personId}/name-form-authorships?name_form=${encodeURIComponent(nameForm)}`,
    );
    // Le rejet porte sur la publication entière : on regroupe les sources par
    // publication pour n'afficher qu'une ligne par publi.
    const byPub = new Map<number, DetachPublication>();
    for (const r of data.authorships) {
      let pub = byPub.get(r.pub_id);
      if (!pub) {
        pub = { pub_id: r.pub_id, title: r.title, pub_year: r.pub_year, sources: [], checked: true };
        byPub.set(r.pub_id, pub);
      }
      pub.sources.push({ source: r.source, authorship_id: r.authorship_id });
    }
    detachModal = {
      personId,
      nameForm,
      loading: false,
      publications: [...byPub.values()],
      otherPersons: data.other_persons,
    };
  }

  async function confirmDetach() {
    if (!detachModal) return;
    const toDetach = detachModal.publications.filter((p) => p.checked);
    if (toDetach.length === 0) {
      detachModal = null;
      return;
    }
    // Une référence de source par publication suffit : le backend détache
    // toutes les sources de la publication.
    await personsApi.detachAuthorships(detachModal.personId, {
      authorships: toDetach.map((p) => p.sources[0]),
    });
    detachModal = null;
    loadStats();
    loadTable();
  }

  async function setNameFormStatus(personId: number, nameForm: string, status: string) {
    await personsApi.updateNameFormStatus(
      personId,
      nameForm,
      status as "pending" | "confirmed" | "rejected",
    );
    await loadTable();
    await refreshSelected();
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
    await loadTable();
    await refreshSelected();
    loadAmbiguousCount();
    loadIdentifierConflictCount();
  }

  // Absorbe une autre personne (sourceId) dans celle du drawer (la cible).
  async function absorbPerson(otherId: number) {
    if (selectedPersonId === null) return;
    try {
      await personsApi.merge(selectedPersonId, otherId);
    } catch (e) {
      const detail = e instanceof ApiError ? (e.detail as { detail?: string })?.detail : null;
      toast(detail || "Fusion impossible", "error");
      return;
    }
    loadStats();
    await loadTable();
    await refreshSelected();
    loadAmbiguousCount();
    loadIdentifierConflictCount();
  }

  async function mergeFromModal(sourceId: number) {
    if (!detachModal) return;
    const targetId = detachModal.personId;
    await personsApi.merge(targetId, sourceId);
    detachModal = null;
    loadStats();
    loadTable();
  }

  /* ── Drawer ── */

  async function openDrawer(personId: number) {
    selectedPersonId = personId;
    updateUrl();
    if (!persons.some((p) => p.id === personId)) {
      fetchedPerson = await api<Person>(`/api/admin/persons/${personId}`);
    }
  }

  // Rafraîchit la personne du drawer après une mutation, quand elle ne vient pas
  // de la liste maîtresse (sinon `loadTable` s'en charge via le derived).
  async function refreshSelected() {
    if (selectedPersonId !== null && !persons.some((p) => p.id === selectedPersonId)) {
      fetchedPerson = await api<Person>(`/api/admin/persons/${selectedPersonId}`);
    }
    // Toute action du drawer passe ici → recharge les files de triage affichées.
    reloadFiles++;
  }

  function closeDrawer() {
    selectedPersonId = null;
    fetchedPerson = null;
    closeMergeSearch();
    updateUrl();
  }

  /* ── Lifecycle ── */

  onMount(async () => {
    readUrlFilters();
    loadFacets();
    await loadTable();
    loadOrphanCount();
    loadAmbiguousCount();
    loadIdentifierConflictCount();
    // Deep-link `?person=` vers une personne hors de la page courante.
    await refreshSelected();
  });
</script>

<svelte:head>
  <title>Admin - Personnes - Bibliom&eacute;trie UCA</title>
</svelte:head>

<nav class="hub-tabs">
  <button class="hub-tab" class:active={tab === "all"} onclick={() => selectTab("all")}>
    Toutes les personnes
  </button>
  <button
    class="hub-tab"
    class:active={tab === "ambiguous-forms"}
    onclick={() => selectTab("ambiguous-forms")}
  >
    Formes ambigu&euml;s
    {#if ambiguousCount > 0}<span class="tab-badge">{ambiguousCount}</span>{/if}
  </button>
  <button
    class="hub-tab"
    class:active={tab === "identifier-conflicts"}
    onclick={() => selectTab("identifier-conflicts")}
  >
    Conflits d'identifiant
    {#if identifierConflictCount > 0}<span class="tab-badge">{identifierConflictCount}</span>{/if}
  </button>
</nav>

{#if tab === "all"}
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
      </tr>
    </thead>
    <tbody>
      {#each persons as p (p.id)}
        <tr class:rejected={p.rejected}>
          <td class="td-name">
            <button
              type="button"
              class="person-name"
              class:active={selectedPersonId === p.id}
              onclick={() => openDrawer(p.id)}
            >
              <span class="person-last">{titleCase(p.last_name)}</span>
              {titleCase(p.first_name)}
            </button>
            {#if p.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
          </td>
          <td>{p.pub_count ?? 0}</td>
          <td>{p.uca_pub_count ?? 0}</td>
        </tr>
      {/each}
    </tbody>
  </table>

  <Pagination page={currentPage} pages={totalPages} onchange={handlePageChange} />
  {/if}
{:else if tab === "ambiguous-forms"}
  <AmbiguousFormsList
    onopenPerson={openDrawer}
    onchange={loadAmbiguousCount}
    reloadKey={reloadFiles}
  />
{:else if tab === "identifier-conflicts"}
  <IdentifierConflictsList
    onopenPerson={openDrawer}
    onchange={loadIdentifierConflictCount}
    reloadKey={reloadFiles}
  />
{/if}

{#if selectedPerson}
  <PersonDrawer
    person={selectedPerson}
    idForm={idForms[selectedPerson.id] ?? null}
    mergeActive={activeMergePersonId === selectedPerson.id}
    {mergeSearch}
    onclose={closeDrawer}
    onrename={renamePerson}
    onToggleReject={togglePersonReject}
    onaddIdentifier={addIdentifier}
    ontoggleIdForm={toggleIdForm}
    onsetIdentifierStatus={setIdentifierStatus}
    onopenDetach={openDetachModal}
    onsetFormStatus={setNameFormStatus}
    onmergeOpen={openMergeSearch}
    onmergeClose={closeMergeSearch}
    onmerge={mergeInto}
    onabsorb={absorbPerson}
    onopenPerson={openDrawer}
  />
{/if}

{#if detachModal}
  <DetachNameFormModal
    bind:state={detachModal}
    onclose={() => {
      detachModal = null;
    }}
    onconfirmDetach={confirmDetach}
    onmerge={mergeFromModal}
  />
{/if}


<style>
  .hub-tabs {
    display: flex;
    gap: 4px;
    border-bottom: 1px solid var(--border, #e0e0e0);
    margin-bottom: 14px;
  }
  .hub-tab {
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 14px;
    cursor: pointer;
    font: inherit;
    color: #666;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .hub-tab:hover {
    color: #222;
  }
  .hub-tab.active {
    color: var(--accent, #1976d2);
    border-bottom-color: var(--accent, #1976d2);
    font-weight: 600;
  }
  .tab-badge {
    background: var(--accent, #1976d2);
    color: white;
    border-radius: 10px;
    font-size: 0.72rem;
    padding: 0 7px;
    font-weight: 600;
  }
  .data-table {
    overflow: visible;
  }
  .sortable:hover {
    color: #2563eb;
  }
  .col-name {
    min-width: 200px;
  }
  .td-name {
    position: relative;
  }
  .person-name {
    font-weight: 500;
    color: inherit;
    text-decoration: none;
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    font: inherit;
    text-align: left;
  }
  .person-name:hover {
    color: #2563eb;
    text-decoration: underline;
  }
  .person-name.active {
    color: #2563eb;
  }
  .person-last {
    font-weight: 600;
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
