<script lang="ts">
  import { resolve } from "$app/paths";
  import DocTypePill from "#lib/components/DocTypePill.svelte";
  import PublicationTitle from "#lib/components/PublicationTitle.svelte";
  import TitleRow from "#lib/components/TitleRow.svelte";
  import { relationTypeLabel, relationTier, relationTierRank } from "#lib/labels.js";
  import type { PubDetail, RelatedPublication } from "./types";

  const {
    pub,
    relations = [],
    onopenDrawer,
  }: {
    pub: PubDetail;
    relations?: RelatedPublication[];
    /** Ouvre le volet de la publication ; fourni en session admin. */
    onopenDrawer?: () => void;
  } = $props();

  // Trié par niveau de gravité (rétractation, erratum, rattachement, secondaire) ; l'ordre d'origine est conservé à l'intérieur d'un niveau (le tri JS est stable).
  const sortedRelations = $derived(
    [...relations].sort(
      (a, b) =>
        relationTierRank[relationTier[a.relation_type] ?? "secondary"] -
        relationTierRank[relationTier[b.relation_type] ?? "secondary"],
    ),
  );

  // Un jeu de données rattachant chacune de ses pièces génère une longue liste de relations. On n'en affiche que les premières (les plus graves, le tri les remonte) et on plie le reste derrière une bascule pour garder le header lisible.
  const RELATION_CAP = 5;
  let showAllRelations = $state(false);
  const visibleRelations = $derived(
    showAllRelations ? sortedRelations : sortedRelations.slice(0, RELATION_CAP),
  );

  // Lien vers l'œuvre liée : interne si elle est au corpus, sinon vers doi.org.
  function relHref(r: RelatedPublication): string {
    return r.publication_id ? resolve(`publications/${r.publication_id}`) : `https://doi.org/${r.doi}`;
  }
</script>

