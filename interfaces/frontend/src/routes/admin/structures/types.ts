/**
 * Types et helpers partagés par la page `admin/structures` et ses sous-composants.
 */

export interface Structure {
  id: number;
  code: string;
  name: string;
  acronym: string | null;
  type: string;
  ror_id: string | null;
  rnsr_id: string | null;
  hal_collection: string | null;
  api_ids: Record<string, string[]> | null;
}

export interface RelatedStructure {
  id: number;
  code: string;
  name: string;
  acronym: string | null;
  type: string;
  relation_id: number;
  relation_type: string;
}

export interface NameForm {
  id: number;
  form_text: string;
  is_word_boundary: boolean;
  is_excluding: boolean;
  requires_context_of: number[] | null;
}

export interface StructureDetail {
  structure: Structure;
  parents: RelatedStructure[];
  children: RelatedStructure[];
  forms: NameForm[];
}

export interface EditFormState {
  id: number;
  form_text: string;
  is_word_boundary: boolean;
  is_excluding: boolean;
}

export const API_SOURCES = ["openalex", "wos", "scanr", "theses"] as const;

export const API_SOURCE_LABELS: Record<string, string> = {
  openalex: "OpenAlex (institution lineage IDs)",
  wos: "WoS (Organization-Enhanced)",
  scanr: "ScanR (SIREN)",
  theses: "theses.fr (PPN IdRef)",
};

export function rorShortId(rorId: string): string {
  return rorId.replace("https://ror.org/", "");
}

export function rorFullUrl(rorId: string): string {
  if (rorId.startsWith("http")) return rorId;
  return "https://ror.org/" + rorId;
}

export function halCollectionUrl(code: string): string {
  return `https://hal.science/search/index/?qa%5BcollCode_s%5D%5B%5D=${code}`;
}
