<script lang="ts">
  import { base } from "$app/paths";
  import { api } from "$lib/api";
  import { titleCase } from "$lib/utils";
  import type { Person, IdFormState, PersonSearchResult } from "./types";
  import type { components } from "$lib/api/schema";
  import IdentifiersCell from "./IdentifiersCell.svelte";
  import MergeSearchCell from "./MergeSearchCell.svelte";
  import NameFormsList from "./NameFormsList.svelte";

  type SharingPerson = components["schemas"]["SharingPersonOut"];

  let {
    person,
    idForm,
    mergeActive,
    mergeSearch,
    onclose,
    onrename,
    onToggleReject,
    onaddIdentifier,
    ontoggleIdForm,
    onsetIdentifierStatus,
    onopenDetach,
    onsetFormStatus,
    onmergeOpen,
    onmergeClose,
    onmerge,
    onabsorb,
  }: {
    person: Person;
    idForm: IdFormState | null;
    mergeActive: boolean;
    mergeSearch: {
      query: string;
      loading: boolean;
      results: PersonSearchResult[];
      setQuery: (q: string) => void;
    };
    onclose: () => void;
    /** Renvoie true si le renommage a réussi (sinon l'édition reste ouverte). */
    onrename: (personId: number, lastName: string, firstName: string) => Promise<boolean>;
    onToggleReject: (personId: number, rejected: boolean) => void | Promise<void>;
    onaddIdentifier: (personId: number) => void | Promise<void>;
    ontoggleIdForm: (personId: number) => void;
    onsetIdentifierStatus: (identId: number, status: string) => void | Promise<void>;
    onopenDetach: (personId: number, nameForm: string) => void | Promise<void>;
    onsetFormStatus: (
      personId: number,
      nameForm: string,
      status: string,
    ) => void | Promise<void>;
    onmergeOpen: (personId: number) => void;
    onmergeClose: () => void;
    onmerge: (targetId: number, sourceId: number) => void | Promise<void>;
    /** Absorbe une autre personne dans celle du drawer (fusion vers `person`). */
    onabsorb: (otherId: number) => Promise<void>;
  } = $props();

  // Personnes partageant ≥1 forme de nom (candidates à l'absorption).
  let sharing = $state<SharingPerson[]>([]);

  async function loadSharing() {
    sharing = await api<SharingPerson[]>(`/api/admin/persons/${person.id}/sharing-name-forms`);
  }

  $effect(() => {
    void person.id; // re-fetch quand le drawer change de personne
    loadSharing();
  });

  async function absorb(otherId: number) {
    await onabsorb(otherId);
    await loadSharing();
  }

  let editing = $state(false);
  let lastName = $state("");
  let firstName = $state("");

  // Verrouille le scroll de fond tant que le drawer est ouvert : sans ça, la
  // scrollbar de page chevauche le bord droit du panneau et masque ses boutons.
  $effect(() => {
    const body = document.body.style.overflow;
    const html = document.documentElement.style.overflow;
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = body;
      document.documentElement.style.overflow = html;
    };
  });

  function startEdit() {
    lastName = person.last_name;
    firstName = person.first_name;
    editing = true;
  }

  async function saveEdit() {
    if (await onrename(person.id, lastName, firstName)) editing = false;
  }

  function formatDate(d: string | null): string {
    return d ? new Date(d).toLocaleDateString("fr-FR") : "";
  }

  function dateRange(start: string | null, end: string | null): string {
    if (start && end) return `${formatDate(start)} – ${formatDate(end)}`;
    if (start) return `depuis le ${formatDate(start)}`;
    if (end) return `jusqu'au ${formatDate(end)}`;
    return "";
  }

  function onkeydown(e: KeyboardEvent) {
    if (e.key !== "Escape") return;
    if (editing) editing = false;
    else onclose();
  }
</script>

<svelte:window {onkeydown} />

<button class="drawer-backdrop" aria-label="Fermer le panneau" onclick={onclose}></button>