<div class="publication-header">
  <div class="publication-meta">
    {#if pub.doc_type}<DocTypePill docType={pub.doc_type} />{/if}
    {#if pub.publication_year}<span class="publication-year">{pub.publication_year}</span>{/if}
    {#if pub.doi}<span class="publication-doi"><span class="doi-label">DOI</span> <a href="https://doi.org/{pub.doi}" target="_blank" rel="noopener">{pub.doi}</a></span>{/if}
  </div>
  <div class="publication-title-row">
    <TitleRow onopen={onopenDrawer}>
      <h1 class="publication-title-main"><PublicationTitle titre={pub.title} /></h1>
    </TitleRow>
  </div>

  {#if pub.monograph_id || pub.journal_title || pub.container_title}
    <div class="publication-journal-line">
      <!-- Le livre ou le volume d'actes, puis sa collection ; sans monographie, la revue ou le titre brut du conteneur. -->
      {#if pub.monograph_id}
        <a href={resolve(`monographs/${pub.monograph_id}`)} class="journal-name"><PublicationTitle titre={pub.monograph_title} /></a>
        {#if pub.serial_id}
          <a href={resolve(`journals/${pub.serial_id}`)} class="collection-name">{pub.journal_title}</a>
        {/if}
      {:else if pub.serial_id}
        <a href={resolve(`journals/${pub.serial_id}`)} class="journal-name">{pub.journal_title || pub.container_title}</a>
      {:else}
        <span class="journal-name" class:container={!pub.journal_title}>{pub.journal_title || pub.container_title}</span>
      {/if}
      {#if pub.publisher_name}
        <!-- Le tiret passe à la ligne avec l'éditeur. -->
        <span class="publisher">
          <span class="publisher-sep">—</span>
          {#if pub.publisher_id}
            <a href={resolve(`publishers/${pub.publisher_id}`)} class="publisher-name">{pub.publisher_name}</a>
          {:else}
            <span class="publisher-name">{pub.publisher_name}</span>
          {/if}
        </span>
      {/if}
    </div>
  {/if}

  {#if sortedRelations.length}
    <div class="rel-banner">
      {#each visibleRelations as r (r.relation_type + (r.publication_id ?? r.doi))}
        {@const tier = relationTier[r.relation_type] ?? "secondary"}
        <a
          class="rel-item tier-{tier}"
          href={relHref(r)}
          target={r.publication_id ? undefined : "_blank"}
          rel={r.publication_id ? undefined : "noopener"}
        >
          <span class="rel-label">
            {#if tier === "danger" || tier === "warning"}
              <svg class="rel-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
            {:else}
              <svg class="rel-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M9 17H7A5 5 0 0 1 7 7h2M15 7h2a5 5 0 0 1 0 10h-2M8 12h8" />
              </svg>
            {/if}
            <span class="rel-kind">{relationTypeLabel[r.relation_type] ?? r.relation_type}</span>
          </span>
          <span class="rel-title"><PublicationTitle titre={r.title ?? r.doi} /></span>
        </a>
      {/each}
      {#if sortedRelations.length > RELATION_CAP}
        <button type="button" class="rel-toggle" onclick={() => (showAllRelations = !showAllRelations)}>
          {showAllRelations
            ? "Afficher moins"
            : `Afficher les ${sortedRelations.length - RELATION_CAP} autres`}
        </button>
      {/if}
    </div>
  {/if}

</div>

<style>
  .publication-header {
    margin-bottom: 28px;
  }
  .publication-title-row {
    margin: 12px 0;
  }
  .publication-title-main {
    margin: 0;
    font-size: var(--fs-3xl);
    font-weight: 700;
    line-height: 1.25;
    letter-spacing: -0.015em;
  }
  .publication-meta {
    display: flex;
    gap: 6px 14px;
    align-items: center;
    flex-wrap: wrap;
    font-size: var(--fs-md);
    color: var(--text-secondary);
  }
  .publication-year {
    font-weight: 600;
  }
  .publication-doi {
    overflow-wrap: anywhere;
  }
  .publication-doi a {
    color: var(--text-secondary);
  }
  .publication-doi a:hover {
    color: var(--accent);
  }
  .doi-label {
    font-size: var(--fs-sm);
    font-weight: 600;
    letter-spacing: 0.06em;
    color: var(--muted);
  }

  /* Bandeau des relations, en pied de header : volontairement voyant (fond teinté + filet d'accent épais), hiérarchisé par niveau de gravité (couleur + ordre) pour qu'on saisisse au premier coup d'œil qu'une publication est rattachée, corrigée ou rétractée. */
  .rel-banner {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin: 0 0 12px;
  }
  .rel-item {
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding: 10px 14px;
    border-left: 4px solid;
    border-radius: var(--radius);
    text-decoration: none;
  }
  /* Icône + type de relation forment un bloc « libellé » centré ensemble ; il s'aligne sur la première ligne du titre (via `align-items: baseline` du `.rel-item`) et y reste quand le titre passe sur plusieurs lignes. */
  .rel-label {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    flex: none;
  }
  .rel-icon {
    width: 16px;
    height: 16px;
    flex: none;
  }
  .rel-kind {
    text-transform: uppercase;
    font-size: var(--fs-xs);
    font-weight: 700;
    letter-spacing: 0.05em;
    white-space: nowrap;
  }
  .rel-title {
    font-size: var(--fs-base);
    font-weight: 600;
    color: var(--text);
    min-width: 0;
  }
  .rel-item:hover .rel-title {
    text-decoration: underline;
  }
  /* Bascule « afficher plus / moins » du bandeau : discrète, alignée à gauche comme un lien. */
  .rel-toggle {
    align-self: flex-start;
    margin-top: 2px;
    padding: 4px 6px;
    background: none;
    border: none;
    color: var(--muted);
    font-size: var(--fs-sm);
    font-weight: 600;
    cursor: pointer;
  }
  .rel-toggle:hover {
    color: var(--text);
    text-decoration: underline;
  }
  /* Niveaux : la couleur porte sur le filet, l'icône et le libellé ; le titre reste lisible. */
  .tier-danger {
    background: var(--danger-light);
    border-left-color: var(--danger);
  }
  .tier-danger .rel-icon,
  .tier-danger .rel-kind {
    color: var(--danger);
  }
  .tier-danger:hover {
    background: color-mix(in srgb, var(--danger) 14%, white);
  }
  .tier-warning {
    background: var(--warning-light);
    border-left-color: var(--warning);
  }
  .tier-warning .rel-icon,
  .tier-warning .rel-kind {
    color: var(--warning-text);
  }
  .tier-warning:hover {
    background: color-mix(in srgb, var(--warning) 20%, white);
  }
  .tier-parent {
    background: var(--accent-light);
    border-left-color: var(--accent);
  }
  .tier-parent .rel-icon,
  .tier-parent .rel-kind {
    color: var(--accent);
  }
  .tier-parent:hover {
    background: color-mix(in srgb, var(--accent) 14%, white);
  }
  .tier-secondary {
    background: var(--surface);
    border-left-color: var(--text-faint);
  }
  .tier-secondary .rel-icon,
  .tier-secondary .rel-kind {
    color: var(--muted);
  }
  .tier-secondary:hover {
    background: var(--hover);
  }

  .publication-journal-line {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
    font-size: var(--fs-md);
    margin-bottom: 8px;
  }
  .journal-name {
    font-weight: 500;
  }
  span.journal-name {
    color: var(--text);
  }
  span.journal-name.container {
    color: var(--muted);
    font-weight: 400;
  }
  .collection-name,
  .publisher-name {
    font-size: var(--fs-sm);
  }
  span.publisher-name {
    color: var(--muted);
  }
  .publisher {
    display: inline-flex;
    gap: 10px;
    align-items: center;
  }
  .publisher-sep {
    font-size: var(--fs-sm);
    color: var(--muted);
  }
</style>
