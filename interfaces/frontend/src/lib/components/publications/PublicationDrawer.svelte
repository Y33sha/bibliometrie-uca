<script lang="ts">
  import { resolve } from "$app/paths";
  import { api, ApiError } from "#lib/api/index.js";
  import type { components } from "#lib/api/schema.js";
  import Drawer from "#lib/components/Drawer.svelte";
  import PublicationTitle from "#lib/components/PublicationTitle.svelte";
  import PublicationMergeSection from "#lib/components/publications/PublicationMergeSection.svelte";
  import SourceTag from "#lib/components/SourceTag.svelte";
  import Tooltip from "#lib/components/Tooltip.svelte";
  import { contributionRoleLabels } from "#lib/labels.js";
  import { isAdmin } from "#lib/session.svelte.js";
  import { structsTooltip } from "#lib/structureLabels.js";
  import { authorRows, comparisonRows, orderRecords, otherRoles } from "./sourceComparison";

  type PublicationSources = components["schemas"]["PublicationSourcesResponse"];

  // `onopen` ouvre le volet d'une autre publication : la publication conservée par une fusion.
  let {
    publicationId,
    onclose,
    onopen,
  }: { publicationId: number; onclose: () => void; onopen: (publicationId: number) => void } =
    $props();

  let data = $state<PublicationSources | null>(null);
  let failure = $state<string | null>(null);
  // Incrémenté après une fusion qui conserve cette publication, pour relire ses enregistrements sources.
  let version = $state(0);

  function merged(keptId: number) {
    if (keptId === publicationId) version++;
    else onopen(keptId);
  }

  $effect(() => {
    const id = publicationId;
    void version;
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

  // Une colonne par enregistrement source ; une ligne par champ, puis une ligne par contribution d'un même auteur.
  const records = $derived(data ? orderRecords(data.source_records) : []);
  const rows = $derived(comparisonRows(records));
  const authors = $derived(data ? authorRows(records, data.source_contributions) : []);
</script>

<Drawer width="max(1200px, 67vw)" {onclose}>
  {#snippet head()}
    {#if data}
      <a
        class="drawer-title"
        href={resolve(`publications/${publicationId}`)}
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
    <table class="comparison">
      <thead>
        <tr>
          <th class="field" scope="col">Sources</th>
          {#each records as r (r.id)}
            <th scope="col">
              <span class="record-head">
                <SourceTag
                  source={r.source}
                  href={r.record_url}
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
                  <a href={resolve(cell.link.kind === "serials" ? `journals/${cell.link.id}` : `publishers/${cell.link.id}`)} target="_blank" rel="noopener">{cell.text}</a>
                {:else if cell.title}
                  <PublicationTitle titre={cell.text} />
                {:else}
                  {#if cell.corrected}
                    <del class="uncorrected" title={cell.corrected.rule ? `Corrigé par la règle ${cell.corrected.rule}` : "Corrigé"}>{cell.corrected.from}</del>
                  {/if}
                  {cell.text}
                {/if}
                {#if cell.note}
                  <div class="note" title="Valeur donnée par la source">{cell.note}</div>
                {/if}
              </td>
            {/each}
          </tr>
        {/each}
        {#if authors.length}
          <tr class="section-row">
            <th class="field" scope="row">Auteurs</th>
            <td colspan={records.length}></td>
          </tr>
        {/if}
        {#each authors as row (row.key)}
          <tr class:divergent={row.divergent}>
            <th
              class="field unlabeled"
              scope="row"
              title={row.divergent ? "Contribution source absente d'un enregistrement source" : undefined}
            ></th>
            {#each row.cells as s}
              <td class="author-cell">
                {#if s}
                  <span class="position">{s.position != null ? s.position + 1 : ""}</span>
                  <span class="author">
                    {#if s.person_id}
                      <a
                        href={resolve(`persons/${s.person_id}`)}
                        target="_blank"
                        rel="noopener"
                        class:in-perimeter={s.in_perimeter}>{s.full_name}</a
                      >
                    {:else}
                      <span class:in-perimeter={s.in_perimeter}>{s.full_name}</span>
                    {/if}
                    {#if structsTooltip(s, data.structures)}
                      <Tooltip text={structsTooltip(s, data.structures)}
                        ><span class="info">&#9432;</span></Tooltip
                      >
                    {/if}
                    {#if s.countries?.length}
                      <span class="countries"
                        >{s.countries.map((c) => c.toUpperCase()).join(" ")}</span
                      >
                    {/if}
                    {#if otherRoles(s).length}
                      <span class="roles"
                        >{otherRoles(s)
                          .map((r) => (contributionRoleLabels[r] ?? r).toLowerCase())
                          .join(", ")}</span
                      >
                    {/if}
                  </span>
                {/if}
              </td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>
    {#if isAdmin()}
      <PublicationMergeSection {publicationId} onmerged={merged} />
    {/if}
  {/if}
</Drawer>

<style>
  .drawer-title {
    color: inherit;
    text-decoration: none;
    font-size: var(--fs-base);
    font-weight: 600;
  }
  .drawer-title:hover {
    color: var(--accent);
    text-decoration: underline;
  }
  .comparison {
    border-collapse: collapse;
    font-size: var(--fs-sm);
  }
  .comparison th,
  .comparison td {
    padding: 6px 10px;
    border-bottom: 1px solid var(--border-subtle);
    text-align: left;
    vertical-align: top;
  }
  /* Une valeur liée se distingue d'une valeur en texte autrement que par la couleur. */
  .comparison td a {
    text-decoration: underline;
    text-decoration-color: color-mix(in srgb, currentColor 40%, transparent);
    text-underline-offset: 2px;
  }
  /* En-têtes des sources et des champs figés aux bords haut et gauche du volet, qui défile dans les deux sens. Les décalages négatifs compensent les marges intérieures du corps du volet, dans lesquelles `top: 0` et `left: 0` laisseraient passer les cellules défilées ; les marges négatives du tableau collent les en-têtes à ces bords dès l'ouverture. Le filet du bas est une ombre : une bordure de tableau fusionnée reste en place au défilement. */
  .comparison {
    margin-top: calc(-1 * var(--drawer-padding-y));
    margin-left: calc(-1 * var(--drawer-padding-x));
    min-width: calc(100% + var(--drawer-padding-x));
  }
  .comparison thead th {
    position: sticky;
    top: calc(-1 * var(--drawer-padding-y));
    z-index: 2;
    background: var(--card);
    border-bottom: none;
    box-shadow: inset 0 -2px 0 var(--border);
    white-space: nowrap;
  }
  /* Colonnes des enregistrements sources : la marge gauche reçoit le numéro de position des auteurs. */
  .comparison {
    --position-gutter: 2.8em;
  }
  .comparison td,
  .comparison thead th:not(.field) {
    padding-left: var(--position-gutter);
  }
  .comparison td {
    min-width: 160px;
    max-width: 320px;
    overflow-wrap: anywhere;
  }
  /* Le retrait des libellés les aligne sur le reste du volet. */
  .comparison .field {
    padding-left: calc(10px + var(--drawer-padding-x));
  }
  .field {
    position: sticky;
    left: calc(-1 * var(--drawer-padding-x));
    z-index: 1;
    background: var(--row-bg);
    color: var(--muted);
    font-weight: 600;
    white-space: nowrap;
  }
  /* Les lignes d'auteurs n'ont pas de libellé : seule la marge du volet y reste opaque. */
  .field.unlabeled {
    background: linear-gradient(to right, var(--row-bg) var(--drawer-padding-x), transparent 0);
  }
  .comparison thead th.field {
    z-index: 3;
  }
  .comparison {
    --row-bg: var(--card);
  }
  /* La couleur de la ligne est peinte sous la partie transparente des cellules sans libellé. */
  tr.divergent {
    --row-bg: var(--warning-light);
    background: var(--row-bg);
  }
  tr.divergent .field {
    box-shadow: inset 3px 0 0 var(--warning);
  }
  .record-head {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .record-id {
    font-weight: 400;
    color: var(--muted);
    font-size: var(--fs-sm);
  }
  .absent {
    color: var(--text-faint);
  }
  .note {
    color: var(--muted);
    font-size: var(--fs-sm);
    margin-top: 2px;
  }
  .uncorrected {
    color: var(--muted);
    margin-right: 4px;
  }
  .failure {
    color: var(--muted);
  }
  .section-row th,
  .section-row td {
    border-bottom: 2px solid var(--border);
    padding-top: 14px;
    color: var(--text);
  }
  .author-cell {
    position: relative;
  }
  .position {
    position: absolute;
    left: 0;
    width: calc(var(--position-gutter) - 6px);
    color: var(--muted);
    font-size: var(--fs-sm);
    font-variant-numeric: tabular-nums;
    text-align: right;
    white-space: nowrap;
  }
  .in-perimeter {
    font-weight: 600;
  }
  .info {
    color: var(--muted);
    cursor: help;
    margin-left: 3px;
  }
  .countries,
  .roles {
    color: var(--muted);
    font-size: var(--fs-sm);
    margin-left: 4px;
  }

  .roles {
    font-style: italic;
  }

</style>
