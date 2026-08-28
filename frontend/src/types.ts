export type FieldStatus = 'auto_accept' | 'review' | 'reject'

export interface FieldResult {
  name: string
  value: string | number | null
  confidence: number
  status: FieldStatus
  self_reported: number
  agreement: number
  rules: number
  rule_notes: string[]
}

export interface LineItem {
  description: string | null
  quantity: number | null
  unit_price: number | null
  amount: number | null
  hsn_sac: string | null
}

export interface CallTiming {
  pass_index: number
  provider: string
  model: string
  latency_ms: number
  wasted_ms: number
  attempts: number
  prompt_tokens: number | null
  completion_tokens: number | null
  cost_usd: number | null          // null = provider reported no price
  cost_is_estimated: boolean
}

/* `total_usd` only means something together with `known`. When a pass reported
   no price, the sum is a floor rather than the answer — so unknown, free, and
   priced are three distinct states, never collapsed into one zero. */
export interface Cost {
  total_usd: number
  prompt_tokens: number
  completion_tokens: number
  known: boolean
  is_estimated: boolean
  free: boolean
}

/* The phases deliberately do NOT sum to total_ms — the extraction passes run
   concurrently, so llm_ms is the wall-clock span of all of them while each
   call's latency_ms is its own (overlapping) request. */
export interface Timing {
  parse_ms: number
  llm_ms: number
  scoring_ms: number
  db_ms: number
  total_ms: number
  calls: CallTiming[]
}

export interface ExtractionResult {
  document_id: string | null
  filename: string
  source: string
  provider: string
  fields: FieldResult[]
  line_items: LineItem[]
  overall_confidence: number
  auto_accept_rate: number
  raw_text_preview: string
  warnings: string[]
  timing?: Timing        // optional: records saved before timing existed have none
  cost?: Cost
}

export interface Health {
  status: string
  llm_providers: string[]
  supabase: { enabled: boolean; detail: string }
  thresholds: { auto_accept: number; review: number }
  weights: { self_reported: number; agreement: number; rules: number }
  passes: number
}

export interface DocSummary {
  id: string
  filename: string
  source: string
  provider: string
  overall_confidence: number
  auto_accept_rate: number
  created_at: string
  total_ms?: number | null   // absent on records saved before timing existed
  cost_usd?: number | null   // null = unknown or not reported, NOT free
}

export type BatchStatus = 'queued' | 'processing' | 'done' | 'error'

/* One entry in the desktop document stack. A document is either something
   uploaded in this session (origin 'batch', may still be in flight) or a record
   pulled back out of Supabase (origin 'history', always finished). The stack
   and the tab rail treat both identically, so they need one shape. `id` is the
   stack identity; `docId` is the Supabase row, which a live upload only gains
   once it has been saved. */
export interface DeskDoc {
  id: string
  filename: string
  status: BatchStatus
  origin: 'batch' | 'history'
  docId?: string | null
  result?: ExtractionResult
  error?: string
  createdAt?: string
}

export interface BatchItem {
  id: string
  file: File
  status: BatchStatus
  result?: ExtractionResult
  error?: string
}

export const FIELD_LABELS: Record<string, string> = {
  vendor_name: 'Vendor name',
  vendor_gstin: 'Vendor GSTIN',
  vendor_address: 'Vendor address',
  buyer_name: 'Buyer name',
  buyer_gstin: 'Buyer GSTIN',
  invoice_number: 'Invoice number',
  invoice_date: 'Invoice date',
  due_date: 'Due date',
  currency: 'Currency',
  subtotal: 'Subtotal',
  tax_amount: 'Tax amount',
  total_amount: 'Total amount',
}
