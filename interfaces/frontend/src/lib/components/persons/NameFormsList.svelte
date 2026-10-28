<script lang="ts">
  import StatusToggles from "#lib/components/StatusToggles.svelte";
  import RejectedFold from "./RejectedFold.svelte";
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

  // Une forme dérivée du nom canonique (source 'persons') est confirmée d'office et le recompute la rétablirait : pas d'action de statut dessus.
  function isCanonical(nf: NameForm): boolean {
    return nf.sources?.includes("persons") ?? false;
  }
</script>

{#snippet formRow(nf: NameForm)}
  <div class="chip-row">
    <span class="chip-controls">
      {#if isCanonical(nf)}
        <span class="canonical-tag" title="Forme dérivée du nom canonique">nom</span>
      {:else}
        <StatusToggles status={nf.status} onchange={(s) => onsetStatus(personId, nf.name_form, s)} />
      {/if}
    </span>
    {#if nf.publication_count > 0}
      <button
        class="status-chip"
        class:confirmed={nf.status === "confirmed"}
        class:rejected={nf.status === "rejected"}
        title="Voir les {nf.publication_count} publication(s) liée(s)"
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
    <span class="publication-count" class:zero={nf.publication_count === 0}>
      {nf.publication_count.toLocaleString("fr-FR")} publication{nf.publication_count > 1 ? "s" : ""}
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
  <RejectedFold {personId} label="les formes rejetées">
    <div class="forms-list">
      {#each rejectedForms as nf}
        {@render formRow(nf)}
      {/each}
    </div>
  </RejectedFold>
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
  .publication-count {
    font-size: 0.72rem;
    color: var(--muted);
    white-space: nowrap;
  }
  .publication-count.zero {
    color: var(--text-faint);
  }
  .shared {
    font-size: 0.72rem;
    color: var(--warning-text);
    white-space: nowrap;
  }
  .empty {
    font-size: 0.8rem;
    color: var(--warning-text);
    background: var(--warning-light);
    padding: 1px 7px;
    border-radius: var(--radius-pill);
  }
</style>
