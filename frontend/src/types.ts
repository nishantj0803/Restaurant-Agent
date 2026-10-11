export type Status = "supported" | "confirmation" | "excluded";

export interface Reference {
  source_id: string;
  quote: string;
}

export interface Source {
  id: string;
  url: string;
  title: string;
  coverage: "search_excerpt" | "extracted_page" | "pdf";
  retrieved_at: string;
  published_date: string | null;
}

export interface Preferences {
  city: string;
  country: string | null;
  meal: string;
  visit_date: string | null;
  budget: number | null;
  currency: string | null;
  budget_operator: "lt" | "lte";
  vegetarian: boolean;
  excluded_ingredients: string[];
  location_preference: string;
  review_concerns: string[];
  assumptions: string[];
}

export interface Dish {
  original_name: string;
  english_name: string;
  description: string;
  ingredients?: string[];
  ingredient_refs?: Reference[];
  price: number | null;
  currency: string | null;
  price_kind: "exact" | "from" | "unknown";
  menu_category: "regular" | "set_menu" | "special" | "unknown";
  vegetarian: "yes" | "no" | "unknown";
  vegan: "yes" | "no" | "unknown";
  menu_refs: Reference[];
  dietary_refs: Reference[];
  price_refs: Reference[];
  exclusions?: {
    ingredient: string;
    status: "absent" | "present" | "unknown";
    refs: Reference[];
  }[];
  status: Status;
  reasons: string[];
}

export interface Review {
  polarity: "positive" | "negative" | "mixed";
  aspect: "food" | "service" | "dietary" | "value" | "other";
  summary: string;
  source_type: "customer_review" | "editorial" | "testimonial" | "unknown";
  review_date: string | null;
  refs: Reference[];
}

export interface Recommendation {
  name: string;
  website: string;
  menu_url: string | null;
  address: string;
  location_summary: string;
  location_refs: Reference[];
  status: Status;
  explanation: string;
  dishes: Dish[];
  reviews: Review[];
  availability_summary: string;
  availability_refs: Reference[];
  gaps: string[];
}

export interface Usage {
  searches: number;
  documents: number;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  elapsed_seconds: number;
}

export interface Result {
  preferences: Preferences;
  recommendations: Recommendation[];
  excluded: Recommendation[];
  sources: Source[];
  usage: Usage;
  warnings: string[];
}

export interface ResearchEvent {
  type: string;
  stage: string;
  message: string;
  timestamp: string;
  data: {
    preferences?: Preferences;
    source?: Source;
    candidate?: { name: string; reason: string; website: string };
    recommendation?: Recommendation;
    result?: Result;
    restaurant?: string;
    session_id?: string;
    refs?: Reference[];
    sources?: Source[];
  };
}
