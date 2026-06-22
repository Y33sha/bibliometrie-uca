<script lang="ts">
  import { base } from "$app/paths";
  import SourceTag from "$lib/components/SourceTag.svelte";
  import { accessTag } from "$lib/labels";
  import { sourceExternalUrl, sourceLabel, SOURCE_ORDER } from "$lib/sources";
  import type { ExternalId, PubDetail, Source } from "./types";

  const {
    pub,
    sources,
    externalIds,
  }: { pub: PubDetail; sources: Source[]; externalIds: ExternalId[] } = $props();

  // NCBI sert un favicon unique pour PubMed et PMC : on les distingue par la valeur, pas le logo.
  const EXT_META: Record<string, { label: string; icon: string; url: (v: string) => string }> = {
    arxiv: { label: "arXiv", icon: `${base}/icons/arxiv.png`, url: (v) => `https://arxiv.org/abs/${v}` },
    pmid: {
      label: "PubMed",
      icon: `${base}/icons/ncbi.png`,
      url: (v) => `https://pubmed.ncbi.nlm.nih.gov/${v}`,
    },
    pmcid: {
      label: "PMC",
      icon: `${base}/icons/ncbi.png`,
      url: (v) => `https://www.ncbi.nlm.nih.gov/pmc/articles/${v}/`,
    },
    nnt: { label: "Thèses.fr", icon: `${base}/icons/theses.ico`, url: (v) => `https://theses.fr/${v}` },
  };

  const orderedSources = $derived([
    ...SOURCE_ORDER.flatMap((src) => sources.filter((s) => s.source === src)),
    ...sources.filter((s) => !SOURCE_ORDER.includes(s.source)),
  ]);

  const access = $derived(accessTag(pub.oa_status));

  // Lien d'accès, dérivé (pas de champ URL unique en base) :
  //   closed / embargoed → aucun lien ; green → dépôt HAL ; sinon → DOI.
  // Exception green : un DOI DataCite (Zenodo, figshare, arXiv…) pointe vers le
  // dépôt réel ; le dépôt HAL correspondant est souvent une coquille vide, donc
  // on préfère le DOI dans ce cas.
  const accessUrl = $derived.by(() => {
    const oa = pub.oa_status;
    if (oa === "closed" || oa === "embargoed") return null;
    if (oa === "green" && pub.doi_ra !== "DataCite") {
      const hal = sources.find((s) => s.source === "hal");
      if (hal) return sourceExternalUrl("hal", hal.source_id, oa);
    }
    return pub.doi ? `https://doi.org/${pub.doi}` : null;
  });
</script>

<aside class="detail-sidebar">
  {#if accessUrl}
    <a class="access-btn" href={accessUrl} target="_blank" rel="noopener">
      Accéder
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M7 17L17 7M17 7H8M17 7v9" />
      </svg>
    </a>
  {:else if access}
    <div class="access-status {access.cls}">
      {#if pub.oa_status === "embargoed"}
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
      {:else}
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
        </svg>
      {/if}
      {access.label}
    </div>
  {/if}

  {#if pub.doi}
    <div class="sidebar-block">
      <div class="detail-sublabel">DOI</div>
      <a class="doi-link" href="https://doi.org/{pub.doi}" target="_blank" rel="noopener">{pub.doi}</a>
    </div>
  {/if}

  {#if orderedSources.length > 0 || externalIds.length > 0}
    <div class="sidebar-block">
      <div class="detail-sublabel">Sources</div>
      <div class="sidebar-sources">
        {#each orderedSources as s}
          <a
            href={sourceExternalUrl(s.source, s.source_id, pub.oa_status)}
            target="_blank"
            rel="noopener"
            class="source-row"
            title="{sourceLabel(s.source)} : {s.source_id}"
          >
            <SourceTag source={s.source} />
            <span class="source-id">{s.source_id}</span>
          </a>
        {/each}
        {#each externalIds as e (e.type + e.value)}
          <a
            href={EXT_META[e.type] ? EXT_META[e.type].url(e.value) : "#"}
            target="_blank"
            rel="noopener"
            class="source-row"
            title="{EXT_META[e.type]?.label ?? e.type} : {e.value}"
          >
            <span class="source-tag">
              {#if EXT_META[e.type]?.icon}
                <img src={EXT_META[e.type].icon} alt={EXT_META[e.type]?.label} />
              {/if}
            </span>
            <span class="source-id">{e.value}</span>
          </a>
        {/each}
      </div>
    </div>
  {/if}
</aside>

<style>
  .detail-sidebar {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px;
    align-self: start;
    position: sticky;
    /* Sous le menu supérieur fixe (sticky top:0) + petit écart, sinon masquée au scroll. */
    top: calc(var(--header-height) + 12px);
  }
  .access-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 9px 12px;
    background: var(--section-heading);
    color: white;
    font-weight: 600;
    font-size: 0.95rem;
    text-decoration: none;
    margin-bottom: 14px;
  }
  .access-btn:hover {
    background: #336668;
  }
  .access-btn svg {
    width: 15px;
    height: 15px;
  }
  .access-status {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 9px 12px;
    font-weight: 600;
    font-size: 0.95rem;
    margin-bottom: 14px;
  }
  .access-status svg {
    width: 15px;
    height: 15px;
  }
  .sidebar-block {
    margin-bottom: 14px;
  }
  .sidebar-block:last-child {
    margin-bottom: 0;
  }
  .doi-link {
    font-size: 0.85rem;
    color: var(--accent);
    text-decoration: none;
    word-break: break-all;
  }
  .doi-link:hover {
    text-decoration: underline;
  }
  .sidebar-sources {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  /* Rectangle neutre couvrant logo + identifiant ; seul le logo (SourceTag) garde sa teinte. */
  .source-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 8px;
    border-radius: 4px;
    background: var(--surface);
    text-decoration: none;
  }
  .source-row:hover {
    background: var(--surface-hover);
  }
  .source-id {
    font-size: 0.82rem;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
