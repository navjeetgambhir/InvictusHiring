const API = '/api'

export interface JobListing {
  session_id: string
  title: string
  department: string
  location: string
  salary_band: string
  required_skills: string[]
  nice_to_have_skills: string[]
  company_description: string
  posted_at: string
  expires_at: string | null
  max_applications: number | null
  application_count: number
  is_accepting: boolean
  content: string | null
}

export interface ApplicationPayload {
  name: string
  email: string
  phone?: string
  cover_letter?: string
  cover_letter_file?: File
  cv?: File
}

export type ScreeningRecommendation = 'strong_match' | 'good_match' | 'partial_match' | 'poor_match'

export type InterviewFormat = 'phone' | 'video' | 'in_person'
export type InterviewStatus = 'scheduled' | 'completed' | 'cancelled'

export interface CandidateApplicationRecord {
  id: string
  name: string
  email: string
  phone: string | null
  cover_letter: string | null
  cover_letter_filename: string | null
  cv_filename: string | null
  has_cv: boolean
  screening_status: 'pending' | 'screened' | 'failed'
  screening_score: number | null
  screening_summary: string | null
  screening_strengths: string[] | null
  screening_gaps: string[] | null
  screening_recommendation: ScreeningRecommendation | null
  applied_at: string
  shortlisted: boolean
  interview_status: InterviewStatus | null
  interview_scheduled_at: string | null
  interview_format: InterviewFormat | null
  interview_location: string | null
  interview_notes: string | null
}

export interface InterviewInvitation {
  id: string
  application_id: string
  email_subject: string
  email_body: string
  interview_questions: string[]
  final_recipient: string | null
  final_subject: string | null
  final_body: string | null
  email_approved_at: string | null
  email_sent_at: string | null
  email_send_error: string | null
  created_at: string
}

export interface ApproveEmailPayload {
  recipient: string
  subject: string
  body: string
}

export interface InterviewRecord {
  id: string
  name: string
  email: string
  phone: string | null
  screening_score: number | null
  screening_recommendation: ScreeningRecommendation | null
  screening_summary: string | null
  shortlisted: boolean
  interview_status: InterviewStatus | null
  interview_scheduled_at: string | null
  interview_format: InterviewFormat | null
  interview_location: string | null
  interview_notes: string | null
  invitation: InterviewInvitation | null
}

export interface SchedulePayload {
  scheduled_at: string    // ISO8601
  format: InterviewFormat
  location?: string
  notes?: string
  duration_minutes?: number
}

export type FeedbackRecommendation = 'strong_hire' | 'hire' | 'no_hire' | 'strong_no_hire'

export interface FeedbackPayload {
  round?: number
  overall_rating: number           // 1–5
  technical_score?: number | null
  communication_score?: number | null
  cultural_fit_score?: number | null
  strengths?: string
  concerns?: string
  recommendation: FeedbackRecommendation
}

export interface InterviewFeedback {
  id: string
  submitted_by: string
  round: number
  overall_rating: number
  technical_score: number | null
  communication_score: number | null
  cultural_fit_score: number | null
  strengths: string | null
  concerns: string | null
  recommendation: FeedbackRecommendation
  created_at: string
}

export interface JobsPage {
  jobs: JobListing[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export async function fetchJobs(page = 1, pageSize = 10): Promise<JobsPage> {
  const res = await fetch(`${API}/candidates/jobs?page=${page}&page_size=${pageSize}`)
  if (!res.ok) throw new Error('Failed to load jobs')
  return res.json()
}

export async function fetchJob(sessionId: string): Promise<JobListing> {
  const res = await fetch(`${API}/candidates/jobs/${sessionId}`)
  if (!res.ok) throw new Error('Job not found')
  return res.json()
}

export async function submitApplication(sessionId: string, payload: ApplicationPayload): Promise<void> {
  const form = new FormData()
  form.append('name', payload.name)
  form.append('email', payload.email)
  form.append('phone', payload.phone ?? '')
  form.append('cover_letter', payload.cover_letter ?? '')
  if (payload.cover_letter_file) form.append('cover_letter_file', payload.cover_letter_file)
  if (payload.cv) form.append('cv', payload.cv)

  const res = await fetch(`${API}/candidates/apply/${sessionId}`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ?? 'Failed to submit application')
  }
}

export async function fetchApplications(sessionId: string, token: string): Promise<CandidateApplicationRecord[]> {
  const res = await fetch(`${API}/candidates/applications/${sessionId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to load applications')
  return res.json()
}

export function cvDownloadUrl(sessionId: string, applicationId: string): string {
  return `${API}/candidates/applications/${sessionId}/cv/${applicationId}`
}

export async function toggleShortlist(
  applicationId: string,
  token: string,
): Promise<{ application_id: string; shortlisted: boolean }> {
  const res = await fetch(`${API}/interviews/shortlist/${applicationId}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to update shortlist status')
  return res.json()
}

export async function generateInvitation(
  applicationId: string,
  token: string,
): Promise<InterviewInvitation> {
  const res = await fetch(`${API}/interviews/generate/${applicationId}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ?? 'Failed to generate invitation')
  }
  return res.json()
}


export async function scheduleInterview(
  applicationId: string,
  payload: SchedulePayload,
  token: string,
): Promise<{ application_id: string; interview_status: string; interview_scheduled_at: string; interview_format: InterviewFormat; interview_location: string | null }> {
  const res = await fetch(`${API}/interviews/schedule/${applicationId}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ?? 'Failed to schedule interview')
  }
  return res.json()
}

export async function fetchSessionInterviews(
  sessionId: string,
  token: string,
): Promise<InterviewRecord[]> {
  const res = await fetch(`${API}/interviews/session/${sessionId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to load interview records')
  return res.json()
}

export function icsDownloadUrl(applicationId: string): string {
  return `${API}/interviews/ics/${applicationId}`
}

export async function cancelInterview(applicationId: string, token: string): Promise<void> {
  const res = await fetch(`${API}/interviews/cancel/${applicationId}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ?? 'Failed to cancel interview')
  }
}

export async function rescheduleInterview(
  applicationId: string,
  payload: SchedulePayload,
  token: string,
): Promise<{ interview_scheduled_at: string; interview_format: InterviewFormat; interview_location: string | null }> {
  const res = await fetch(`${API}/interviews/reschedule/${applicationId}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ?? 'Failed to reschedule interview')
  }
  return res.json()
}

export async function submitFeedback(
  applicationId: string,
  payload: FeedbackPayload,
  token: string,
): Promise<InterviewFeedback> {
  const res = await fetch(`${API}/interviews/feedback/${applicationId}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ?? 'Failed to submit feedback')
  }
  return res.json()
}

export async function fetchFeedback(applicationId: string, token: string): Promise<InterviewFeedback[]> {
  const res = await fetch(`${API}/interviews/feedback/${applicationId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to load feedback')
  return res.json()
}

export async function approveAndSendEmail(
  invitationId: string,
  payload: ApproveEmailPayload,
  token: string,
): Promise<InterviewInvitation & { email_sent: boolean; send_error: string | null }> {
  const res = await fetch(`${API}/interviews/approve-email/${invitationId}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ?? 'Failed to approve invitation')
  }
  return res.json()
}