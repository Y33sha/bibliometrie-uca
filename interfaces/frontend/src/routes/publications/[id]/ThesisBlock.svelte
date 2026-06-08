<script lang="ts">
  import { base } from "$app/paths";
  import {
    structLabel,
    type StructInfo,
    type ThesisAuthorship,
    type ThesisMeta,
  } from "./types";

  const {
    thesesAuth,
    thesisMeta,
    thesisAuthorStructures,
    structures,
  }: {
    thesesAuth: ThesisAuthorship[];
    thesisMeta: ThesisMeta | null | undefined;
    thesisAuthorStructures: number[];
    structures: Record<string, StructInfo>;
  } = $props();

  const ROLE_ORDER = [
    "author",
    "thesis_director",
    "rapporteur",
    "jury_president",
    "jury_member",
  ];

  const ROLE_LABELS: Record<string, string> = {
    author: "Auteur",
    thesis_director: "Direction",
    rapporteur: "Rapporteur",
    jury_president: "Président du jury",
    jury_member: "Examinateur",
  };
</script>

<div class="section thesis-section">
  <h2 class="section-title">Thèse</h2>
  <dl class="thesis-dl">
    {#each ROLE_ORDER as role}
      {@const people = thesesAuth.filter((a) => a.roles?.includes(role))}
      {#if people.length}
        <dt>{ROLE_LABELS[role] || role}</dt>
        <dd>
          {#each people as p, i}
            {#if p.person_id}
              <a href="{base}/persons/{p.person_id}">{p.full_name}</a>
            {:else}
              <span>{p.full_name}</span>
            {/if}
            {#if i < people.length - 1},&nbsp;{/if}
          {/each}
        </dd>
      {/if}
    {/each}

    {#if thesisMeta?.discipline}
      <dt>Discipline</dt>
      <dd>{thesisMeta.discipline}</dd>
    {/if}

    {#if thesisMeta?.date_inscription || thesisMeta?.date_soutenance}
      <dt>Dates</dt>
      <dd>
        {#if thesisMeta?.date_inscription}
          <span
            >Inscription en doctorat le {new Date(
              thesisMeta.date_inscription,
            ).toLocaleDateString("fr-FR")}</span
          >
        {/if}
        {#if thesisMeta?.date_inscription && thesisMeta?.date_soutenance}<br />{/if}
        {#if thesisMeta?.date_soutenance}
          <span
            >Soutenance le {new Date(thesisMeta.date_soutenance).toLocaleDateString(
              "fr-FR",
            )}</span
          >
        {/if}
      </dd>
    {/if}

    {#if thesisMeta?.ecoles_doctorales?.length}
      <dt>École(s) doctorale(s)</dt>
      <dd>
        {#each thesisMeta.ecoles_doctorales as ed, i}
          <span>{ed.nom}</span>{#if i < thesisMeta.ecoles_doctorales.length - 1},&nbsp;{/if}
        {/each}
      </dd>
    {/if}

    {#if thesisMeta?.partenaires?.length || thesisAuthorStructures.length}
      <dt>Partenaire(s) de recherche</dt>
      <dd>
        {#if thesisMeta?.partenaires?.length}
          {#each thesisMeta.partenaires as pr, i}
            <span>{pr.nom}{#if pr.type}&nbsp;({pr.type}){/if}</span>{#if i < thesisMeta.partenaires.length - 1},&nbsp;{/if}
          {/each}
        {/if}
        {#each thesisAuthorStructures as sid}
          <a href="{base}/laboratories/{sid}?tab=theses" class="struct-tag"
            >{structLabel(structures, sid)}</a
          >
        {/each}
      </dd>
    {/if}
  </dl>
</div>

<style>
  .section {
    margin-bottom: 16px;
  }
  .section-title {
    font-size: 1.05rem;
    font-weight: 600;
    margin: 0 0 8px;
  }
  .thesis-dl {
    display: grid;
    grid-template-columns: auto 1fr;
    font-size: 0.95rem;
    margin: 0;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
  }
  .thesis-dl dt,
  .thesis-dl dd {
    padding: 7px 12px;
    border-bottom: 1px solid #f0efec;
    margin: 0;
  }
  .thesis-dl dt {
    font-weight: 600;
    color: var(--muted);
    white-space: nowrap;
    background: #fafaf8;
    font-size: 0.85rem;
  }
  .thesis-dl a {
    color: var(--accent);
    text-decoration: none;
  }
  .thesis-dl a:hover {
    text-decoration: underline;
  }
  .struct-tag {
    display: inline-block;
    padding: 1px 6px;
    background: var(--accent-light);
    border-radius: 3px;
    font-size: 0.8rem;
    color: var(--accent);
    font-weight: 500;
    margin-right: 3px;
    text-decoration: none;
  }
  a.struct-tag:hover {
    background: #d0e3f4;
    text-decoration: none;
  }
</style>
