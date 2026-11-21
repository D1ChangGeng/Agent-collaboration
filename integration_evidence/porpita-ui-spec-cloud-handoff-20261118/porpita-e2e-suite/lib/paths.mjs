import { execFileSync, spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const LIB_DIR = path.dirname(fileURLToPath(import.meta.url))
export const SUITE_DIR = path.resolve(LIB_DIR, '..')

function isAgentCollabCheckout(dir) {
  return (
    existsSync(path.join(dir, 'runtime', 'communication_http.py')) &&
    existsSync(path.join(dir, 'docs', 'client', 'porpita-ui-spec'))
  )
}

function findAncestorDir(startDir, predicate) {
  let current = path.resolve(startDir)
  while (true) {
    if (predicate(current)) return current
    const parent = path.dirname(current)
    if (parent === current) return null
    current = parent
  }
}

function dedupeExistingDirs(candidates) {
  const seen = new Set()
  const out = []
  for (const raw of candidates) {
    if (!raw) continue
    const resolved = path.resolve(raw)
    if (seen.has(resolved)) continue
    seen.add(resolved)
    if (existsSync(resolved)) out.push(resolved)
  }
  return out
}

/**
 * Resolve the primary git checkout directory when `repoDir` is a linked git worktree.
 */
export function resolveGitPrimaryRoot(repoDir) {
  if (!repoDir || !existsSync(repoDir)) return null
  try {
    const commonDir = execFileSync(
      'git',
      ['-C', repoDir, 'rev-parse', '--git-common-dir'],
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 5000 }
    ).trim()
    if (!commonDir) return null
    const resolvedCommon = path.resolve(repoDir, commonDir)
    if (path.basename(resolvedCommon) === '.git') {
      return path.dirname(resolvedCommon)
    }
    return path.dirname(resolvedCommon)
  } catch {
    return null
  }
}

export function resolveAgentCollabRoot(explicitRoot = null) {
  if (explicitRoot) return path.resolve(explicitRoot)
  const fromEnv =
    process.env.PORPITA_E2E_AGENT_COLLAB_ROOT || process.env.AGENT_COLLAB_ROOT
  if (fromEnv) return path.resolve(fromEnv)
  const fromSuite = findAncestorDir(SUITE_DIR, isAgentCollabCheckout)
  if (fromSuite) return fromSuite
  const fromCwd = findAncestorDir(process.cwd(), isAgentCollabCheckout)
  if (fromCwd) return fromCwd
  return path.resolve(SUITE_DIR, '..', '..')
}

export function resolvePythonExecutable(agentCollabRoot = resolveAgentCollabRoot()) {
  const fromEnv = process.env.PORPITA_E2E_PYTHON || process.env.PYTHON_BIN
  if (fromEnv) {
    if (existsSync(fromEnv)) return fromEnv
    const probeEnv = spawnSync(fromEnv, ['--version'], {
      stdio: 'ignore',
      timeout: 5000
    })
    if (probeEnv.status === 0) return fromEnv
  }

  const searchRoots = dedupeExistingDirs([
    agentCollabRoot,
    resolveGitPrimaryRoot(agentCollabRoot),
    SUITE_DIR,
    path.resolve(SUITE_DIR, '..', '..'),
    process.cwd()
  ])

  const venvRelatives =
    process.platform === 'win32'
      ? [
          path.join('.venv', 'Scripts', 'python.exe'),
          path.join('.venv', 'bin', 'python')
        ]
      : [
          path.join('.venv', 'bin', 'python'),
          path.join('.venv', 'bin', 'python3'),
          path.join('.venv', 'Scripts', 'python.exe')
        ]

  for (const root of searchRoots) {
    for (const rel of venvRelatives) {
      const candidate = path.join(root, rel)
      if (existsSync(candidate)) return candidate
    }
  }

  const pathCandidates =
    process.platform === 'win32' ? ['python', 'python3', 'py'] : ['python3', 'python']
  for (const cmd of pathCandidates) {
    const res = spawnSync(cmd, ['--version'], { stdio: 'ignore', timeout: 5000 })
    if (res.status === 0) return cmd
  }

  throw new Error(
    `Unable to locate a usable Python interpreter (checked .venv under ${searchRoots.join(', ')} and PATH: ${pathCandidates.join(', ')})`
  )
}

