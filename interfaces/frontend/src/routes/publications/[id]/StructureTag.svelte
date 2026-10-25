<script lang="ts">
  import { resolve } from "$app/paths";
  import { structIsLabo, structLabelById, type StructInfo } from "#lib/structureLabels.js";

  // Tag d'une structure liée à une publication : lien vers la fiche labo si c'en est un, sinon span non cliquable (établissement, partenaires…).
  // `tab` : onglet ciblé sur la fiche labo (ex. "theses").
  let {
    structures,
    sid,
    tab,
  }: {
    structures: Record<string, StructInfo>;
    sid: number;
    tab?: string;
  } = $props();
</script>

{#if structIsLabo(structures, sid)}
  <a href={resolve(`laboratories/${sid}${tab ? `?tab=${tab}` : ''}`)} class="struct-tag"
    >{structLabelById(structures, sid)}</a
  >
{:else}
  <span class="struct-tag">{structLabelById(structures, sid)}</span>
{/if}

<style>
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
