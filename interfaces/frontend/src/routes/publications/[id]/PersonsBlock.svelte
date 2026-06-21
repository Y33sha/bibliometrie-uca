<script lang="ts">
  import { base } from "$app/paths";
  import SectionLabel from "./SectionLabel.svelte";
  import { titleCase } from "$lib/utils";
  import type { Authorship } from "./types";

  let { authorships }: { authorships: Authorship[] } = $props();

  // Une personne par lien, dédupliquée (un même `person_id` peut apparaître sur deux signatures),
  // ordre d'apparition conservé.
  const persons = $derived.by(() => {
    const seen = new Set<number>();
    const out: Authorship[] = [];
    for (const a of authorships) {
      if (a.person_id != null && !seen.has(a.person_id)) {
        seen.add(a.person_id);
        out.push(a);
      }
    }
    return out;
  });

  function personName(a: Authorship): string {
    return `${titleCase(a.first_name)} ${titleCase(a.last_name)}`.trim();
  }
</script>

{#if persons.length > 0}
  <div class="detail-section">
    <SectionLabel icon="person" text="Personnes liées" count={persons.length} />
    <div class="detail-tags">
      {#each persons as a (a.person_id)}
        <a href="{base}/persons/{a.person_id}">
          {personName(a)}
          {#if a.has_rh}
            <svg
              class="rh-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2.5"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-label="Base RH"
            >
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
              <polyline points="22 4 12 14.01 9 11.01" />
            </svg>
          {/if}
        </a>
      {/each}
    </div>
  </div>
{/if}

<style>
  .rh-icon {
    width: 13px;
    height: 13px;
    color: var(--accent);
    flex-shrink: 0;
  }
</style>
