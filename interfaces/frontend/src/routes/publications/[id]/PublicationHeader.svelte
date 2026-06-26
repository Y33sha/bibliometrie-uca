<script lang="ts">
  import { base } from "$app/paths";
  import { sanitizeTitle } from "$lib/utils";
  import { docTypeSingular, relationTypeLabel, relationTier, relationTierRank } from "$lib/labels";
  import type { PubDetail, RelatedPublication } from "./types";

  const { pub, relations = [] }: { pub: PubDetail; relations?: RelatedPublication[] } = $props();

  // Trié par niveau de gravité (rétractation, erratum, rattachement, secondaire) ; l'ordre d'origine
  // est conservé à l'intérieur d'un niveau (le tri JS est stable).
  const sortedRelations = $derived(
    [...relations].sort(
      (a, b) =>
        relationTierRank[relationTier[a.relation_type] ?? "secondary"] -
        relationTierRank[relationTier[b.relation_type] ?? "secondary"],
    ),
  );

  // Lien vers l'œuvre liée : interne si elle est au corpus, sinon vers doi.org.
  function relHref(r: RelatedPublication): string {
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

  {#if sortedRelations.length}
    <div class="rel-banner">
      {#each sortedRelations as r (r.relation_type + (r.publication_id ?? r.doi))}
        {@const tier = relationTier[r.relation_type] ?? "secondary"}
        <a
          class="rel-item tier-{tier}"
          href={relHref(r)}
          target={r.publication_id ? undefined : "_blank"}
          rel={r.publication_id ? undefined : "noopener"}
        >
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
          <span class="rel-title">{@html sanitizeTitle(r.title ?? r.doi ?? "")}</span>
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

  /* Bandeau des relations, en pied de header : volontairement voyant (fond teinté + filet d'accent
     épais), hiérarchisé par niveau de gravité (couleur + ordre) pour qu'on saisisse au premier coup
     d'œil qu'une publi est rattachée, corrigée ou rétractée. */
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
    border-radius: 4px;
    text-decoration: none;
  }
  .rel-icon {
    width: 16px;
    height: 16px;
    flex: none;
    align-self: center;
  }
  .rel-kind {
    text-transform: uppercase;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    white-space: nowrap;
  }
  .rel-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--text);
    min-width: 0;
  }
  .rel-item:hover .rel-title {
    text-decoration: underline;
  }
  /* Niveaux : la couleur porte sur le filet, l'icône et le libellé ; le titre reste lisible. */
  .tier-danger {
    background: #fef3f2;
    border-left-color: #d92d20;
  }
  .tier-danger .rel-icon,
  .tier-danger .rel-kind {
    color: #b42318;
  }
  .tier-danger:hover {
    background: #fee4e2;
  }
  .tier-warning {
    background: #fffaeb;
    border-left-color: #f79009;
  }
  .tier-warning .rel-icon,
  .tier-warning .rel-kind {
    color: #b54708;
  }
  .tier-warning:hover {
    background: #fef0c7;
  }
  .tier-parent {
    background: #eef4f5;
    border-left-color: #15616d;
  }
  .tier-parent .rel-icon,
  .tier-parent .rel-kind {
    color: #15616d;
  }
  .tier-parent:hover {
    background: #e1edef;
  }
  .tier-secondary {
    background: #f5f6f7;
    border-left-color: #98a2b3;
  }
  .tier-secondary .rel-icon,
  .tier-secondary .rel-kind {
    color: #667085;
  }
  .tier-secondary:hover {
    background: #eceef0;
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
