<script lang="ts">
  import { untrack } from "svelte";
  import { ApiError, api, persons as personsApi } from "$lib/api";
  import { titleCase } from "$lib/utils";
  import Pagination from "$lib/components/Pagination.svelte";
  import { confirmMerge } from "./confirmMerge";
  import type { components } from "$lib/api/schema";

  type Resp = components["schemas"]["IdentifierConflictsResponse"];
  type Pair = components["schemas"]["IdentifierConflictPairOut"];
  type Person = components["schemas"]["IdentifierConflictPersonOut"];

  let {
    onopenPerson,
    onchange,
    reloadKey,
  }: {
    /** Ouvre le drawer d'une personne. */
    onopenPerson: (personId: number) => void;
    /** Notifie le parent après une mutation (rafraîchir le badge de l'onglet). */
    onchange: () => void;
    /** Incrémenté par le parent après une action dans le drawer → recharge la file. */
    reloadKey: number;
  } = $props();

  let page = $state(1);
  let data = $state<Resp | null>(null);
  let loading = $state(false);
  let acting = $state(false);
  let error = $state("");

  async function load() {
    loading = true;
    data = await api<Resp>(`/api/persons/identifier-conflicts?page=${page}&per_page=50`);
    loading = false;
  }

  function handlePage(p: number) {
    page = p;
    load();
    window.scrollTo(0, 0);
  }

  async function merge(targetId: number, sourceId: number) {
    if (!(await confirmMerge(sourceId))) return;
    acting = true;
    error = "";
    try {
      await personsApi.merge(targetId, sourceId);
      await load();
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
      await load();
      onchange();
    } catch {
      error = "Erreur";
    }
    acting = false;
  }

  // Charge au montage et à chaque incrément de `reloadKey` (action dans le drawer).
  $effect(() => {
    void reloadKey;
    untrack(load);
  });
</script>

<p class="intro">
  Paires de personnes portant la <strong>même valeur d'identifiant</strong> (ORCID, IdRef,
  hal_person_id, idHAL). Mêmes nom et réseau (labos, publications) ⇒ <em>doublon</em> à fusionner ;
  personnes manifestement distinctes ⇒ <em>erreur d'attribution</em> de l'identifiant, à laisser
  (marquer distinctes).
</p>

{#if error}<p class="error">{error}</p>{/if}

{#if data && data.pairs.length === 0 && !loading}
  <div class="empty">Aucune paire en conflit d'identifiant.</div>
{:else if data}
  <div class="pairs">
    {#each data.pairs as pair, i (i)}
      {@const shared = pair.shared_identifiers}
      <div class="pair-block">
        <div class="shared-row">
          {#each shared as s (s.id_type + s.id_value)}
            <span class="ident-chip"><span class="it">{s.id_type}</span>{s.id_value}</span>
          {/each}
        </div>
        <div class="pair-body">
          {@render personCol(pair.person_a)}
          <div class="actions">
            <button
              class="act keep"
              disabled={acting}
              title="Garder la personne de gauche, absorber celle de droite"
              onclick={() => merge(pair.person_a.person_id, pair.person_b.person_id)}
              >&larr; Fusionner</button
            >
            <button
              class="act distinct"
              disabled={acting}
              title="Personnes distinctes (identifiant mal attribué)"
              onclick={() => markDistinct(pair.person_a.person_id, pair.person_b.person_id)}
              >Distinctes</button
            >
            <button
              class="act keep"
              disabled={acting}
              title="Garder la personne de droite, absorber celle de gauche"
              onclick={() => merge(pair.person_b.person_id, pair.person_a.person_id)}
              >Fusionner &rarr;</button
            >
          </div>
          {@render personCol(pair.person_b)}
        </div>
      </div>
    {/each}
  </div>

  <Pagination {page} pages={data.pages} onchange={handlePage} />
{/if}

{#snippet personCol(p: Person)}
  <div class="person-col">
    <button class="person-link" onclick={() => onopenPerson(p.person_id)}>
      <span class="person-last">{titleCase(p.last_name)}</span>
      {titleCase(p.first_name)}
    </button>
    {#if p.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
    <div class="meta">{p.pub_count} publication{p.pub_count !== 1 ? "s" : ""}</div>
    {#if p.labs.length}
      <div class="labs">
        {#each p.labs as lab (lab)}<span class="lab-badge">{lab}</span>{/each}
      </div>
    {/if}
  </div>
{/snippet}

<style>
  .intro {
    font-size: 0.85rem;
    color: #555;
    margin: 4px 0 14px;
    max-width: 70ch;
  }
  .pairs {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .pair-block {
    border: 1px solid var(--border, #e0e0e0);
    border-radius: 6px;
    padding: 10px 12px;
  }
  .shared-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 8px;
  }
  .ident-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 0.8rem;
    background: #eef4f5;
    border: 1px solid #cfe0e3;
    border-radius: 4px;
    padding: 1px 7px;
    font-family: "SF Mono", SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
  }
  .ident-chip .it {
    text-transform: uppercase;
    font-size: 0.65rem;
    font-weight: 700;
    color: #15616d;
  }
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
  .person-link {
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    font: inherit;
    color: inherit;
    text-align: left;
  }
  .person-link:hover {
    color: #2563eb;
    text-decoration: underline;
  }
  .person-last {
    font-weight: 600;
  }
  .meta {
    font-size: 0.78rem;
    color: #888;
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
    background: #e8eef4;
    color: var(--accent, #2563eb);
    border-radius: 10px;
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
    border: 1px solid var(--border, #ccc);
    border-radius: 4px;
    background: var(--card, #fff);
    cursor: pointer;
    white-space: nowrap;
    font-family: inherit;
  }
  .act:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .act.keep:hover:not(:disabled) {
    background: var(--success-light, #e6f4ea);
    border-color: var(--success, #34a853);
  }
  .act.distinct:hover:not(:disabled) {
    background: #fff3cd;
    border-color: #d4a017;
  }
  .error {
    color: var(--danger, #c0392b);
    background: var(--danger-light, #fdecea);
    padding: 6px 10px;
    border-radius: 4px;
    margin-bottom: 10px;
  }
  .empty {
    padding: 20px;
    color: #888;
  }
</style>
