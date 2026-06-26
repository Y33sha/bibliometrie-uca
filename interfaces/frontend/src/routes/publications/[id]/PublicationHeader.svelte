<script lang="ts">
  import { base } from "$app/paths";
  import { sanitizeTitle } from "$lib/utils";
  import { docTypeSingular, relationTypeLabel } from "$lib/labels";
  import type { PubDetail, RelatedPublication } from "./types";

  const { pub, parentRelations = [] }: { pub: PubDetail; parentRelations?: RelatedPublication[] } =
    $props();

  // Lien vers l'œuvre principale : interne si elle est au corpus, sinon vers doi.org.
  function parentHref(r: RelatedPublication): string {
    return r.publication_id ? `${base}/publications/${r.publication_id}` : `https://doi.org/${r.doi}`;
  }
</script>

<div class="pub-header">
  <div class="pub-meta">
    {#if pub.doc_type}<span class="doc-type-tag">{docTypeSingular[pub.doc_type] || pub.doc_type}</span>{/if}
    {#if pub.pub_year}<span class="pub-year">{pub.pub_year}</span>{/if}
  </div>
  <h1 class="pub-title-main">{@html sanitizeTitle(pub.title)}</h1>

  {#if pub.journal_title || pub.container_title}
    <div class="pub-journal-line">
      {#if pub.journal_id}
        <a href="{base}/journals/{pub.journal_id}" class="journal-name">{pub.journal_title || pub.container_title}</a>
      {:else}
        <span class="journal-name" class:container={!pub.journal_title}>{pub.journal_title || pub.container_title}</span>
      {/if}
      {#if pub.publisher_name}
        <span class="publisher-sep">—</span>
        {#if pub.publisher_id}
          <a href="{base}/publishers/{pub.publisher_id}" class="publisher-name">{pub.publisher_name}</a>
        {:else}
          <span class="publisher-name">{pub.publisher_name}</span>
        {/if}
      {/if}
    </div>
  {/if}

  {#if parentRelations.length}
    <div class="parent-relations">
      {#each parentRelations as r (r.relation_type + (r.publication_id ?? r.doi))}
        <a
          class="parent-rel"
          href={parentHref(r)}
          target={r.publication_id ? undefined : "_blank"}
          rel={r.publication_id ? undefined : "noopener"}
        >
          <svg class="parent-rel-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M9 17H7A5 5 0 0 1 7 7h2M15 7h2a5 5 0 0 1 0 10h-2M8 12h8" />
          </svg>
          <span class="parent-rel-kind">{relationTypeLabel[r.relation_type] ?? r.relation_type}</span>
          <span class="parent-rel-title">{@html sanitizeTitle(r.title ?? r.doi ?? "")}</span>
        </a>
      {/each}
    </div>
  {/if}

</div>

<style>
  .pub-header {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 20px 24px;
    margin-bottom: 16px;
  }
  .pub-title-main {
    font-size: 1.3rem;
    font-weight: 600;
    margin: 0 0 10px;
    line-height: 1.4;
  }
  .pub-meta {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
    margin-bottom: 10px;
    font-size: 1rem;
    color: var(--muted);
  }
  .pub-year {
    font-weight: 600;
  }
  .doc-type-tag {
    background: #15616d;
    color: #fff;
    padding: 3px 9px;
    border-radius: 3px;
    font-size: 0.92rem;
    font-weight: 500;
  }

  /* Bandeau « cette publi est une pièce rattachée à une œuvre principale » : volontairement
     voyant (fond teinté + filet d'accent épais) pour qu'on le saisisse au premier coup d'œil. */
  .parent-relations {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin: 0 0 12px;
  }
  .parent-rel {
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding: 10px 14px;
    background: #eef4f5;
    border-left: 4px solid #15616d;
    border-radius: 4px;
    text-decoration: none;
  }
  .parent-rel:hover {
    background: #e1edef;
  }
  .parent-rel-icon {
    width: 16px;
    height: 16px;
    color: #15616d;
    flex: none;
    align-self: center;
  }
  .parent-rel-kind {
    text-transform: uppercase;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    color: #15616d;
    white-space: nowrap;
  }
  .parent-rel-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--text);
    min-width: 0;
  }
  .parent-rel:hover .parent-rel-title {
    text-decoration: underline;
  }

  .pub-journal-line {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
    font-size: 0.95rem;
    margin-bottom: 8px;
  }
  .journal-name {
    font-weight: 500;
    color: var(--text);
    text-decoration: none;
  }
  .journal-name.container {
    color: var(--muted);
    font-weight: 400;
  }
  a.journal-name:hover {
    text-decoration: underline;
  }
  .publisher-name {
    font-size: 0.85rem;
    color: var(--muted);
    text-decoration: none;
  }
  a.publisher-name:hover {
    text-decoration: underline;
  }
  .publisher-sep {
    font-size: 0.85rem;
    color: var(--muted);
  }
</style>
