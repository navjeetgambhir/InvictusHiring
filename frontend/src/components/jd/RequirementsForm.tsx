import { useState } from 'react'
import { Plus, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import type { JobRequirements } from '@/api/jd'

interface Props {
  onSubmit: (req: JobRequirements) => void
  loading: boolean
}

function TagInput({
  label, tags, onChange, placeholder,
}: {
  label: string; tags: string[]; onChange: (tags: string[]) => void; placeholder: string
}) {
  const [input, setInput] = useState('')

  const add = () => {
    const val = input.trim()
    if (val && !tags.includes(val)) onChange([...tags, val])
    setInput('')
  }

  return (
    <div className="flex flex-col gap-2">
      <Label>{label}</Label>
      <div className="flex gap-2">
        <Input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), add())}
          placeholder={placeholder}
        />
        <Button type="button" variant="outline" size="icon" onClick={add}>
          <Plus className="h-4 w-4" />
        </Button>
      </div>
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {tags.map(tag => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 rounded-full bg-violet-50 border border-violet-200 px-2.5 py-0.5 text-xs text-violet-800"
            >
              {tag}
              <button type="button" onClick={() => onChange(tags.filter(t => t !== tag))}>
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export function RequirementsForm({ onSubmit, loading }: Props) {
  const [form, setForm] = useState<Omit<JobRequirements, 'required_skills' | 'nice_to_have_skills'>>({
    submitted_by: '',
    role: 'hm',
    title: '',
    department: '',
    location: '',
    salary_band: '',
    company_description: '',
    additional_context: '',
  })
  const [requiredSkills, setRequiredSkills] = useState<string[]>([])
  const [niceSkills, setNiceSkills] = useState<string[]>([])

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>): void =>
    setForm(prev => ({ ...prev, [k]: e.target.value }))

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!requiredSkills.length) return
    onSubmit({ ...form, required_skills: requiredSkills, nice_to_have_skills: niceSkills })
  }

  return (
    <Card className="w-full max-w-2xl mx-auto">
      <CardHeader>
        <CardTitle>New Job Requisition</CardTitle>
        <p className="text-sm text-stone-500">Fill in the requirements and the AI will draft the JD</p>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="flex flex-col gap-5">
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="submitted_by">Your Email</Label>
              <Input id="submitted_by" required value={form.submitted_by} onChange={set('submitted_by')} placeholder="you@company.com" />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="role">Your Role</Label>
              <select
                id="role"
                value={form.role}
                onChange={set('role')}
                className="flex h-9 w-full rounded-lg border border-stone-200 bg-white px-3 py-1 text-sm text-stone-900 focus:outline-none focus:ring-2 focus:ring-violet-500"
              >
                <option value="hm">Hiring Manager</option>
                <option value="hr">HR</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="title">Job Title</Label>
              <Input id="title" required value={form.title} onChange={set('title')} placeholder="e.g. Senior Backend Engineer" />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="department">Department</Label>
              <Input id="department" required value={form.department} onChange={set('department')} placeholder="e.g. Engineering" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="location">Location</Label>
              <Input id="location" required value={form.location} onChange={set('location')} placeholder="e.g. London, UK" />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="salary_band">Salary Band</Label>
              <Input id="salary_band" required value={form.salary_band} onChange={set('salary_band')} placeholder="e.g. £60,000 – £80,000" />
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="company_description">Company Description</Label>
            <Textarea id="company_description" required rows={3} value={form.company_description} onChange={set('company_description')} placeholder="Brief description of the company…" />
          </div>

          <TagInput label="Required Skills *" tags={requiredSkills} onChange={setRequiredSkills} placeholder="Type a skill and press Enter" />
          <TagInput label="Nice-to-Have Skills" tags={niceSkills} onChange={setNiceSkills} placeholder="Type a skill and press Enter" />

          <div className="flex flex-col gap-2">
            <Label htmlFor="additional_context">Additional Context (optional)</Label>
            <Textarea id="additional_context" rows={2} value={form.additional_context} onChange={set('additional_context')} placeholder="Any extra requirements or notes for the AI…" />
          </div>

          <Button type="submit" disabled={loading || !requiredSkills.length} className="w-full">
            {loading ? 'Generating Draft…' : 'Generate JD Draft'}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}