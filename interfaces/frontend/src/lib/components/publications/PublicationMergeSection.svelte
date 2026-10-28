<script lang="ts">
  import { untrack } from "svelte";
  import { resolve } from "$app/paths";
  import { errorMessage, publications as publicationsApi } from "#lib/api/index.js";
  import type { MergeCandidate } from "#lib/api/publications.js";
  import PublicationTitle from "#lib/components/PublicationTitle.svelte";
  import SourceTag from "#lib/components/SourceTag.svelte";
  import { useDebouncedSearch } from "#lib/composables/useDebouncedSearch.svelte.js";
  import { confirmDialog, toast } from "#lib/dialogs.svelte.js";

  // `onmerged` reçoit la publication conservée, qui peut être l'autre publication.
  let {
    publicationId,
    onmerged,
  }: { publicationId: number; onmerged: (publicationId: number) => void } = $props();

  let similar = $state<MergeCandidate[] | null>(null);
  let merging = $state(false);

  const search = useDebouncedSearch<MergeCandidate>({
    search: (q, request) => publicationsApi.mergeCandidates(publicationId, q, request),
    minLength: 1,
  });

  // Chaque publication ouverte repart de ses titres proches, sans recherche.
  $effect(() => {
    const id = publicationId;
    similar = null;
    untrack(() => search.clear());
    publicationsApi
      .mergeCandidates(id)
      .then((candidates) => {
        if (id === publicationId) similar = candidates;
      })
      .catch(() => {
        if (id === publicationId) similar = [];
      });
  });

  const searching = $derived(search.query.trim().length > 0);
  const candidates = $derived(searching ? search.results : (similar ?? []));

  function conflictText(conflicts: number): string {
    if (conflicts === 1)
      return "1 contribution désigne deux personnes différentes : elle restera sans personne jusqu'au prochain passage du pipeline.";
    return `${conflicts} contributions désignent chacune deux personnes différentes : elles resteront sans personne jusqu'au prochain passage du pipeline.`;
  }

  async function mergeWith(candidate: MergeCandidate) {
    if (merging) return;
    merging = true;
    try {
      const preview = await publicationsApi.mergePreview(publicationId, candidate.publication_id);
      const kept =
        preview.publication_id === publicationId
          ? "Cette publication est conservée."
          : `La publication n° ${preview.publication_id} est conservée.`;
      // Une ligne par information ; la modale rend les sauts de ligne.
      const lines = [
        `Fusionner avec la publication n° ${candidate.publication_id} (« ${candidate.title} ») ?`,
        kept,
        ...(preview.conflicts > 0 ? [conflictText(preview.conflicts)] : []),
      ];
      const confirmed = await confirmDialog({
        title: "Fusionner les publications",
        message: lines.join("\n\n"),
        confirmLabel: "Fusionner",
        danger: preview.conflicts > 0,
      });
      if (!confirmed) return;
      const result = await publicationsApi.merge(publicationId, candidate.publication_id);
      toast("Publications fusionnées", "success");
      onmerged(result.publication_id);
    } catch (e) {
      toast(`Fusion impossible : ${errorMessage(e)}`, "error");
    } finally {
      merging = false;
    }
  }
</script>

<section class="merge">
  <h3>Fusion</h3>
  <input
    type="search"
    class="merge-search"
    placeholder="Identifiant, DOI ou mots du titre"
    aria-label="Chercher une publication à fusionner"
    value={search.query}
    oninput={(e) => search.setQuery((e.target as HTMLInputElement).value)}
  />
  {#if !searching && similar === null}
    <p class="hint">Chargement…</p>
  {:else if searching && search.loading}
    <p class="hint">Recherche…</p>
  {:else if candidates.length === 0}
    <p class="hint">{searching ? "Aucune publication fusionnable" : "Aucun titre proche"}</p>
  {:else}
    {#if !searching}<p class="hint">Titres proches</p>{/if}
    <ul class="candidates">
      {#each candidates as c (c.publication_id)}
        <li>
          <button class="btn-merge" disabled={merging} onclick={() => mergeWith(c)}>Fusionner</button>
          <span class="candidate">
            <a href={resolve(`publications/${c.publication_id}`)} target="_blank" rel="noopener"
              ><PublicationTitle titre={c.title} /></a
            >
            <span class="meta">
              n°&nbsp;{c.publication_id}{#if c.publication_year} · {c.publication_year}{/if}
              {#if c.doi} · {c.doi}{/if}
            </span>
            {#each c.sources as source (source)}<SourceTag {source} />{/each}
          </span>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .merge {
    margin-top: 22px;
    max-width: 900px;
  }
  .merge h3 {
    font-size: var(--fs-sm);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
    margin: 0 0 8px;
  }
  .merge-search {
    width: 100%;
    max-width: 420px;
  }
  .hint {
    color: var(--muted);
    font-size: var(--fs-sm);
    margin: 8px 0 4px;
  }
  .candidates {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: var(--fs-sm);
  }
  .candidates li {
    display: flex;
    gap: 10px;
    align-items: baseline;
  }
  .candidate a {
    color: inherit;
  }
  .meta {
    color: var(--muted);
    margin: 0 6px;
  }
</style>
