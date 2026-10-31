export type QrStatus = 'PAUSED' | 'IN_PROGRESS' | 'LIVE' | 'ESCALATED'

export interface Reason {
  label: string
  detail: string
}

export interface MuleRisk {
  score: number
  flagged: boolean
  top_features: { feature: string; label: string; detail: string; contribution: number }[]
}

export interface QueueItem {
  rank: number
  merchant_id: string
  shop_name: string
  owner_name: string
  category: string
  locality: string
  city: string
  qr_status: QrStatus
  route: string
  current_step: string | null
  monthly_gmv: number
  priority_score: number
  reasons: Reason[]
  mule_risk: MuleRisk
}

export interface Stats {
  qr_status: Record<QrStatus, number>
  total: number
  open_review_cases: number
}

export interface AuditItem {
  id: number
  ts: string
  merchant_id: string
  shop_name?: string | null
  actor: string
  action: string
  summary: string | null
  payload: Record<string, any>
}

export interface Waiting {
  waiting_for: 'shopkeeper' | 'field_employee' | 'human_review'
  doc_type?: string
  visit_id?: number
  case_id?: number
}

export interface JourneyView {
  merchant_id: string
  shop_name: string
  qr_status: QrStatus
  step: string | null
  started: boolean
  waiting_for: Waiting | null
  visit_slot: string | null
  assigned_employee: string | null
  attempts: Record<string, number>
  escalation_reason: string | null
  state: Record<string, any>
  chain: { ok: boolean; broken_at: number | null; checked: number }
  timeline: AuditItem[]
}

export interface Profile {
  id: string
  shop_name: string
  owner_name: string
  category: string
  city: string
  locality: string
  lat: number
  lng: number
  turnover_band: string
  in_ckycr: boolean
  qr_status: QrStatus
  has_soundbox: boolean
  monthly_gmv: number
  has_active_loan: boolean
  loan_outstanding: number
  open_hours: { open_hour: number; close_hour: number }
  docs_status: Record<string, string>
  priority_score: number
  reasons: Reason[]
  mule_risk: MuleRisk
  route: string
  current_step: string | null
}

export interface RequirementResult {
  requirement: string
  passed: boolean
  evidence_ref: string | null
  checked_at: string
  detail: string
}

export interface Compliance {
  merchant_id: string
  route: string
  results: RequirementResult[]
  compliant: boolean
  review_reason: string | null
}

export interface DocumentRow {
  id: number
  merchant_id: string
  doc_type: string
  extracted_fields: Record<string, any>
  quality_metrics: Record<string, any>
  decision: 'ACCEPTED' | 'REJECTED'
  reason: string | null
  attempt_no: number
  created_at: string
  image_url: string | null
}

export interface ChatMessage {
  id: number
  merchant_id: string
  ts: string
  sender: 'agent' | 'shopkeeper'
  channel: 'WHATSAPP' | 'IVR'
  text_hi: string
  text_en: string
  attachment: string | null
  meta: Record<string, any>
}

export interface Specimen {
  name: string
  label: string
  doc_type: string | null
  use: 'shop' | 'field'
  url: string
}

export interface Employee {
  id: string
  name: string
  home_base: string
}

export interface VisitRow {
  id: number
  merchant_id: string
  employee_id: string
  employee_name: string
  scheduled_at: string
  route_order: number
  completed_at: string | null
  confirmed_by: string | null
  shop_name: string
  owner_name: string
  locality: string
  city: string
  lat: number
  lng: number
  category: string
}

export interface ReviewCase {
  id: number
  merchant_id: string
  shop_name: string | null
  reason: string
  evidence: Record<string, any>
  status: 'OPEN' | 'DECIDED'
  decided_by: string | null
  decision: string | null
  note: string | null
  created_at: string
}
