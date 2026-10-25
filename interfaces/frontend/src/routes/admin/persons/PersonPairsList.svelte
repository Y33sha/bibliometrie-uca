<script lang="ts" generics="Pair extends { person_a: CurationPerson; person_b: CurationPerson }">
  import { untrack, type Snippet } from "svelte";
  import { ApiError, persons as personsApi } from "#lib/api/index.js";
  import { titleCase } from "#lib/utils.js";
  import { usePaginatedFetch } from "#lib/composables/usePaginatedFetch.svelte.js";
  import Pagination from "#lib/components/Pagination.svelte";
  import { confirmMerge } from "./confirmMerge";
  import type { CurationPerson } from "./types";

  let {
    endpoint,
    apiKey,
    emptyText,
    distinctTitle,
    intro,
    pairHeader,
    onopenPerson,
    onchange,
    reloadKey,
  }: {
    /** Route de la file de paires, au format `{ pairs, page, pages }`. */
    endpoint: string;
    apiKey: string;
    emptyText: string;
    /** Info-bulle du bouton « Distinctes ». */
    distinctTitle: string;
    intro: Snippet;
    /** Ligne affichée au-dessus des deux personnes d'une paire. */
    pairHeader: Snippet<[Pair]>;
    /** Ouvre le drawer d'une personne. */
    onopenPerson: (personId: number) => void;
    /** Notifie le parent après une mutation (rafraîchir le badge de l'onglet). */
    onchange: () => void;
    /** Incrémenté par le parent après une action dans le drawer → recharge la file. */
    reloadKey: number;
  } = $props();

  const list = usePaginatedFetch<Pair>({
    // svelte-ignore state_referenced_locally
    endpoint,
    itemsKey: "pairs",
    // svelte-ignore state_referenced_locally
    apiKey,
    buildParams: () => new URLSearchParams(),
    pageParam: null,
  });
  let acting = $state(false);
  let error = $state("");

  async function merge(targetId: number, sourceId: number) {
    if (!(await confirmMerge(sourceId))) return;
    acting = true;
    error = "";
    try {
      await personsApi.merge(targetId, sourceId);
      await list.load();
      onchange();
    } catch (e) {
      error = e instanceof ApiError ? `Erreur ${e.status}` : "Erreur de fusion";
    }
    acting = false;
  }

  async function markDistinct(a: number, b: number) {
    acting = true;
    error = "";
    try {
      await personsApi.markDistinct(a, b);
      await list.load();
      onchange();
    } catch {
      error = "Erreur";
    }
    acting = false;
  }

  // Charge au montage et à chaque incrément de `reloadKey` (action dans le drawer).
  $effect(() => {
    void reloadKey;
    untrack(list.load);
  });
</script>

<p class="triage-intro">{@render intro()}</p>

{#if error}<p class="error">{error}</p>{/if}

{#if !list.loaded}
  <div class="empty">Chargement…</div>
{:else if list.items.length === 0 && !list.loading}
  <div class="empty">{emptyText}</div>
{:else}
  <div class="triage-list">
    {#each list.items as pair, i (i)}
      <div class="triage-item">
        {@render pairHeader(pair)}
        <div class="pair-body">
          {@render personCol(pair.person_a)}
          <div class="actions">
            {#if !pair.person_b.has_rh}
              <button
                class="act keep"
                disabled={acting}
                title="Garder la personne de gauche, absorber celle de droite"
                onclick={() => merge(pair.person_a.person_id, pair.person_b.person_id)}
                >&larr; Fusionner</button
              >
            {/if}
            <button
              class="act distinct"
              disabled={acting}
              title={distinctTitle}
              onclick={() => markDistinct(pair.person_a.person_id, pair.person_b.person_id)}
              >Distinctes</button
            >
            {#if !pair.person_a.has_rh}
              <button
                class="act keep"
                disabled={acting}
                title="Garder la personne de droite, absorber celle de gauche"
                onclick={() => merge(pair.person_b.person_id, pair.person_a.person_id)}
                >Fusionner &rarr;</button
              >
            {/if}
          </div>
          {@render personCol(pair.person_b)}
        </div>
      </div>
    {/each}
  </div>

  <Pagination page={list.page} pages={list.pages} onchange={list.goToPage} />
{/if}

{#snippet personCol(p: CurationPerson)}
  <div class="person-col">
    <button class="triage-person" onclick={() => onopenPerson(p.person_id)}>
      <span class="triage-person-last">{titleCase(p.last_name)}</span>
      {titleCase(p.first_name)}
    </button>
    {#if p.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
    <div class="meta">{p.contribution_count} publication{p.contribution_count !== 1 ? "s" : ""}</div>
    {#if p.labs.length}
      <div class="labs">
        {#each p.labs as lab (lab)}<span class="lab-badge">{lab}</span>{/each}
      </div>
    {/if}
  </div>
{/snippet}

<style>
  .pair-body {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    gap: 12px;
    align-items: center;
  }
  @media (max-width: 700px) {
    .pair-body {
      grid-template-columns: 1fr;
    }
  }
  .person-col {
    min-width: 0;
  }
  .meta {
    font-size: 0.78rem;
    color: var(--muted);
    margin-top: 2px;
  }
  .labs {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 4px;
  }
  .lab-badge {
    font-size: 0.72rem;
    background: var(--accent-light);
    color: var(--accent);
    border-radius: var(--radius-pill);
    padding: 1px 7px;
  }
  .actions {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .act {
    padding: 4px 10px;
    font-size: 0.8rem;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--card);
    cursor: pointer;
    white-space: nowrap;
    font-family: inherit;
  }
  .act:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .act.keep:hover:not(:disabled) {
    background: var(--success-light);
    border-color: var(--success);
  }
  .act.distinct:hover:not(:disabled) {
    background: var(--warning-light);
    border-color: var(--warning);
  }
  .error {
    color: var(--danger);
    background: var(--danger-light);
    padding: 6px 10px;
    border-radius: var(--radius);
    margin-bottom: 10px;
  }
</style>
