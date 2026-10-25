<script lang="ts">
  import { untrack } from "svelte";
  import { base } from "$app/paths";
  import { usePaginatedFetch } from "$lib/composables/usePaginatedFetch.svelte";
  import Pagination from "$lib/components/Pagination.svelte";
  import PublicationTitle from "$lib/components/PublicationTitle.svelte";
  import SourceTag from "$lib/components/SourceTag.svelte";
  import type { components } from "$lib/api/schema";

  type Suspect = components["schemas"]["SuspectMergeOut"];

  let {
    onopenPublication,
    activePublicationId,
  }: {
    /** Ouvre le volet d'une publication. */
    onopenPublication: (publicationId: number) => void;
    /** Publication dont le volet est ouvert. */
    activePublicationId: number | null;
  } = $props();

  const list = usePaginatedFetch<Suspect>({
    endpoint: "/api/publications/suspect-merges",
    itemsKey: "publications",
    apiKey: "suspect-merges",
    buildParams: () => new URLSearchParams(),
    pageParam: null,
  });

  $effect(() => {
    untrack(list.load);
  });

  const percent = (part: number, whole: number) => Math.round((100 * part) / whole);
</script>

<p class="intro">
  Publications dont <strong>moins de la moitié des auteurs</strong> se retrouvent d'un enregistrement source à
  l'autre&nbsp;: leurs listes d'auteurs ne se recouvrent pas, signe probable de deux œuvres réunies à
  tort. Pour chaque enregistrement source, le nombre de ses auteurs retrouvés dans un autre enregistrement source.
</p>

{#if !list.loaded}
  <div class="empty">Chargement…</div>
{:else if list.items.length === 0 && !list.loading}
  <div class="empty">Aucune fusion suspecte.</div>
{:else}
  <div class="rows">
    {#each list.items as item (item.publication_id)}
      <div class="row" class:active={item.publication_id === activePublicationId}>
        <div class="head">
          <button class="title" onclick={() => onopenPublication(item.publication_id)}>
            <PublicationTitle titre={item.title} />
          </button>
          <span class="meta">
            {item.doc_type}{#if item.publication_year} · {item.publication_year}{/if} ·
            <a href="{base}/publications/{item.publication_id}" target="_blank" rel="noopener"
              >listes d'auteurs</a
            >
          </span>
        </div>
        <div class="stats">
          <span class="share">
            {percent(item.matched_source_contributions, item.source_contributions)}&nbsp;% d'auteurs retrouvés
          </span>
          <span>{item.matched_source_contributions} / {item.source_contributions} contributions sources</span>
        </div>
        <div class="source-records">
          {#each item.source_records as n (n.source + n.source_id)}
            <span class="source-record">
              <SourceTag source={n.source} id={n.source_id} href={n.record_url} />
              {n.matched_source_contributions} / {n.source_contributions}
            </span>
          {/each}
        </div>
      </div>
    {/each}
  </div>

  <Pagination page={list.page} pages={list.pages} onchange={list.goToPage} />
{/if}

<style>
  .intro {
    font-size: 0.85rem;
    color: #555;
    margin: 4px 0 14px;
    max-width: 70ch;
  }
  .rows {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .row {
    border: 1px solid var(--border, #e0e0e0);
    border-radius: 6px;
    padding: 10px 12px;
  }
  .row.active {
    border-color: var(--accent, #2563eb);
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 12px;
    align-items: baseline;
    justify-content: space-between;
  }
  .title {
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    font: inherit;
    font-weight: 600;
    color: inherit;
    text-align: left;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .title:hover {
    color: var(--accent, #2563eb);
    text-decoration: underline;
  }
  .meta {
    font-size: 0.78rem;
    color: #888;
  }
  .stats {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 14px;
    font-size: 0.8rem;
    color: #555;
    margin-top: 4px;
  }
  .share {
    font-weight: 600;
    color: var(--danger, #c0392b);
  }
  .source-records {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 12px;
    margin-top: 6px;
    font-size: 0.8rem;
  }
  .source-record {
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  .empty {
    padding: 20px;
    color: #888;
  }
</style>
