<script lang="ts">
  import { asset } from "$app/paths";
  import SourceTag from "#lib/components/SourceTag.svelte";
  import { accessTag } from "#lib/labels.js";
  import { licenseLabels } from "#lib/licenses.js";
  import { sourceLabel, sourceOrder } from "#lib/sources.svelte.js";
  import type { AccessLink, ExternalId, PubDetail, Source } from "./types";

  const {
    pub,
    bestCopyUrl,
    access,
    referencedBy,
    externalIds,
  }: {
    pub: PubDetail;
    bestCopyUrl: string | null;
    access: AccessLink[];
    referencedBy: Source[];
    externalIds: ExternalId[];
  } = $props();

  const EXT_META: Record<string, { label: string; icon: string; url: (v: string) => string }> = {
    pmid: {
      label: "PubMed",
      icon: asset('icons/ncbi.png'),
      url: (v) => `https://pubmed.ncbi.nlm.nih.gov/${v}`,
    },
    nnt: { label: "Thèses.fr", icon: asset('icons/theses.ico'), url: (v) => `https://theses.fr/${v}` },
  };

  const orderedSources = $derived([
    ...sourceOrder().flatMap((src) => referencedBy.filter((s) => s.source === src)),
    ...referencedBy.filter((s) => !sourceOrder().includes(s.source)),
  ]);

  // Les formes secondaires convergées (pièces d'un jeu de données, versions, variantes) sont repliées : un jeu de données rattachant chacun de ses fichiers en aligne des dizaines.
  const primarySources = $derived(orderedSources.filter((s) => !s.is_secondary));
  const secondarySources = $derived(orderedSources.filter((s) => s.is_secondary));

  const accessState = $derived(accessTag(pub.oa_status));

  let labels = $state<Record<string, string>>({});
  $effect(() => {
    if (pub.license || pub.deposit_license) licenseLabels().then((l) => (labels = l)).catch(() => {});
  });

  // Le bouton d'accès mène à la meilleure copie ouverte, à défaut au DOI ; une publication fermée ou sous embargo n'en a pas.
  const accessUrl = $derived.by(() => {
    const oa = pub.oa_status;
    if (oa === "closed" || oa === "embargoed") return null;
    return bestCopyUrl ?? (pub.doi ? `https://doi.org/${pub.doi}` : null);
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
  {:else if accessState}
    <div class="access-status {accessState.cls}">
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
      {accessState.label}
    </div>
  {/if}

  {#if access.length > 0}
    <div class="sidebar-block">
      <div class="detail-sublabel">Accès</div>
      <div class="access-links">
        {#each access as copy (copy.url)}
          <a href={copy.url} target="_blank" rel="noopener noreferrer">{copy.label}</a>
        {/each}
      </div>
    </div>
  {/if}

  {#if pub.doi}
    <div class="sidebar-block">
      <div class="detail-sublabel">DOI</div>
      <a class="doi-link" href="https://doi.org/{pub.doi}" target="_blank" rel="noopener">{pub.doi}</a>
    </div>
  {/if}

  {#if pub.license || pub.deposit_license}
    <div class="sidebar-block">
      <div class="detail-sublabel">Licence</div>
      <dl class="licenses">
        {#if pub.license}
          <dt>Version éditeur</dt>
          <dd>{labels[pub.license] ?? pub.license}</dd>
        {/if}
        {#if pub.deposit_license}
          <dt>Dépôt HAL</dt>
          <dd>{labels[pub.deposit_license] ?? pub.deposit_license}</dd>
        {/if}
      </dl>
    </div>
  {/if}

  {#snippet sourceRow(s: Source)}
    <a
      href={s.record_url}
      target="_blank"
      rel="noopener"
      class="source-row"
      title="{sourceLabel(s.source)} : {s.source_id}"
    >
      <SourceTag source={s.source} />
      <span class="source-id">{s.source_id}</span>
    </a>
  {/snippet}

  {#if orderedSources.length > 0 || externalIds.length > 0}
    <div class="sidebar-block">
      <div class="detail-sublabel">Référencé par</div>
      <div class="sidebar-sources">
        {#each primarySources as s (s.source + s.source_id)}
          {@render sourceRow(s)}
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
      {#if secondarySources.length}
        <details class="secondary-sources">
          <summary>{secondarySources.length} sources secondaires (pièces, versions)</summary>
          <div class="sidebar-sources">
            {#each secondarySources as s (s.source + s.source_id)}
              {@render sourceRow(s)}
            {/each}
          </div>
        </details>
      {/if}
    </div>
  {/if}
</aside>

<style>
  .access-links {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
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
    word-break: break-all;
  }
  .licenses {
    margin: 0;
    font-size: 0.85rem;
  }
  .licenses dt {
    color: var(--muted);
    font-size: 0.78rem;
  }
  .licenses dd {
    margin: 0 0 4px;
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
  /* Le lien couvre toute la ligne : l'icône gonfle au survol de la ligne entière, pas seulement au survol de l'icône. */
  .source-row:hover :global(.source-tag) {
    transform: scale(1.15);
  }
  .source-id {
    font-size: 0.82rem;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* Groupe replié des sources secondaires (pièces / versions convergées) : discret, fermé par défaut, mêmes lignes que les sources primaires une fois déplié. */
  .secondary-sources {
    margin-top: 6px;
  }
  .secondary-sources > summary {
    font-size: 0.78rem;
    color: var(--muted);
    cursor: pointer;
    padding: 3px 4px;
    user-select: none;
  }
  .secondary-sources > summary:hover {
    color: var(--text);
  }
  .secondary-sources[open] > summary {
    margin-bottom: 6px;
  }
</style>
