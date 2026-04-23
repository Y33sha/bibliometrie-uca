<script lang="ts">
  import { base } from "$app/paths";
  import { sanitizeTitle, halDocUrl, scanrPubUrl } from "$lib/utils";
  import { typeLabels as baseTypeLabels } from "$lib/labels";
  import type { PubDetail, Source } from "./types";

  const {
    pub,
    halSource,
    oaSource,
    scanrSource,
    wosSource,
    thesesSource,
  }: {
    pub: PubDetail;
    halSource: Source | undefined;
    oaSource: Source | undefined;
    scanrSource: Source | undefined;
    wosSource: Source | undefined;
    thesesSource: Source | undefined;
  } = $props();

  const typeLabels: Record<string, string> = {
    ...baseTypeLabels,
    conference_paper: "Communication",
  };

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
      <span class="meta-badge type-badge">{typeLabels[pub.doc_type] || pub.doc_type}</span>
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
      <span class="journal-name">{pub.journal_title || pub.container_title}</span>
      {#if pub.issn}
        <span class="issn">ISSN {pub.issn}</span>
      {/if}
      {#if pub.publisher_name}
        <span class="publisher-name">— {pub.publisher_name}</span>
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
    {#if halSource}
      <a href={halDocUrl(halSource.source_id, pub.oa_status)} target="_blank" rel="noopener" class="source-link source-hal-link">
        <img src="https://hal.science/favicon.ico" alt="" class="source-ico" />
        HAL : {halSource.source_id}
      </a>
    {/if}
    {#if oaSource}
      <a href="https://openalex.org/{oaSource.source_id}" target="_blank" rel="noopener" class="source-link source-oa-link">
        <img src="https://raw.githubusercontent.com/ourresearch/openalex-gui/refs/heads/master/public/favicon.png" alt="" class="source-ico" />
        OpenAlex : {oaSource.source_id}
      </a>
    {/if}
    {#if scanrSource}
      <a href={scanrPubUrl(scanrSource.source_id)} target="_blank" rel="noopener" class="source-link source-scanr-link">
        <img src="{base}/scanr-icon.svg" alt="" class="source-ico" />
        ScanR : {scanrSource.source_id}
      </a>
    {/if}
    {#if wosSource}
      <a href="https://www.webofscience.com/wos/woscc/full-record/{wosSource.source_id}" target="_blank" rel="noopener" class="source-link source-wos-link">
        WoS : {wosSource.source_id}
      </a>
    {/if}
    {#if thesesSource}
      <a href="https://theses.fr/{thesesSource.source_id}" target="_blank" rel="noopener" class="source-link source-theses-link">
        <img src="https://theses.fr/favicon.ico" alt="" class="source-ico" />
        theses.fr : {thesesSource.source_id}
      </a>
    {/if}
  </div>

  {#if halSource?.hal_collections && halSource.hal_collections.length > 0}
    <div class="collections-line">
      <span class="collections-label">Collections HAL :</span>
      {#each halSource.hal_collections as col}
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
  }
  .issn {
    font-size: 0.85rem;
    color: var(--muted);
  }
  .publisher-name {
    font-size: 0.85rem;
    color: var(--muted);
  }
  .predatory-badge {
    display: inline-block;
    padding: 2px 8px;
    background: #fde8e8;
    border-radius: 3px;
    font-size: 0.8rem;
    font-weight: 600;
    color: #c0392b;
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
    background: #e8f0f8;
    color: #3b6b9e;
  }
  .source-hal-link:hover {
    background: #d0e3f4;
  }
  .source-oa-link {
    background: #fef3e0;
    color: #b8733e;
  }
  .source-oa-link:hover {
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
    color: #2e7d32;
  }
  .source-theses-link:hover {
    background: #d0ebd3;
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
    background: #f0efec;
    border-radius: 3px;
    font-size: 0.8rem;
    color: var(--muted);
  }
</style>
