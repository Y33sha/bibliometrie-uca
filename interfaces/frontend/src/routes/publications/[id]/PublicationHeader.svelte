<script lang="ts">
  import { base } from "$app/paths";
  import { sanitizeTitle } from "$lib/utils";
  import { docTypeSingular } from "$lib/labels";
  import type { PubDetail } from "./types";

  const { pub }: { pub: PubDetail } = $props();
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
