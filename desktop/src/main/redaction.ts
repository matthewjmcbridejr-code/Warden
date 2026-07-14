const patterns: Array<[RegExp, string]> = [
  [/sk-[A-Za-z0-9_-]{16,}/g, 'sk-[REDACTED]'],
  [/("(?:api[_-]?key|token|password|secret|authorization)"\s*:\s*)"[^"]*"/gi, '$1"[REDACTED]"'],
  [/(api[_-]?key|token|password|secret|authorization)\s*[:=]\s*[^\s]+/gi, '$1=[REDACTED]'],
  [/-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+ PRIVATE KEY-----/g, '[REDACTED PRIVATE KEY]'],
];
export function redact(value: string): string { return patterns.reduce((text, [pattern, replacement]) => text.replace(pattern, replacement), value); }
