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
