export interface AgentSkill {
  id: string
  name: string
  description: string
  inputModes: string[]
  outputModes: string[]
  endpoint: string
  targetPlatforms?: string[]
}

export interface AgentCard {
  schemaVersion: string
  name: string
  description: string
  url: string
  version: string
  documentationUrl?: string
  capabilities: {
    streaming: boolean
    pushNotifications: boolean
    stateTransitionHistory: boolean
  }
  defaultInputModes: string[]
  defaultOutputModes: string[]
  skills: AgentSkill[]
}

export async function fetchAgentCard(agentId: 'jd-drafter' | 'job-poster'): Promise<AgentCard> {
  const res = await fetch(`/.well-known/${agentId}/agent-card.json`)
  if (!res.ok) throw new Error(`Failed to fetch agent card for ${agentId}`)
  return res.json()
}
