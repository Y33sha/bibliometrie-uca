<script lang="ts">
  import { asset } from "$app/paths";
  import type { AssetPath } from "$app/types";
  import { identifierTypeLabel } from "#lib/labels.js";
  import { halPersonUrl } from "#lib/utils.js";

  let {
    id_type,
    id_value,
    confirmed = true,
  }: {
    id_type: string;
    id_value: string;
    /** Icône en pleine opacité si vrai, atténuée sinon. */
    confirmed?: boolean;
  } = $props();

  const META: Record<string, { url: (v: string) => string; icon: AssetPath; cls: string }> = {
    orcid: {
      url: (v) => `https://orcid.org/${v}`,
      icon: "icons/orcid.ico",
      cls: "id-orcid",
    },
    idhal: {
      url: (v) => `https://hal.science/search/index/?q=%2A&authIdHal_s=${v}`,
      icon: "icons/hal.ico",
      cls: "id-hal",
    },
    idref: {
      url: (v) => `https://www.idref.fr/${v}`,
      icon: "icons/idref.png",
      cls: "id-idref",
    },
    hal_person_id: {
      url: halPersonUrl,
      icon: "icons/hal.ico",
      cls: "id-hal",
    },
  };

  const meta = $derived(META[id_type] ? { ...META[id_type], label: identifierTypeLabel(id_type) } : null);
</script>

{#if meta}
  <a
    class="id-icon {meta.cls}"
    class:id-confirmed={confirmed}
    href={meta.url(id_value)}
    target="_blank"
    rel="noopener"
    title="{meta.label} : {id_value}"
  >
    <img src={asset(meta.icon)} alt={meta.label} />
  </a>
{:else}
  <span class="id-icon id-placeholder"></span>
{/if}
