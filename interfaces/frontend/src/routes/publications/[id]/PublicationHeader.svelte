<script lang="ts">
  import { base } from "$app/paths";
  import { sanitizeTitle } from "$lib/utils";
  import { docTypeSingular } from "$lib/labels";
  import { sourceExternalUrl, sourceIcon, sourceLabel, SOURCE_ORDER } from "$lib/sources";
  import type { PubDetail, Source } from "./types";

  // `sources` peut contenir plusieurs rows pour une même source (ex: deux
  // Work IDs OpenAlex partageant un DOI). On affiche un lien par row. La
  // 1ère collection HAL listée correspond à la `source_publications` la
  // plus récente (l'API trie par `created_at DESC`).
  const {
    pub,
    sources,
  }: {
    pub: PubDetail;
    sources: Source[];
  } = $props();

  // Liens sources regroupés par type (ordre stable), une entrée par row.
  const orderedSources = $derived([
    ...SOURCE_ORDER.flatMap((src) => sources.filter((s) => s.source === src)),
    ...sources.filter((s) => !SOURCE_ORDER.includes(s.source)),
  ]);
  // Collections HAL : celles de la `source_publications` HAL la plus récente
  // (la 1ère grâce au tri DESC côté API).
  const halCollections = $derived(sources.find((s) => s.source === "hal")?.hal_collections ?? []);

  const langLabels: Record<string, string> = {
    en: "anglais",
    fr: "français",
    de: "allemand",
    es: "espagnol",
    it: "italien",
    pt: "portugais",
  };
</script>

<div class="pub-header">
  <h1 class="pub-title-main">{@html sanitizeTitle(pub.title)}</h1>
  <div class="pub-meta">
    {#if pub.pub_year}<span class="meta-badge">{pub.pub_year}</span>{/if}
    {#if pub.doc_type}
      <span class="meta-badge type-badge">{docTypeSingular[pub.doc_type] || pub.doc_type}</span>
    {/if}
    {#if pub.oa_status && pub.oa_status !== "unknown"}
      <span class="oa-tag oa-{pub.oa_status}">{pub.oa_status}</span>
    {/if}
    {#if pub.language}
      <span class="meta-badge lang-badge">{langLabels[pub.language] || pub.language}</span>
    {/if}
  </div>

  {#if pub.journal_title || pub.container_title}
    <div class="pub-journal-line">
      {#if pub.journal_id}
        <a href="{base}/journals/{pub.journal_id}" class="journal-name">{pub.journal_title || pub.container_title}</a>
      {:else}
        <span class="journal-name">{pub.journal_title || pub.container_title}</span>
      {/if}
      {#if pub.issn}
        <span class="issn">ISSN {pub.issn}</span>
      {/if}
      {#if pub.publisher_name}
        <span class="publisher-sep">—</span>
        {#if pub.publisher_id}
          <a href="{base}/publishers/{pub.publisher_id}" class="publisher-name">{pub.publisher_name}</a>
        {:else}
          <span class="publisher-name">{pub.publisher_name}</span>
        {/if}
      {/if}
      {#if pub.journal_predatory}
        <span class="predatory-badge">Revue prédatrice</span>
      {/if}
      {#if pub.publisher_predatory && !pub.journal_predatory}
        <span class="predatory-badge">Éditeur prédateur</span>
      {/if}
      {#if pub.oa_model}
        <span class="meta-badge">{pub.oa_model}</span>
      {/if}
    </div>
  {/if}

  {#if pub.doi}
    <div class="pub-doi">
      <span class="doi-label">DOI</span>
      <a href="https://doi.org/{pub.doi}" target="_blank" rel="noopener">{pub.doi}</a>
    </div>
  {/if}

  <div class="pub-sources">
    {#each orderedSources as s}
      <a
        href={sourceExternalUrl(s.source, s.source_id, pub.oa_status)}
        target="_blank"
        rel="noopener"
        class="source-link source-{s.source}-link"
      >
        {#if sourceIcon(s.source)}<img src={sourceIcon(s.source)} alt="" class="source-ico" />{/if}
        {sourceLabel(s.source)} : {s.source_id}
      </a>
    {/each}
  </div>

  {#if halCollections.length > 0}
    <div class="collections-line">
      <span class="collections-label">Collections HAL :</span>
      {#each halCollections as col}
        <span class="collection-tag">{col}</span>
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
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
    margin-bottom: 10px;
  }
  .lang-badge {
    background: #f5f0fa;
    color: #7c5ca7;
  }
  .oa-tag {
    font-size: 0.8rem;
    padding: 2px 8px;
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
  a.journal-name:hover {
    text-decoration: underline;
  }
  .issn {
    font-size: 0.85rem;
    color: var(--muted);
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
  .predatory-badge {
    display: inline-block;
    padding: 2px 8px;
    background: var(--danger-light);
    border-radius: 3px;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--danger);
  }

  .pub-doi {
    display: flex;
    gap: 6px;
    align-items: center;
    font-size: 0.95rem;
    margin-bottom: 8px;
  }
  .doi-label {
    font-weight: 500;
    color: var(--muted);
    font-size: 0.85rem;
  }
  .pub-doi a {
    color: var(--accent);
    text-decoration: none;
  }
  .pub-doi a:hover {
    text-decoration: underline;
  }

  .pub-sources {
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
    margin-bottom: 6px;
  }
  .source-link {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 0.85rem;
    text-decoration: none;
    font-weight: 500;
  }
  .source-hal-link {
    background: var(--accent-light);
    color: var(--accent);
  }
  .source-hal-link:hover {
    background: #d0e3f4;
  }
  .source-openalex-link {
    background: #fef3e0;
    color: var(--bronze);
  }
  .source-openalex-link:hover {
    background: #fde8c8;
  }
  .source-scanr-link {
    background: #e0edf5;
    color: #1b4f72;
  }
  .source-scanr-link:hover {
    background: #cde0ef;
  }
  .source-wos-link {
    background: #f0e8f5;
    color: #6b4c8a;
  }
  .source-wos-link:hover {
    background: #e4d8f0;
  }
  .source-theses-link {
    background: #e8f5e9;
    color: var(--success);
  }
  .source-theses-link:hover {
    background: #d0ebd3;
  }
  .source-crossref-link {
    background: #e3f2f4;
    color: #1a7a8c;
  }
  .source-crossref-link:hover {
    background: #d2eaed;
  }
  .source-datacite-link {
    background: #e3f4ef;
    color: #0f766e;
  }
  .source-datacite-link:hover {
    background: #d2ebe3;
  }
  .source-ico {
    width: 14px;
    height: 14px;
  }

  .collections-line {
    display: flex;
    gap: 6px;
    align-items: center;
    flex-wrap: wrap;
    font-size: 0.85rem;
    margin-top: 6px;
  }
  .collections-label {
    color: var(--muted);
    font-weight: 500;
  }
  .collection-tag {
    display: inline-block;
    padding: 1px 6px;
    background: var(--border-subtle);
    border-radius: 3px;
    font-size: 0.8rem;
    color: var(--muted);
  }
</style>
