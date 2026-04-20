/**
 * Types partagés par la page `admin/persons` et ses sous-composants.
 */

export interface PersonStats {
  total_persons: number;
  linked_persons: number;
  linked_authors: number;
  departments: number;
}

export interface LinkedAuthor {
  id: number;
  source: string;
  full_name: string;
  orcid?: string;
  idhal?: string;
}

export interface PersonIdentifier {
  id: number;
  id_type: string;
  id_value: string;
  source: string;
  status: "pending" | "confirmed" | "rejected";
}

export interface NameForm {
  name_form: string;
  ambiguous: boolean;
}

export interface Person {
  id: number;
  first_name: string;
  last_name: string;
  department_name?: string;
  role_title?: string;
  start_date?: string;
  end_date?: string;
  has_rh?: boolean;
  rejected?: boolean;
  pub_count?: number;
  uca_pub_count?: number;
  linked_authors?: LinkedAuthor[];
  identifiers?: PersonIdentifier[];
  name_forms?: NameForm[];
}

export interface PersonListResponse {
  total: number;
  page: number;
  pages: number;
  persons: Person[];
}

export interface DetachAuthorship {
  source: string;
  authorship_id: number;
  pub_id: number;
  title: string;
  pub_year: number | null;
  doi: string | null;
  checked: boolean;
}

export interface OtherPerson {
  id: number;
  first_name: string;
  last_name: string;
  department_name: string | null;
  has_rh: boolean;
}

export interface PersonSearchResult {
  id: number;
  first_name: string;
  last_name: string;
  department_name: string | null;
  has_rh: boolean;
}

export interface EditNameState {
  personId: number;
  lastName: string;
  firstName: string;
  rejected: boolean;
}

export interface DetachModalState {
  personId: number;
  nameForm: string;
  authorships: DetachAuthorship[];
  otherPersons: OtherPerson[];
  loading: boolean;
}

export interface IdFormState {
  id_type: string;
  id_value: string;
  error: string;
}
