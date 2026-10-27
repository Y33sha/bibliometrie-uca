<script lang="ts">
  import { asset } from "$app/paths";
  import AccessButton from "#lib/components/AccessButton.svelte";
  import SourceTag from "#lib/components/SourceTag.svelte";
  import { accessTag } from "#lib/labels.js";
  import { licenseLabels } from "#lib/licenses.js";
  import { sourceLabel, sourceOrder } from "#lib/sources.svelte.js";
  import type { AccessLink, ExternalId, PubDetail, Source } from "./types";

  const {
    pub,
    accessUrl,
    access,
    referencedBy,
    externalIds,
  }: {
    pub: PubDetail;
    accessUrl: string | null;
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

  // Plateformes connues dont l'interface a l'icône, par leur nom (`domain/platforms/registry.py`).
  const PLATFORM_ICONS: Record<string, string> = {
    HAL: asset('icons/hal.ico'),
    arXiv: asset('icons/arxiv.png'),
    "PubMed Central": asset('icons/ncbi.png'),
    Zenodo: asset('icons/zenodo.png'),
    Figshare: asset('icons/figshare.png'),
    "CERN Document Server": asset('icons/cds.ico'),
    OpenEdition: asset('icons/openedition.png'),
  };
  // Pastilles colorées des icônes claires.
  const PLATFORM_TAG_CLASSES: Record<string, string> = { Zenodo: "tag-zenodo" };

  const orderedSources = $derived([
    ...sourceOrder().flatMap((src) => referencedBy.filter((s) => s.source === src)),
    ...referencedBy.filter((s) => !sourceOrder().includes(s.source)),
  ]);

  // Les formes secondaires convergées (pièces d'un jeu de données, versions, variantes) sont repliées : un jeu de données rattachant chacun de ses fichiers en aligne des dizaines.
  // L'enregistrement source theses mène à la même fiche theses.fr que le NNT, identifiant de la thèse : seul le NNT est listé quand il existe.
  const hasNnt = $derived(externalIds.some((e) => e.type === "nnt"));
  const primarySources = $derived(
    orderedSources.filter((s) => !s.is_secondary && !(hasNnt && s.source === "theses")),
  );
  const secondarySources = $derived(orderedSources.filter((s) => s.is_secondary));

  const accessState = $derived(accessTag(pub.oa_status));

  let labels = $state<Record<string, string>>({});
  $effect(() => {
    if (accessLicense) licenseLabels().then((l) => (labels = l)).catch(() => {});
  });

  // Plateforme de la copie donnée par le bouton : une copie listée, ou l'éditeur quand le bouton mène au DOI.
  const accessCopy = $derived(access.find((a) => a.url === accessUrl) ?? null);
  const viaPublisher = $derived(accessUrl != null && accessCopy == null);
  const otherAccess = $derived(access.filter((a) => a !== accessCopy));
  // Les plateformes du registre restent visibles ; les autres dépôts sont repliés.
  const knownAccess = $derived(otherAccess.filter((a) => a.known));
  const unknownAccess = $derived(otherAccess.filter((a) => !a.known));

  // Licence de la copie donnée : celle de la version éditeur par le DOI, celle du dépôt par HAL ; inconnue pour les autres plateformes.
  const accessLicense = $derived(viaPublisher ? pub.license : accessCopy?.label === "HAL" ? pub.deposit_license : null);
</script>

<aside class="detail-sidebar">
  <AccessButton {accessUrl} oaStatus={pub.oa_status} />

  {#if accessUrl && accessState}
    <div class="access-line">
      <span class="access-state" data-access={accessState.cls}><span class="access-dot"></span>Accès ouvert</span>
      {#if accessLicense}<span class="access-license">· {labels[accessLicense] ?? accessLicense}</span>{/if}
      {#if accessCopy || viaPublisher}
        <div class="access-via">via {viaPublisher ? "l'éditeur" : accessCopy?.label}</div>
      {/if}
    </div>
  {/if}

  {#snippet copyRow(copy: AccessLink)}
    <a href={copy.url} target="_blank" rel="noopener noreferrer" class="source-row" title={copy.url}>
      <span class="source-tag {PLATFORM_TAG_CLASSES[copy.label] ?? ''}">
        {#if PLATFORM_ICONS[copy.label]}
          <img src={PLATFORM_ICONS[copy.label]} alt={copy.label} />
        {/if}
      </span>
      <span class="row-label">{copy.label}</span>
    </a>
  {/snippet}

  {#if otherAccess.length > 0}
    <div class="sidebar-block">
      <h2 class="sidebar-title">Autres accès</h2>
      <div class="sidebar-sources">
        {#each knownAccess as copy (copy.url)}{@render copyRow(copy)}{/each}
      </div>
      {#if unknownAccess.length}
        <details class="folded">
          <summary>{unknownAccess.length} {knownAccess.length ? "autres dépôts" : unknownAccess.length > 1 ? "dépôts" : "dépôt"}</summary>
          <div class="sidebar-sources">
            {#each unknownAccess as copy (copy.url)}{@render copyRow(copy)}{/each}
          </div>
        </details>
      {/if}
    </div>
  {/if}

  {#snippet sourceRow(s: Source)}
    <a
      href={s.record_url}
      target="_blank"
      rel="noopener"
      class="source-row"
      title={s.source_id}
    >
      <SourceTag source={s.source} />
      <span class="row-label">{sourceLabel(s.source)}</span>
    </a>
  {/snippet}

  {#if orderedSources.length > 0 || externalIds.length > 0}
    <div class="sidebar-block">
      <h2 class="sidebar-title">Référencé dans</h2>
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
            title={e.value}
          >
            <span class="source-tag">
              {#if EXT_META[e.type]?.icon}
                <img src={EXT_META[e.type].icon} alt={EXT_META[e.type]?.label} />
              {/if}
            </span>
            <span class="row-label">{EXT_META[e.type]?.label ?? e.type}</span>
          </a>
        {/each}
      </div>
      {#if secondarySources.length}
        <details class="folded">
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
  /* Encadré d'accès, teinté, qui reste visible au défilement. */
  .detail-sidebar {
    align-self: start;
    position: sticky;
    top: calc(var(--header-height) + 16px);
    padding: 20px;
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--accent-light) 55%, var(--bg));
  }
  .access-line {
    margin-top: 10px;
    font-size: 0.9rem;
    line-height: 1.5;
    color: var(--text-secondary);
  }
  .access-state {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-weight: 600;
  }
  .access-dot {
    width: 8px;
    height: 8px;
    border-radius: var(--radius-pill);
    background: currentColor;
  }
  .access-state {
    color: var(--open-text);
  }
  .access-via {
    color: var(--muted);
  }
  .sidebar-block {
    margin-top: 22px;
  }
  .sidebar-title {
    margin: 0 0 8px;
    padding-bottom: 6px;
    border-bottom: 1px solid color-mix(in srgb, var(--accent) 15%, white);
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-secondary);
  }
  .sidebar-sources {
    display: flex;
    flex-direction: column;
  }
  .source-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 0 -8px;
    padding: 6px 8px;
    border-radius: var(--radius);
    text-decoration: none;
  }
  .source-row:hover {
    background: color-mix(in srgb, var(--accent-light) 60%, white);
    text-decoration: none;
  }
  /* La pastille garde sa largeur, icône ou non : les libellés restent alignés. */
  .source-row :global(.source-tag) {
    flex-shrink: 0;
  }
  /* Le lien couvre toute la ligne : l'icône grossit au survol de la ligne entière, pas seulement de l'icône. */
  .source-row:hover :global(.source-tag) {
    transform: scale(1.15);
  }
  .row-label {
    font-size: 0.9rem;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* Groupe replié, fermé par défaut : dépôts hors registre, sources secondaires. */
  .folded {
    margin-top: 6px;
  }
  .folded > summary {
    font-size: 0.8rem;
    color: var(--muted);
    cursor: pointer;
    padding: 3px 0;
    user-select: none;
  }
  .folded > summary:hover {
    color: var(--text);
  }
  .folded[open] > summary {
    margin-bottom: 6px;
  }
</style>
