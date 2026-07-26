import type { NormalizedRunEvent, ProviderAuthReport, RunApproval, StructuredProviderId } from '../shared/types';

/** Terminology table — Simple Mode surfaces only the right-hand column; Developer Mode may show either. */
export const TERMINOLOGY: Record<string, string> = {
  project: 'Project',
  run: 'Task',
  provider: 'AI',
  evidence: 'Result details',
  proof: 'Work history',
  diff: 'What changed',
  tests: 'Checks',
  handoff: 'Continue with another AI',
  worktree: 'Safe workspace',
  commit: 'Saved version',
  memory: 'Project memory',
  approvalPolicy: 'When Warden should ask',
};

export const PROVIDER_LABELS: Record<StructuredProviderId, string> = { codex: 'Codex', claude: 'Claude', gemini: 'Gemini', grok: 'Grok Build' };
export const PROVIDER_SUBSCRIPTION_LABELS: Record<StructuredProviderId, string> = { codex: 'ChatGPT Plus', claude: 'Claude Pro', gemini: 'your Google account', grok: 'your Grok subscription' };

export function recommendedProviderLine(provider: StructuredProviderId): string {
  return `Recommended: ${PROVIDER_LABELS[provider]} through ${PROVIDER_SUBSCRIPTION_LABELS[provider]}`;
}

export function connectedThroughLine(provider: StructuredProviderId): string {
  return `Connected through ${PROVIDER_SUBSCRIPTION_LABELS[provider]}`;
}

/** A plain-language line for one run event. Falls back to a generic "working" line for anything unmapped. */
export function translateEvent(event: NormalizedRunEvent): string {
  switch (event.type) {
    case 'run.started':
      return 'Understanding your project';
    case 'command.started': {
      const command = String(event.payload.command || '');
      if (/^(npm|pnpm|yarn)\s+(install|add)/.test(command)) return 'Adding a package your project needs';
      if (/^(npm|pnpm|yarn)\s+(run\s+)?(build|test)/.test(command)) return 'Checking that everything still works';
      if (/^git\s/.test(command)) return 'Recording progress';
      return 'Running a step to make the change';
    }
    case 'command.completed': {
      const exitCode = event.payload.exitCode;
      return exitCode === 0 ? 'That step finished successfully' : 'That step ran into a problem';
    }
    case 'file.changed':
      return 'Updating your project’s files';
    case 'tool.started':
      return 'Reviewing your project';
    case 'tool.completed':
      return 'Finished reviewing that part';
    case 'test.completed':
      return 'Checking that it still works';
    case 'approval.requested':
      return 'Waiting for your approval';
    case 'run.completed':
      return 'Preparing your result';
    case 'run.failed':
      return 'Something went wrong';
    case 'run.cancelled':
      return 'Stopped';
    default:
      return 'Working on it';
  }
}

export interface ApprovalCopy { title: string; why?: string; source?: string }

/** Consumer-language framing for an approval request. "Technical details" (the raw approval.detail/providerPayload) stays available separately. */
export function translateApproval(approval: Pick<RunApproval, 'title' | 'detail'>): ApprovalCopy {
  const detail = approval.detail || '';

  const packageMatch = detail.match(/\b(npm|pnpm|yarn)\s+(?:install|add)\s+(?:--save(?:-dev)?\s+)?([^\s]+)/);
  if (packageMatch) {
    return { title: `Wants to add a package to this project`, why: `Needed to continue the task`, source: packageMatch[1] === 'npm' ? 'npm' : packageMatch[1] };
  }

  if (/\brm\s+-r?f?\b|unlink|delete/i.test(detail)) {
    return { title: 'Wants to delete one or more files', why: 'No longer needed for this task' };
  }

  if (/curl|wget|fetch\(|https?:\/\//i.test(detail) && /\b(GET|POST|curl|wget)\b/i.test(detail)) {
    return { title: 'Wants to access the internet', why: 'Needed to complete the task' };
  }

  if (/\bgit\s+push\b/.test(detail)) {
    return { title: 'Wants to publish this project remotely', why: 'Requested as part of the task' };
  }

  return { title: approval.title || 'Wants to make a change', why: undefined };
}

export function providerOnboardingCopy(provider: StructuredProviderId, report?: ProviderAuthReport): { headline: string; body: string; action: 'connect' | 'ready' | 'wait' } {
  if (!report || report.state === 'disconnected') return { headline: `Connect ${PROVIDER_LABELS[provider]} to start building`, body: `Uses ${PROVIDER_SUBSCRIPTION_LABELS[provider]}`, action: 'connect' };
  if (report.state === 'installed_not_authenticated' || report.state === 'unknown_entitlement') return { headline: `Sign in to ${PROVIDER_LABELS[provider]}`, body: report.detail, action: 'connect' };
  if (report.state === 'subscription_authenticated') return { headline: recommendedProviderLine(provider), body: connectedThroughLine(provider), action: 'ready' };
  return { headline: `${PROVIDER_LABELS[provider]} isn’t ready yet`, body: report.detail, action: 'wait' };
}
