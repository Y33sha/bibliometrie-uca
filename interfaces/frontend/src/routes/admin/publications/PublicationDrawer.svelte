<script lang="ts">
  import { base } from "$app/paths";
  import { api, ApiError } from "$lib/api";
  import type { components } from "$lib/api/schema";
  import Drawer from "$lib/components/Drawer.svelte";
  import PublicationTitle from "$lib/components/PublicationTitle.svelte";
  import SourceTag from "$lib/components/SourceTag.svelte";
  import { sourceExternalUrl } from "$lib/sources";
  import { comparisonRows, orderRecords } from "./sourceComparison";

  type PublicationSources = components["schemas"]["PublicationSourcesResponse"];

  let { publicationId, onclose }: { publicationId: number; onclose: () => void } = $props();

  let data = $state<PublicationSources | null>(null);
  let failure = $state<string | null>(null);

  $effect(() => {
    const id = publicationId;
    data = null;
    failure = null;
    api<PublicationSources>(`/api/publications/${id}/sources`)
      .then((d) => {
        if (id === publicationId) data = d;
      })
      .catch((e) => {
        if (id !== publicationId) return;
        failure =
          e instanceof ApiError && e.status === 404
            ? "Publication introuvable."
            : "Chargement impossible.";
      });
  });

  // Une colonne par enregistrement source, une ligne par champ.
  const records = $derived(data ? orderRecords(data.source_publications) : []);
  const rows = $derived(comparisonRows(records));
</script>

<Drawer width="1200px" {onclose}>
  {#snippet head()}
    {#if data}
      <a
        class="drawer-title"
        href="{base}/publications/{publicationId}"
        target="_blank"
        rel="noopener"
        title="Voir la fiche publique"
      >
        <PublicationTitle titre={data.title} />
      </a>
    {/if}
  {/snippet}

  {#if failure}
    <p class="failure">{failure}</p>
  {:else if data}
    <section>
      <h3>Sources</h3>
      <div class="comparison-scroll">
        <table class="comparison">
          <thead>
            <tr>
              <th class="field" scope="col"></th>
              {#each records as r (r.id)}
                <th scope="col">
                  <span class="record-head">
                    <SourceTag
                      source={r.source}
                      href={sourceExternalUrl(r.source, r.source_id, r.oa_status)}
                      id={r.source_id}
                    />
                    <span class="record-id">{r.source_id}</span>
                  </span>
                </th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each rows as row (row.key)}
              <tr class:divergent={row.divergent}>
                <th
                  class="field"
                  scope="row"
                  title={row.divergent ? "Valeurs différentes selon les sources" : undefined}
                >
                  {row.label}
                </th>
                {#each row.cells as cell}
                  <td>
                    {#if cell.text === null}
                      <span class="absent">—</span>
                    {:else if cell.link?.kind === "doi"}
                      <a href="https://doi.org/{cell.link.doi}" target="_blank" rel="noopener">{cell.text}</a>
                    {:else if cell.link}
                      <a href="{base}/{cell.link.kind}/{cell.link.id}" target="_blank" rel="noopener">{cell.text}</a>
                    {:else}
                      {cell.text}
                    {/if}
                    {#if cell.note}
                      <div class="note" title="Nom donné par la source">{cell.note}</div>
                    {/if}
                  </td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>
  {/if}
</Drawer>

<style>
  .drawer-title {
    color: inherit;
    text-decoration: none;
    font-size: 1.05rem;
    font-weight: 600;
  }
  .drawer-title:hover {
    color: #2563eb;
    text-decoration: underline;
  }
  h3 {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #888;
    margin: 0 0 8px;
  }
  .comparison-scroll {
    overflow-x: auto;
  }
  .comparison {
    border-collapse: collapse;
    font-size: 0.85rem;
    min-width: 100%;
  }
  .comparison th,
  .comparison td {
    padding: 6px 10px;
    border-bottom: 1px solid var(--border-subtle, #eee);
    text-align: left;
    vertical-align: top;
  }
  .comparison thead th {
    border-bottom: 2px solid var(--border, #e0e0e0);
    white-space: nowrap;
  }
  .comparison td {
    min-width: 160px;
    max-width: 320px;
    overflow-wrap: anywhere;
  }
  .field {
    position: sticky;
    left: 0;
    background: #fff;
    color: #666;
    font-weight: 600;
    white-space: nowrap;
  }
  tr.divergent td,
  tr.divergent .field {
    background: #fff8e6;
  }
  tr.divergent .field {
    box-shadow: inset 3px 0 0 #f0a020;
  }
  .record-head {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .record-id {
    font-weight: 400;
    color: #666;
    font-size: 0.8rem;
  }
  .absent {
    color: #bbb;
  }
  .note {
    color: #888;
    font-size: 0.78rem;
    margin-top: 2px;
  }
  .failure {
    color: #888;
  }
</style>
