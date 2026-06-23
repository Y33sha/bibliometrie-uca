<script lang="ts">
  import type { Person, NameForm } from "./types";

  let {
    person,
    onopenDetail,
    onsetStatus,
  }: {
    person: Person;
    /** Ouvre la vue détaillée (publications liées, détachement, fusion). */
    onopenDetail: (personId: number, nameForm: string) => void | Promise<void>;
    onsetStatus: (
      personId: number,
      nameForm: string,
      status: string,
    ) => void | Promise<void>;
  } = $props();

  // Une forme dérivée du nom canonique (source 'persons') est confirmée d'office
  // et le recompute la rétablirait : pas d'action de statut dessus.
  function isCanonical(nf: NameForm): boolean {
    return nf.sources?.includes("persons") ?? false;
  }
</script>

{#if person.name_forms?.length}
  <div class="forms-list">
    {#each person.name_forms as nf}
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
                  person.id,
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
                  person.id,
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
            onclick={() => onopenDetail(person.id, nf.name_form)}
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
        {#if nf.shared_count > 1}
          <span
            class="shared"
            title="Aussi portée par {nf.shared_count - 1} autre(s) personne(s)"
          >
            &#9094; {nf.shared_count - 1}
          </span>
        {/if}
      </div>
    {/each}
  </div>
{:else}
  <span class="empty">aucune</span>
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
</style>
