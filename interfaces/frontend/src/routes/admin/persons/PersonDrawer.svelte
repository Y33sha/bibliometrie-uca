<script lang="ts">
  import { base } from "$app/paths";
  import { titleCase } from "$lib/utils";
  import type { Person, IdFormState, PersonSearchResult } from "./types";
  import IdentifiersCell from "./IdentifiersCell.svelte";
  import MergeSearchCell from "./MergeSearchCell.svelte";
  import NameFormsList from "./NameFormsList.svelte";

  let {
    person,
    idForm,
    mergeActive,
    mergeSearch,
    onclose,
    oneditName,
    onaddIdentifier,
    ontoggleIdForm,
    onsetIdentifierStatus,
    onopenDetach,
    onsetFormStatus,
    onmergeOpen,
    onmergeClose,
    onmerge,
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
    oneditName: (person: Person) => void;
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
  } = $props();

  function onkeydown(e: KeyboardEvent) {
    if (e.key === "Escape") onclose();
  }
</script>

<svelte:window {onkeydown} />

<button class="drawer-backdrop" aria-label="Fermer le panneau" onclick={onclose}></button>

<aside class="drawer" class:rejected={person.rejected}>
  <header class="drawer-head">
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
      <button class="btn btn-sm" onclick={() => oneditName(person)}>Modifier le nom</button>
      <button class="drawer-close" title="Fermer" aria-label="Fermer" onclick={onclose}>&times;</button>
    </div>
  </header>

  <div class="drawer-body">
    <div class="drawer-meta">
      <span>{person.pub_count ?? 0} publications</span>
      <span>{person.uca_pub_count ?? 0} UCA</span>
      {#if person.rejected}<span class="tag tag-rejected">rejetée</span>{/if}
    </div>

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
  .rh-check {
    color: var(--success, #2e7d32);
    margin-left: 4px;
  }
  .drawer-head-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
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
  .drawer-section h3 {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #888;
    margin: 0 0 8px;
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
