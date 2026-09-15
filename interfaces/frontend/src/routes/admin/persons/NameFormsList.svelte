<script lang="ts">
  import type { NameForm } from "./types";

  let {
    personId,
    nameForms,
    onopenDetail,
    onsetStatus,
  }: {
    personId: number;
    nameForms: NameForm[];
    /** Ouvre la vue détaillée (publications liées, détachement, fusion). */
    onopenDetail: (personId: number, nameForm: string) => void | Promise<void>;
    onsetStatus: (
      personId: number,
      nameForm: string,
      status: string,
    ) => void | Promise<void>;
  } = $props();

  const activeForms = $derived(nameForms.filter((nf) => nf.status !== "rejected"));
  const rejectedForms = $derived(nameForms.filter((nf) => nf.status === "rejected"));

  let showRejected = $state(false);

  // Les formes rejetées se replient à chaque changement de personne.
  $effect(() => {
    void personId;
    showRejected = false;
  });

  // Une forme dérivée du nom canonique (source 'persons') est confirmée d'office et le recompute la rétablirait : pas d'action de statut dessus.
  function isCanonical(nf: NameForm): boolean {
    return nf.sources?.includes("persons") ?? false;
  }
</script>

{#snippet formRow(nf: NameForm)}
  <div class="chip-row">
    <span class="chip-controls">
      {#if isCanonical(nf)}
        <span class="canonical" title="Forme dérivée du nom canonique">nom</span>
      {:else}
        <button
          class="toggle-btn confirm"
          class:active={nf.status === "confirmed"}
          title={nf.status === "confirmed" ? "Retirer la confirmation" : "Confirmer"}
          onclick={() =>
            onsetStatus(
              personId,
              nf.name_form,
              nf.status === "confirmed" ? "pending" : "confirmed",
            )}>&#x2713;</button
        >
        <button
          class="toggle-btn reject"
          class:active={nf.status === "rejected"}
          title={nf.status === "rejected" ? "Retirer le rejet" : "Rejeter"}
          onclick={() =>
            onsetStatus(
              personId,
              nf.name_form,
              nf.status === "rejected" ? "pending" : "rejected",
            )}>&#x2717;</button
        >
      {/if}
    </span>
    {#if nf.pub_count > 0}
      <button
        class="status-chip"
        class:confirmed={nf.status === "confirmed"}
        class:rejected={nf.status === "rejected"}
        title="Voir les {nf.pub_count} publication(s) liée(s)"
        onclick={() => onopenDetail(personId, nf.name_form)}
      >
        {nf.name_form}
      </button>
    {:else}
      <span
        class="status-chip"
        class:confirmed={nf.status === "confirmed"}
        class:rejected={nf.status === "rejected"}
      >
        {nf.name_form}
      </span>
    {/if}
    <span class="pub-count" class:zero={nf.pub_count === 0}>
      {nf.pub_count} pub.
    </span>
    {#if nf.shared_count > 0}
      <span
        class="shared"
        title="Aussi portée par {nf.shared_count} autre(s) personne(s)"
      >
        &#9094; {nf.shared_count}
      </span>
    {/if}
  </div>
{/snippet}

{#if activeForms.length}
  <div class="forms-list">
    {#each activeForms as nf}
      {@render formRow(nf)}
    {/each}
  </div>
{:else}
  <span class="empty">aucune</span>
{/if}

{#if rejectedForms.length}
  <details class="rejected-forms" bind:open={showRejected}>
    <summary>
      {showRejected ? "masquer les formes rejetées ▲" : "afficher les formes rejetées ▼"}
    </summary>
    <div class="forms-list">
      {#each rejectedForms as nf}
        {@render formRow(nf)}
      {/each}
    </div>
  </details>
{/if}

<style>
  .forms-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
    align-items: flex-start;
  }
  .chip-row {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .pub-count {
    font-size: 0.72rem;
    color: #666;
    white-space: nowrap;
  }
  .pub-count.zero {
    color: #bbb;
  }
  .shared {
    font-size: 0.72rem;
    color: #8a6d3b;
    white-space: nowrap;
  }
  .canonical {
    font-size: 0.68rem;
    color: #888;
    background: #f0f0f0;
    border-radius: 8px;
    padding: 0 6px;
  }
  .empty {
    font-size: 0.8rem;
    color: #8a6d10;
    background: var(--warning-light, #fff3e0);
    padding: 1px 7px;
    border-radius: 10px;
  }
  .rejected-forms {
    margin-top: 8px;
  }
  .rejected-forms summary {
    /* Retire le triangle natif : la flèche fait partie du libellé. */
    list-style: none;
    cursor: pointer;
    font-size: 0.75rem;
    color: #888;
  }
  .rejected-forms summary::-webkit-details-marker {
    display: none;
  }
  .rejected-forms summary:hover {
    color: var(--accent, #1976d2);
  }
  .rejected-forms[open] summary {
    margin-bottom: 4px;
  }
</style>