export function resolveDefaultPorpitaRoot(agentCollabRoot = resolveAgentCollabRoot()) {
  const fromEnv =
    process.env.PORPITA_E2E_PORPITA_ROOT || process.env.PORPITA_ROOT
  if (fromEnv) return path.resolve(fromEnv)
  const primary = resolveGitPrimaryRoot(agentCollabRoot)
  const candidates = [
    primary && path.join(primary, '.tmp', 'porpita-ui-spec-03'),
    path.join(agentCollabRoot, '.tmp', 'porpita-ui-spec-03'),
    path.resolve(primary || agentCollabRoot, '..', 'Porpita')
  ].filter(Boolean)
  for (const c of candidates) {
    if (existsSync(path.join(c, 'package.json'))) return c
  }
  return candidates[0]
}

export function resolveDefaultSpecRoot(agentCollabRoot = resolveAgentCollabRoot()) {
  const fromEnv =
    process.env.PORPITA_E2E_SPEC_ROOT || process.env.PORPITA_SPEC_ROOT
  if (fromEnv) return path.resolve(fromEnv)
  return path.join(agentCollabRoot, 'docs', 'client', 'porpita-ui-spec')
}

export function resolveDefaultHistoryRoot({
  agentCollabRoot = resolveAgentCollabRoot(),
  specRoot = resolveDefaultSpecRoot(agentCollabRoot),
  porpitaRoot = resolveDefaultPorpitaRoot(agentCollabRoot)
} = {}) {
  const fromEnv =
    process.env.PORPITA_E2E_HISTORY_ROOT || process.env.PORPITA_HISTORY_ROOT
  if (fromEnv) return path.resolve(fromEnv)

  const specAcBase = path.resolve(specRoot, '..', '..', '..')
  const primary = resolveGitPrimaryRoot(agentCollabRoot)
  const candidates = [
    path.join(
      specAcBase,
      'integration_evidence',
      'porpita-ui-spec-cloud-handoff-20261118',
      'porpita-history-root'
    ),
    path.join(
      agentCollabRoot,
      'integration_evidence',
      'porpita-ui-spec-cloud-handoff-20261118',
      'porpita-history-root'
    ),
    path.resolve(primary || agentCollabRoot, '..', 'Porpita'),
    porpitaRoot
  ]
  for (const c of candidates) {
    if (c && existsSync(c)) return c
  }
  return porpitaRoot
}

export function resolveDefaultRefRoot({
  agentCollabRoot = resolveAgentCollabRoot(),
  specRoot = resolveDefaultSpecRoot(agentCollabRoot)
} = {}) {
  const fromEnv = process.env.PORPITA_E2E_REF_ROOT || process.env.PORPITA_REF_ROOT
  if (fromEnv) return path.resolve(fromEnv)
  const specAcBase = path.resolve(specRoot, '..', '..', '..')
  const primary = resolveGitPrimaryRoot(agentCollabRoot)
  const rel = path.join('RFC_TEMP_SOURCE', 'Porpita-Workspace-UI-Spec-Reference-v1.0.0')
  const candidates = [
    path.join(specAcBase, rel),
    path.join(agentCollabRoot, rel),
    primary && path.join(primary, rel)
  ].filter(Boolean)
  for (const c of candidates) {
    if (existsSync(c)) return c
  }
  return candidates[0]
}

export function resolveCheckDesignEvidenceScript(
  agentCollabRoot = resolveAgentCollabRoot()
) {
  const fromEnv = process.env.UI_SPEC_CHECK_DESIGN_EVIDENCE_SCRIPT
  if (fromEnv && existsSync(fromEnv)) return path.resolve(fromEnv)
  const home = os.homedir()
  const candidates = [
    path.join(
      home,
      '.gemini',
      'config',
      'plugins',
      'ui-spec-studio',
      'skills',
      'ui-spec',
      'scripts',
      'check_design_evidence.py'
    ),
    path.join(
      home,
      '.gemini',
      'antigravity',
      'skills',
      'ui-spec',
      'scripts',
      'check_design_evidence.py'
    ),
    path.join(agentCollabRoot, '.ui-spec', 'check_design_evidence.py')
  ]
  return candidates.find((p) => existsSync(p)) || null
}
