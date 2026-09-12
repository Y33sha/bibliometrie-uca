<script lang="ts">
  import { base } from "$app/paths";
  import SectionLabel from "./SectionLabel.svelte";
  import type { Subject } from "./types";

  let { subjects, keywords }: { subjects: Subject[]; keywords: string[] } = $props();

  function tooltip(s: Subject): string {
    return `Source : ${s.sources.join(", ")}`;
  }
</script>

{#if subjects.length > 0 || keywords.length > 0}
  <div class="detail-section">
    <SectionLabel icon="tag" text="Sujets" />
    {#if subjects.length > 0}
      <div class="detail-tags">
        {#each subjects as s (s.id)}
          <a href="{base}/subjects/{s.id}" title={tooltip(s)}>{s.label}</a>
        {/each}
      </div>
    {/if}
    {#if keywords.length > 0}
      <div class="detail-sublabel">Mots-clés libres</div>
      <div class="detail-tags">
        {#each keywords as kw (kw)}
          <span class="detail-tag free-keyword">{kw}</span>
        {/each}
      </div>
    {/if}
  </div>
{/if}

<style>
  /* Mot-clé libre : même pastille que les sujets, en contour et sans lien, car hors du référentiel des sujets. Le padding compense la bordure pour garder la même hauteur. */
  .detail-tags .free-keyword {
    padding: 2px 9px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--muted);
  }
</style>
