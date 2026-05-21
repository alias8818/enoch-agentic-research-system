import type { MovementDiagnosis } from '../types'

export function resolveMovementPanelCopy(diagnosis: MovementDiagnosis): { title: string; subtitle: string } {
  const status = diagnosis.status || 'unknown'

  if (status === 'ready') {
    return {
      title: 'What is moving now?',
      subtitle: 'Active lanes and normal progress. The frontend renders backend movement truth.',
    }
  }

  if (status === 'actionable') {
    return {
      title: 'What can I do next?',
      subtitle: 'Safe operator work is available before lane controls.',
    }
  }

  return {
    title: 'Why no work is moving?',
    subtitle: 'Backend-diagnosed blocker before lane controls. The frontend does not infer queue truth.',
  }
}
