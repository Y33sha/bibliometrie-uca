<script lang="ts">
  import { asset } from "$app/paths";
  import type { AssetPath } from "$app/types";
  import AccessButton from "#lib/components/AccessButton.svelte";
  import SourceTag from "#lib/components/SourceTag.svelte";
  import LicenseBadge from "#lib/components/LicenseBadge.svelte";
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

  // Pastilles colorées des icônes claires.
  const PLATFORM_LOGO_CLASSES: Record<string, string> = { Zenodo: "logo-zenodo" };

  const orderedSources = $derived([
    ...sourceOrder().flatMap((src) => referencedBy.filter((s) => s.source === src)),
    ...referencedBy.filter((s) => !sourceOrder().includes(s.source)),
  ]);

  // L'enregistrement source theses mène à la même fiche theses.fr que le NNT, identifiant de la thèse : seul le NNT est listé quand il existe.
  const hasNnt = $derived(externalIds.some((e) => e.type === "nnt"));
  const listedSources = $derived(
    orderedSources.filter((s) => !(hasNnt && s.source === "theses")),
  );

  const oaStatusKnown = $derived(pub.oa_status != null && pub.oa_status !== "unknown");

  // Plateforme de la copie donnée par le bouton : une copie listée, ou l'éditeur quand le bouton mène au DOI.
  const accessCopy = $derived(access.find((a) => a.url === accessUrl) ?? null);
  const viaPublisher = $derived(accessUrl != null && accessCopy == null);
  // Seules les plateformes à icône figurent parmi les autres accès.
  const otherAccess = $derived(access.filter((a) => a !== accessCopy && a.icon));

  // Licence de la copie donnée : celle de la version éditeur par le DOI, celle du dépôt par HAL ; inconnue pour les autres plateformes.
  const accessLicense = $derived(viaPublisher ? pub.license : accessCopy?.label === "HAL" ? pub.deposit_license : null);
</script>

<aside class="detail-sidebar">
  <AccessButton {accessUrl} oaStatus={pub.oa_status} docType={pub.doc_type} />

  {#if accessUrl && oaStatusKnown}
    <div class="access-line">
      <span class="access-state"><span class="access-dot"></span>Accès ouvert</span>
      {#if accessLicense}<span class="access-license">· <LicenseBadge license={accessLicense} /></span>{/if}
      {#if accessCopy || viaPublisher}
        <div class="muted">via {viaPublisher ? "l'éditeur" : accessCopy?.label}</div>
      {/if}
    </div>
  {/if}

  {#snippet copyRow(copy: AccessLink)}
    <a href={copy.url} target="_blank" rel="noopener noreferrer" class="source-row" title={copy.url}>
      <span class="logo-icon logo-source {PLATFORM_LOGO_CLASSES[copy.label] ?? ''}">
        <img src={asset(`icons/${copy.icon}` as AssetPath)} alt={copy.label} />
      </span>
      <span class="row-label">{copy.label}</span>
    </a>
  {/snippet}

  {#if otherAccess.length > 0}
    <div class="sidebar-block">
      <h2 class="sidebar-title">Autres accès</h2>
      <div class="sidebar-sources">
        {#each otherAccess as copy (copy.url)}{@render copyRow(copy)}{/each}
      </div>
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
        {#each listedSources as s (s.source + s.source_id)}
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
            <span class="logo-icon logo-source">
              {#if EXT_META[e.type]?.icon}
                <img src={EXT_META[e.type].icon} alt={EXT_META[e.type]?.label} />
              {/if}
            </span>
            <span class="row-label">{EXT_META[e.type]?.label ?? e.type}</span>
          </a>
        {/each}
      </div>
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
    font-size: var(--fs-md);
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
  .sidebar-block {
    margin-top: 22px;
  }
  .sidebar-title {
    margin: 0 0 8px;
    padding-bottom: 6px;
    border-bottom: 1px solid color-mix(in srgb, var(--accent) 15%, white);
    font-size: var(--fs-xs);
    font-weight: 700;
    letter-spacing: var(--tracking-caps);
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
    background: var(--card);
    text-decoration: none;
  }
  /* La pastille garde sa largeur, icône ou non : les libellés restent alignés. */
  .source-row :global(.logo-icon) {
    flex-shrink: 0;
  }
  .row-label {
    font-size: var(--fs-md);
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
