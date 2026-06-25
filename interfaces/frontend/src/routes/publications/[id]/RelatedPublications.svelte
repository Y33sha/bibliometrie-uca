<script lang="ts">
  import { base } from "$app/paths";
  import SectionLabel from "./SectionLabel.svelte";
  import { docTypeSingular, relationTypeLabel } from "$lib/labels";
  import { sanitizeTitle } from "$lib/utils";
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
  function docTypeLabel(dt: string | null | undefined): string {
    return dt ? (docTypeSingular[dt] ?? dt) : "";
  }
</script>

{#if relations.length > 0}
  <div class="detail-section">
    <SectionLabel icon="document" text="Publications liées" />
    {#each groups as [rtype, items] (rtype)}
      <div class="relation-group">
        <div class="detail-sublabel">{label(rtype)}</div>
        <ul class="relations-list">
          {#each items as r (r.relation_type + r.doi)}
            <li>
              {#if r.publication_id}
                <a href="{base}/publications/{r.publication_id}">{@html sanitizeTitle(r.title ?? r.doi)}</a>
                <span class="meta">
                  {#if r.pub_year}{r.pub_year}{/if}{#if r.pub_year && r.doc_type} · {/if}{docTypeLabel(r.doc_type)}
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
  .relations-list a {
    color: var(--accent);
    text-decoration: none;
  }
  .relations-list a:hover {
    text-decoration: underline;
  }
  .meta {
    color: var(--muted);
    font-size: 0.85rem;
    margin-left: 6px;
  }
</style>
