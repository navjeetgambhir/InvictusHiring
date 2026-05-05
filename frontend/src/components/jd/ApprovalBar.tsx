import { useState } from 'react'
import { ThumbsUp, ThumbsDown, CheckCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import type { SessionStatus } from '@/hooks/useJDSession'

interface Props {
  status: SessionStatus
  onApprove: () => void
  onReject: (feedback: string) => void
}

export function ApprovalBar({ status, onApprove, onReject }: Props) {
  const [showFeedback, setShowFeedback] = useState(false)
  const [feedback, setFeedback] = useState('')

  if (status === 'approved') {
    return (
      <div className="flex items-center justify-center gap-2 rounded-xl border border-violet-200 bg-violet-50 px-4 py-3">
        <CheckCircle className="h-4 w-4 text-violet-600" />
        <span className="text-sm font-medium text-violet-800">JD Approved — posting to job portals</span>
      </div>
    )
  }

  if (status !== 'pending_approval') return null

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-violet-200 bg-white p-4 shadow-sm">
      {!showFeedback ? (
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-stone-600">Review the draft above and take action</p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setShowFeedback(true)}>
              <ThumbsDown className="h-3.5 w-3.5" />
              Reject & Revise
            </Button>
            <Button size="sm" onClick={onApprove}>
              <ThumbsUp className="h-3.5 w-3.5" />
              Approve JD
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-sm font-medium text-stone-700">What needs to change?</p>
          <Textarea
            value={feedback}
            onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setFeedback(e.target.value)}
            placeholder="e.g. Make the tone more formal, add a remote-first clause, expand the responsibilities section…"
            rows={3}
            autoFocus
          />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => { setShowFeedback(false); setFeedback('') }}>
              Cancel
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!feedback.trim()}
              onClick={() => { onReject(feedback); setShowFeedback(false); setFeedback('') }}
            >
              Submit Feedback
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}