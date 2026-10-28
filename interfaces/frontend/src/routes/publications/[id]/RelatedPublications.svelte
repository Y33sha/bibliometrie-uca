<script lang="ts">
  import { resolve } from "$app/paths";
  import SectionLabel from "./SectionLabel.svelte";
  import { docTypeLabel, relationTypeLabel } from "#lib/labels.js";
  import PublicationTitle from "#lib/components/PublicationTitle.svelte";
  import type { RelatedPublication } from "./types";

  let { relations }: { relations: RelatedPublication[] } = $props();

  // Regroupe par type de relation, dans l'ordre d'apparition (déjà trié côté API).
  const groups = $derived.by(() => {
    const map = new Map<string, RelatedPublication[]>();
    for (const r of relations) {
      const list = map.get(r.relation_type) ?? [];
      list.push(r);
      map.set(r.relation_type, list);
    }
    return [...map.entries()];
  });

  function label(rt: string): string {
    return relationTypeLabel[rt] ?? rt;
  }
</script>

{#if relations.length > 0}
  <div class="detail-section">
    <SectionLabel icon="document" text="Publications liées" />
    {#each groups as [rtype, items] (rtype)}
      <div class="relation-group">
        <div class="detail-sublabel">{label(rtype)}</div>
        <ul class="relations-list">
          {#each items as r (r.relation_type + (r.publication_id ?? r.doi))}
            <li>
              {#if r.publication_id}
                <a href={resolve(`publications/${r.publication_id}`)}><PublicationTitle titre={r.title ?? r.doi} /></a>
                <span class="meta">
                  {#if r.publication_year}{r.publication_year}{/if}{#if r.publication_year && r.doc_type} · {/if}{#if r.doc_type}{docTypeLabel(r.doc_type)}{/if}
                </span>
              {:else}
                <a href="https://doi.org/{r.doi}" target="_blank" rel="noopener">{r.doi}</a>
                <span class="meta">hors corpus</span>
              {/if}
            </li>
          {/each}
        </ul>
      </div>
    {/each}
  </div>
{/if}

<style>
  .relation-group {
    margin-bottom: 10px;
  }
  .relation-group:last-child {
    margin-bottom: 0;
  }
  .relations-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .meta {
    color: var(--muted);
    font-size: var(--fs-sm);
    margin-left: 6px;
  }
</style>
