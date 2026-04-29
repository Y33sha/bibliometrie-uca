<script lang="ts">
  import { base } from "$app/paths";
  import type { Subject } from "./types";

  let { subjects }: { subjects: Subject[] } = $props();

  /** Ontologies considérées comme "généralistes" (badge gris discret).
   *
   * - openalex_topic level 0 : domain OpenAlex.
   * - hal_domain top-level : tous les codes sans `.` (ex `phys`, `chim`).
   * - wos_heading : grandes catégories WoS (Physical Sciences…). */
  function isGeneral(s: Subject): boolean {
    if (Object.keys(s.ontologies).length === 0) return false;
    const oa = s.ontologies.openalex_topic;
    if (oa && oa.level === 0) return true;
    const hal = s.ontologies.hal_domain;
    if (hal && hal.codes.every((c) => !c.includes("."))) return true;
    if (s.ontologies.wos_heading) return true;
    return false;
  }

  function isFree(s: Subject): boolean {
    return Object.keys(s.ontologies).length === 0;
  }

  const generalConcepts = $derived(subjects.filter(isGeneral));
  const preciseConcepts = $derived(
    subjects.filter((s) => !isGeneral(s) && !isFree(s)),
  );
  const freeKeywords = $derived(subjects.filter(isFree));

  function tooltip(s: Subject): string {
    return `Source : ${s.sources.join(", ")}`;
  }
</script>

{#if subjects.length > 0}
  <div class="section subjects-section">
    <h2 class="section-title">Sujets</h2>

    {#if generalConcepts.length > 0}
      <div class="general">
        {#each generalConcepts as s (s.id)}
          <a href="{base}/subjects/{s.id}" class="chip" title={tooltip(s)}>{s.label}</a>
        {/each}
      </div>
    {/if}

    {#if preciseConcepts.length > 0}
      <div class="badges">
        {#each preciseConcepts as s (s.id)}
          <a href="{base}/subjects/{s.id}" class="badge concept" title={tooltip(s)}>{s.label}</a>
        {/each}
      </div>
    {/if}

    {#if freeKeywords.length > 0}
      <div class="badges">
        {#each freeKeywords as s (s.id)}
          <a href="{base}/subjects/{s.id}" class="badge free" title={tooltip(s)}>{s.label}</a>
        {/each}
      </div>
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
  .general {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 10px;
    padding-bottom: 10px;
    border-bottom: 1px dashed var(--border);
  }
  .chip {
    display: inline-block;
    padding: 2px 8px;
    font-size: 0.8rem;
    color: var(--muted, #6b7280);
    background: var(--bg-muted, #f3f4f6);
    border-radius: 4px;
  }
  .badges {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .badges + .badges {
    margin-top: 8px;
  }
  .badge {
    display: inline-block;
    padding: 3px 10px;
    font-size: 0.85rem;
    border-radius: 12px;
  }
  .badge.concept {
    background: #e0f2fe;
    color: #075985;
    border: 1px solid #bae6fd;
  }
  .badge.free {
    background: #fef3c7;
    color: #92400e;
    border: 1px solid #fde68a;
  }
</style>
