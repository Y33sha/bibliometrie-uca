<script lang="ts">
  import { base } from "$app/paths";
  import SectionLabel from "./SectionLabel.svelte";
  import type { Subject } from "./types";

  let { subjects }: { subjects: Subject[] } = $props();

  function isFree(s: Subject): boolean {
    return Object.keys(s.ontologies).length === 0;
  }

  const concepts = $derived(subjects.filter((s) => !isFree(s)));
  const freeKeywords = $derived(subjects.filter(isFree));

  function tooltip(s: Subject): string {
    return `Source : ${s.sources.join(", ")}`;
  }
</script>

{#if subjects.length > 0}
  <div class="detail-section">
    <SectionLabel icon="tag" text="Sujets" />
    {#if concepts.length > 0}
      <div class="detail-tags">
        {#each concepts as s (s.id)}
          <a href="{base}/subjects/{s.id}" title={tooltip(s)}>{s.label}</a>
        {/each}
      </div>
    {/if}
    {#if freeKeywords.length > 0}
      <div class="detail-sublabel">Mots-clés libres</div>
      <div class="detail-tags">
        {#each freeKeywords as s (s.id)}
          <a href="{base}/subjects/{s.id}" title={tooltip(s)}>{s.label}</a>
        {/each}
      </div>
    {/if}
  </div>
{/if}
