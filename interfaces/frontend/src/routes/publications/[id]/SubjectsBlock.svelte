<script lang="ts">
  import { base } from "$app/paths";
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
  <div class="section subjects-section">
    <h2 class="section-title">Sujets</h2>

    {#if concepts.length > 0}
      <ul class="tags-list">
        {#each concepts as s (s.id)}
          <li>
            <a href="{base}/subjects/{s.id}" title={tooltip(s)}>{s.label}</a>
          </li>
        {/each}
      </ul>
    {/if}

    {#if freeKeywords.length > 0}
      <h3 class="subsection-title">Mots-clés libres</h3>
      <ul class="tags-list">
        {#each freeKeywords as s (s.id)}
          <li>
            <a href="{base}/subjects/{s.id}" title={tooltip(s)}>{s.label}</a>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}

<style>
  .subjects-section {
    background: white;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px 20px;
    margin-bottom: 16px;
  }
  .section-title {
    font-size: 1.05rem;
    font-weight: 600;
    margin: 0 0 10px;
  }
  .subsection-title {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.3px;
    margin: 14px 0 8px;
  }
  .tags-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .tags-list li {
    display: inline-flex;
    align-items: center;
    background: #f5f4f1;
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 0.9rem;
  }
  .tags-list a {
    color: var(--accent);
    text-decoration: none;
  }
  .tags-list a:hover {
    text-decoration: underline;
  }
</style>
