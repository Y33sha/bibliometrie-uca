<script lang="ts">
  import ClampedBlock from "#lib/components/ClampedBlock.svelte";
  import { formatDate } from "#lib/utils.js";
  import DetailTable from "./DetailTable.svelte";
  import StructureTag from "./StructureTag.svelte";
  import type { PatentMeta, StructInfo } from "./types";

  const {
    patentMeta,
    structures,
  }: {
    patentMeta: PatentMeta;
    structures: Record<string, StructInfo>;
  } = $props();

  // Offices sans pays : l'Office européen des brevets et les demandes internationales selon le traité de coopération en matière de brevets (PCT).
  const OFFICE_LABELS: Record<string, string> = {
    EP: "Europe (OEB)",
    WO: "International (PCT)",
  };
  const regionNames = new Intl.DisplayNames(["fr"], { type: "region" });

  function officeLabel(office: string): string {
    if (OFFICE_LABELS[office]) return OFFICE_LABELS[office];
    try {
      return regionNames.of(office) ?? office;
    } catch {
      return office;
    }
  }

  // Recherche du numéro de publication sur Espacenet, préfixé du code de l'office.
  function espacenetUrl(office: string, publicationNumber: string): string {
    return `https://worldwide.espacenet.com/patent/search?q=${encodeURIComponent(`pn="${office}${publicationNumber}"`)}`;
  }

  const organisations = $derived(patentMeta.applicants.filter((a) => a.type !== "person"));
  const persons = $derived(patentMeta.applicants.filter((a) => a.type === "person"));
</script>

<DetailTable title="Brevet">
  {#if organisations.length || persons.length}
    <dt>Déposants</dt>
    <dd>
      <div class="applicants">
        {#each organisations as applicant (applicant.name)}
          {#if applicant.structure_id != null && structures[String(applicant.structure_id)]}
            <StructureTag {structures} sid={applicant.structure_id} />
          {:else}
            <span class="tag">{applicant.name}</span>
          {/if}
        {/each}
      </div>
      {#if persons.length}
        <div class="persons">{persons.map((p) => p.name).join(", ")}</div>
      {/if}
    </dd>
  {/if}

  {#if patentMeta.grant_date}
    <dt>Délivrance</dt>
    <dd>Premier brevet délivré le {formatDate(patentMeta.grant_date)}</dd>
  {/if}

  {#if patentMeta.applications.length}
    <dt>Demandes</dt>
    <dd class="applications">
      <table class="data-table">
        <thead>
          <tr>
            <th>Office</th>
            <th>Numéro de publication</th>
            <th>Dépôt</th>
            <th>Publication</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {#each patentMeta.applications as application, i (i)}
            <tr>
              <td>{application.office ? officeLabel(application.office) : ""}</td>
              <td class="number">
                {#if application.office && application.publication_number}
                  <a
                    href={espacenetUrl(application.office, application.publication_number)}
                    target="_blank"
                    rel="noopener noreferrer"
                    >{application.office}&#8239;{application.publication_number}</a
                  >
                {:else}
                  {application.publication_number ?? ""}
                {/if}
              </td>
              <td>{formatDate(application.application_date)}</td>
              <td>{formatDate(application.publication_date)}</td>
              <td class="status">
                {#if application.priority}<span class="tag">prioritaire</span>{/if}
                {#if application.granted}<span class="tag tag-success">délivré</span>{/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </dd>
  {/if}

  {#if patentMeta.cpc.length}
    <dt>Classification CPC</dt>
    <dd>
      <ClampedBlock maxHeight="calc(1.6em * 6)" moreLabel="Voir les {patentMeta.cpc.length} codes">
        <ul class="cpc">
          {#each patentMeta.cpc as cpc (cpc.code)}
            <li><code>{cpc.code}</code>{#if cpc.label}<span class="cpc-label">{cpc.label}</span>{/if}</li>
          {/each}
        </ul>
      </ClampedBlock>
    </dd>
  {/if}
</DetailTable>

<style>
  .applicants {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .persons {
    margin-top: 6px;
    color: var(--text-secondary);
  }
  .applications {
    padding: 0;
  }
  .applications .data-table th,
  .applications .data-table td {
    padding: 6px 12px;
  }
  .number {
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .status {
    white-space: nowrap;
  }
  .status .tag + .tag {
    margin-left: 4px;
  }
  .cpc {
    list-style: none;
    margin: 0;
    padding: 0;
    line-height: 1.6;
  }
  .cpc li {
    display: flex;
    align-items: baseline;
    gap: 10px;
    min-height: 1.6em;
  }
  .cpc code {
    flex: none;
    min-width: 9em;
    font-family: var(--mono);
    font-size: var(--fs-sm);
  }
  .cpc-label {
    color: var(--text-secondary);
  }
</style>