<aside class="drawer" class:rejected={person.rejected}>
  <header class="drawer-head">
    {#if editing}
      <form class="drawer-edit" onsubmit={(e) => { e.preventDefault(); saveEdit(); }}>
        <input class="edit-input" bind:value={lastName} placeholder="Nom" aria-label="Nom" />
        <input class="edit-input" bind:value={firstName} placeholder="Prénom" aria-label="Prénom" />
        <button type="submit" class="btn btn-icon-sm btn-confirm-outline" title="Enregistrer"
          >&#x2713;</button
        >
        <button type="button" class="btn btn-icon-sm" title="Annuler" onclick={() => (editing = false)}
          >&#x2715;</button
        >
      </form>
    {:else}
      <div class="drawer-title">
        <a
          class="drawer-name-link"
          href="{base}/persons/{person.id}"
          target="_blank"
          rel="noopener"
          title="Voir la fiche publique"
        >
          <span class="drawer-last">{titleCase(person.last_name)}</span>
          {titleCase(person.first_name)}
        </a>
        {#if person.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
      </div>
      <div class="drawer-head-actions">
        <button class="icon-btn" title="Modifier le nom" aria-label="Modifier le nom" onclick={startEdit}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" /><path d="m15 5 4 4" /></svg>
        </button>
        <button
          class="icon-btn"
          class:rejected={person.rejected}
          title={person.rejected ? "Restaurer la personne" : "Rejeter (fausse entité)"}
          aria-label={person.rejected ? "Restaurer la personne" : "Rejeter la personne"}
          onclick={() => onToggleReject(person.id, !person.rejected)}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
        </button>
        <button class="drawer-close" title="Fermer" aria-label="Fermer" onclick={onclose}>&times;</button>
      </div>
    {/if}
  </header>

  <div class="drawer-body">
    <div class="drawer-meta">
      <span>{person.pub_count ?? 0} publications</span>
      <span>{person.uca_pub_count ?? 0} UCA</span>
      {#if person.rejected}<span class="tag tag-rejected">rejetée</span>{/if}
    </div>

    {#if person.has_rh}
      <section class="drawer-section">
        <h3>Fiche RH</h3>
        <dl class="rh-info">
          {#if person.role_title}
            <dt>Rôle</dt>
            <dd>{person.role_title}</dd>
          {/if}
          {#if person.department_name}
            <dt>Département</dt>
            <dd>{person.department_name}</dd>
          {/if}
          {#if person.start_date || person.end_date}
            <dt>Dates</dt>
            <dd>{dateRange(person.start_date, person.end_date)}</dd>
          {/if}
        </dl>
      </section>
    {/if}

    <section class="drawer-section">
      <h3>Identifiants</h3>
      <IdentifiersCell
        {person}
        form={idForm}
        onadd={onaddIdentifier}
        ontoggleForm={ontoggleIdForm}
        onsetStatus={onsetIdentifierStatus}
      />
    </section>

    <section class="drawer-section">
      <h3>Formes de nom</h3>
      <NameFormsList {person} onopenDetail={onopenDetach} onsetStatus={onsetFormStatus} />
    </section>

    {#if sharing.length}
      <section class="drawer-section">
        <h3>Personnes partageant une forme de nom</h3>
        <div class="sharing-list">
          {#each sharing as sp (sp.id)}
            <div class="sharing-row">
              <button
                class="btn btn-sm"
                title="Fusionner cette personne dans celle-ci"
                onclick={() => absorb(sp.id)}>Absorber</button
              >
              <span class="sharing-name">
                <span class="person-last">{titleCase(sp.last_name)}</span>
                {titleCase(sp.first_name)}
              </span>
              {#if sp.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
              <span class="sharing-forms" title={sp.shared_forms.join(", ")}>
                {sp.shared_forms.length} forme{sp.shared_forms.length > 1 ? "s" : ""}
              </span>
            </div>
          {/each}
        </div>
      </section>
    {/if}

    <section class="drawer-section">
      <h3>Fusion</h3>
      <MergeSearchCell
        targetPersonId={person.id}
        active={mergeActive}
        {mergeSearch}
        onopen={onmergeOpen}
        onclose={onmergeClose}
        {onmerge}
      />
    </section>
  </div>
</aside>

<style>
  .drawer-backdrop {
    position: fixed;
    top: var(--header-height, 46px);
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.25);
    border: none;
    padding: 0;
    cursor: pointer;
    z-index: 90;
  }
  .drawer {
    position: fixed;
    top: var(--header-height, 46px);
    right: 0;
    height: calc(100vh - var(--header-height, 46px));
    width: min(480px, 92vw);
    background: #fff;
    box-shadow: -4px 0 16px rgba(0, 0, 0, 0.15);
    z-index: 91;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .drawer.rejected .drawer-title {
    text-decoration: line-through;
    opacity: 0.7;
  }
  .drawer-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    padding: 16px 18px;
    border-bottom: 1px solid var(--border, #e0e0e0);
  }
  .drawer-title {
    font-size: 1.1rem;
  }
  .drawer-name-link {
    color: inherit;
    text-decoration: none;
  }
  .drawer-name-link:hover {
    color: #2563eb;
    text-decoration: underline;
  }
  .drawer-last {
    font-weight: 600;
  }
  .drawer-head-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }
  .drawer-edit {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .drawer-edit .btn {
    flex-shrink: 0;
  }
  .edit-input {
    width: 128px;
    padding: 4px 6px;
    border: 1px solid #ccc;
    border-radius: 4px;
    font-size: 0.9rem;
  }
  .icon-btn {
    background: none;
    border: none;
    cursor: pointer;
    padding: 3px;
    color: #888;
    display: inline-flex;
    align-items: center;
    border-radius: 4px;
  }
  .icon-btn:hover {
    color: var(--accent, #1976d2);
    background: #f0f0f0;
  }
  .icon-btn.rejected {
    color: var(--danger, #c0392b);
  }
  .drawer-close {
    background: none;
    border: none;
    font-size: 1.5rem;
    line-height: 1;
    cursor: pointer;
    color: #888;
    padding: 0 4px;
  }
  .drawer-close:hover {
    color: #333;
  }
  .drawer-body {
    flex: 1;
    overflow-y: auto;
    padding: 16px 18px;
  }
  .drawer-meta {
    display: flex;
    gap: 14px;
    align-items: center;
    color: #555;
    font-size: 0.85rem;
    margin-bottom: 18px;
  }
  .drawer-section {
    margin-bottom: 22px;
  }
  .rh-info {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 3px 12px;
    margin: 0;
    font-size: 0.85rem;
  }
  .rh-info dt {
    color: #888;
  }
  .rh-info dd {
    margin: 0;
  }
  .drawer-section h3 {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #888;
    margin: 0 0 8px;
  }
  .sharing-list {
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .sharing-row {
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }
  .sharing-name {
    font-size: 0.9rem;
  }
  .sharing-forms {
    font-size: 0.72rem;
    color: #888;
  }
  .tag {
    display: inline-block;
    font-size: 0.8rem;
    padding: 1px 7px;
    border-radius: 10px;
    font-weight: 500;
  }
  .tag-rejected {
    background: #fdecea;
    color: #b71c1c;
  }
</style>
