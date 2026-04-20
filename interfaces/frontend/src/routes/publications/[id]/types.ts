/**
 * Types partagés par la page `publications/[id]` et ses sous-composants.
 * Co-localisés avec la route car ils ne sont pas réutilisés ailleurs.
 */

export interface PubDetail {
  id: number;
  title: string;
  pub_year: number | null;
  doi: string | null;
  doc_type: string | null;
  oa_status: string | null;
  language: string | null;
  container_title: string | null;
  abstract: string | null;
  journal_id: number | null;
  journal_title: string | null;
  issn: string | null;
  eissn: string | null;
  journal_predatory: boolean | null;
  apc_amount: number | null;
  apc_currency: string | null;
  oa_model: string | null;
  publisher_id: number | null;
  publisher_name: string | null;
  publisher_predatory: boolean | null;
}

export interface Source {
  source: string;
  source_id: string;
  doi: string | null;
  hal_collections: string[] | null;
  countries: string[] | null;
}

export interface Authorship {
  author_position: number;
  person_id: number;
  last_name: string;
  first_name: string;
  in_perimeter: boolean;
  is_corresponding: boolean | null;
  structure_ids: number[] | null;
  source_hal: boolean;
  source_openalex: boolean;
  source_wos: boolean;
}

export interface SourceAuthorship {
  id: number;
  author_position: number;
  full_name: string;
  person_id: number | null;
  in_perimeter: boolean;
  structure_ids: number[] | null;
  raw_affiliation: string | null;
  excluded: boolean;
  countries: string[] | null;
}

export interface StructInfo {
  acronym: string | null;
  name: string;
  type: string;
}

export interface ThesisAuthorship {
  id: number;
  author_position: number | null;
  full_name: string;
  person_id: number | null;
  roles: string[];
  in_perimeter: boolean;
}

export interface ThesisMeta {
  discipline: string | null;
  ecoles_doctorales: { nom: string; ppn?: string }[] | null;
  partenaires: { nom: string; type?: string }[] | null;
  date_soutenance: string | null;
  date_inscription: string | null;
}

export interface PubResponse {
  publication: PubDetail;
  sources: Source[];
  authorships: Authorship[];
  hal_authorships: SourceAuthorship[];
  openalex_authorships: SourceAuthorship[];
  wos_authorships: SourceAuthorship[];
  theses_authorships: ThesisAuthorship[];
  thesis_meta: ThesisMeta | null;
  structures: Record<string, StructInfo>;
}

export interface SourceRow {
  position: number;
  hal: SourceAuthorship | null;
  oa: SourceAuthorship | null;
  wos: SourceAuthorship | null;
  conflict: boolean;
}

/** Nom d'une structure via son id (acronyme si dispo, sinon nom, sinon `#id`). */
export function structLabel(structures: Record<string, StructInfo>, id: number): string {
  const s = structures[String(id)];
  return s ? s.acronym || s.name : `#${id}`;
}

export function structIsLabo(structures: Record<string, StructInfo>, id: number): boolean {
  return structures[String(id)]?.type === "labo";
}

/** Tooltip résumé des affiliations brutes + structures identifiées. */
export function structsTooltip(
  a: SourceAuthorship,
  structures: Record<string, StructInfo>,
): string {
  const parts: string[] = [];
  if (a.raw_affiliation) {
    parts.push(`<em>${a.raw_affiliation}</em>`);
  }
  if (a.structure_ids?.length) {
    parts.push(
      `Structures identifiées : ${a.structure_ids.map((sid) => structLabel(structures, sid)).join(", ")}`,
    );
  }
  return parts.join("<br>") || "";
}
