<script lang="ts">
  import { untrack } from "svelte";
  import { base } from "$app/paths";
  import { ApiError, api, persons as personsApi } from "$lib/api";
  import { titleCase } from "$lib/utils";
  import Pagination from "$lib/components/Pagination.svelte";
  import type { components } from "$lib/api/schema";

  type Resp = components["schemas"]["DetachableIntrudersResponse"];
  type Group = components["schemas"]["DetachableIntruderGroupOut"];

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
    data = await api<Resp>(`/api/persons/detachable-intruders?page=${page}&per_page=50`);
    loading = false;
  }

  function handlePage(p: number) {
    page = p;
    load();
    window.scrollTo(0, 0);
  }

  // Détacher l'intrus = rejeter sa forme de nom pour cette personne (verrou de non-retour
  // + détachement effectif des signatures).
  async function detach(personId: number, nameForm: string) {
    acting = true;
    error = "";
    try {
      await personsApi.updateNameFormStatus(personId, nameForm, "rejected");
      await load();
      onchange();
    } catch (e) {
      error = e instanceof ApiError ? `Erreur ${e.status}` : "Erreur de détachement";
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
  Une même personne rattachée à <strong>≥2 signatures d'une même publication</strong> : impossible,
  donc l'une est mal rattachée. L'occurrence dont le nom est compatible avec une forme
  <em>confirmée</em> est l'<strong>ancre</strong> ; l'occurrence incompatible est l'<strong
    >intrus</strong
  >, accroché par erreur (souvent via un identifiant partagé). Détacher l'intrus rejette sa forme de
  nom. Vérifier qu'il ne s'agit pas d'un nom marié non confirmé avant de détacher.
</p>

{#if error}<p class="error">{error}</p>{/if}

{#if data && data.groups.length === 0 && !loading}
  <div class="empty">Aucun intrus détachable.</div>
{:else if data}
  <div class="groups">
    {#each data.groups as g, i (i)}
      {@render groupBlock(g)}
    {/each}
  </div>

  <Pagination {page} pages={data.pages} onchange={handlePage} />
{/if}

{#snippet groupBlock(g: Group)}
  <div class="group-block">
    <div class="pub-row">
      {#if g.publication_id}
        <a href="{base}/publications/{g.publication_id}" class="pub-link">{g.pub_title}</a>
      {:else}
        <span class="pub-title">{g.pub_title}</span>
      {/if}
      {#if g.pub_year}<span class="pub-year">{g.pub_year}</span>{/if}
    </div>

    <div class="person-row">
      <button class="person-link" onclick={() => onopenPerson(g.person.person_id)}>
        <span class="person-last">{titleCase(g.person.last_name)}</span>
        {titleCase(g.person.first_name)}
      </button>
      {#if g.person.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
      <span class="meta">{g.person.pub_count} publication{g.person.pub_count !== 1 ? "s" : ""}</span>
      {#each g.person.labs as lab (lab)}<span class="lab-badge">{lab}</span>{/each}
    </div>

    <div class="evidence">
      <div class="anchor-col">
        <div class="col-label">Signe légitimement</div>
        {#each g.anchors as a, ai (ai)}
          <div class="occ"><span class="occ-src">{a.source}</span>{a.raw_author_name}</div>
        {/each}
      </div>
      <div class="intruder-col">
        <div class="col-label">Intrus</div>
        {#each g.intruders as intruder, ii (ii)}
          <div class="intruder">
            <div class="occ"><span class="occ-src">{intruder.source}</span>{intruder.raw_author_name}</div>
            {#if intruder.identifiers.length}
              <div class="ident-row">
                {#each intruder.identifiers as s (s.id_type + s.id_value)}
                  <span class="ident-chip"><span class="it">{s.id_type}</span>{s.id_value}</span>
                {/each}
              </div>
            {/if}
            <button
              class="act detach"
              disabled={acting}
              title="Rejeter la forme « {intruder.name_form} » et détacher les signatures"
              onclick={() => detach(g.person.person_id, intruder.name_form)}
            >
              Détacher
            </button>
          </div>
        {/each}
      </div>
    </div>
  </div>
{/snippet}

<style>
  .intro {
    font-size: 0.85rem;
    color: #555;
    margin: 4px 0 14px;
    max-width: 80ch;
  }
  .groups {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .group-block {
    border: 1px solid var(--border, #e0e0e0);
    border-radius: 6px;
    padding: 10px 12px;
  }
  .pub-row {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 6px;
  }
  .pub-link,
  .pub-title {
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--accent, #2563eb);
    text-decoration: none;
  }
  .pub-link:hover {
    text-decoration: underline;
  }
  .pub-year {
    font-size: 0.78rem;
    color: #888;
  }
  .person-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    margin-bottom: 8px;
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
  }
  .lab-badge {
    font-size: 0.72rem;
    background: #e8eef4;
    color: var(--accent, #2563eb);
    border-radius: 10px;
    padding: 1px 7px;
  }
  .evidence {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  @media (max-width: 700px) {
    .evidence {
      grid-template-columns: 1fr;
    }
  }
  .col-label {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    color: #999;
    margin-bottom: 4px;
  }
  .occ {
    font-size: 0.85rem;
    display: flex;
    align-items: baseline;
    gap: 6px;
  }
  .occ-src {
    text-transform: uppercase;
    font-size: 0.62rem;
    font-weight: 700;
    color: #15616d;
  }
  .intruder {
    background: #fff3cd;
    border: 1px solid #f0d98a;
    border-radius: 4px;
    padding: 6px 8px;
    margin-bottom: 6px;
  }
  .ident-row {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    margin: 4px 0;
  }
  .ident-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 0.78rem;
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
  .act.detach:hover:not(:disabled) {
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
