import { execFileSync } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import {
  cpSync,
  existsSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync
} from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { resolveAgentCollabRoot } from './paths.mjs'

// Authoritative baseline manifest recorded at E2E Track start (teamwork_explorer_e2e_2/handoff.md)
export const AGENT_COLLAB_BASELINE_HEAD = 'e5d71968a13e67e3dc51e318867d4ed9a1f946ac'
export const AGENT_COLLAB_TRACKED_MODS = {
  'README.md': '20EB031218C848DC9109F9BF2ABDE413097857AFA4879951601A2AC3F4E89A96',
  'README.zh-CN.md': '6554470CA59D3929B3B13D28B68A2CAE36763F42C0A05A8039BE4ED5DF3C2433',
  'agent-collabration/routes/collaboration-runtime/design/BUSINESS-MODEL.zh-CN.md':
    '87B986C8DC0285A35172D3B88B74B531F86B7E6C5563C390D82AB3296A51E6CA',
  'runtime/artifacts.py': '3DA80F915E391C5E8AB736185E1B2B0C59BDA8540F63BF0F8CD05CA3F2AADD23',
  'runtime/communication.py': '8757402142ADA701E8B756E0A9A8E43AE0549DE92D18C9EAC84775EFB3AC3B1C',
  'runtime/communication_dispatch.py':
    'B258170836187CABC5EC984132D9D8E6AF00DF7F8EE2F62EF57CA56164EC12E8',
  'runtime/communication_native_link_storage.py':
    '32DF829C73E03CD02D4BAC563CA03CAC94EB66A190AB90B2C370145E3CD2CF65',
  'runtime/delivery.py': 'F732C6B8C03512B30AE7AC02095602BC6FA5F9BBC1A9A7571778D327F646A259',
  'runtime/orca_receiver_backend.py':
    '1CF8D1D96C1F1FC7E19FD48ED94CF06BF850531AA8A76698724E96E2E36AA738',
  'runtime/receiver.py': '00B092653BB75E2ADF1AA26DC8EA86AEA315335AC79312BEA45B5D44564873C7',
  'runtime/receiver_delivery.py':
    '5F529722F9864EEC8227470E2D3C9B59EEA9ABB6D21F142357956B859D7224B3',
  'runtime_tests/test_communication_client_native_links.py':
    '1342480C555A113AB2C33D725DB2EB42880CD78A2FAE5240FE547476E5B5B2AA',
  'runtime_tests/test_communication_maintenance.py':
    '6A3E960F0C5CA35A8D1AF1F90E15E3B61B0A33249560820C6715900A93C95F5A',
  'runtime_tests/test_orca_receiver_backend.py':
    'E293F19C1223DA4F692A48CDA08AD67C67A2EF364A820D9B1F0BA876E9943A0B',
  'runtime_tests/test_windows_artifact_store.py':
    '0FBFF656C43A35BF5650686ABE4F48B4A5C9B2458A7F3F043CA8A9F6F1F8C1BF'
}

export const PORPITA_BASELINE_HEAD = '517555d5ce68ba8e417cdd2192b561a4061237ef'
export const PORPITA_DELETED_COUNT = 188
export const PORPITA_DELIVERY_MANIFEST_SHA256 =
  '21A04812527C193C8F889DAF749BB251AB465F8A62F1EA2788AFD94E8E384621'

// Valid 1x1 PNG pixel
const TINY_PNG_BASE64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='

function runGit(cwd, args) {
  return execFileSync('git', ['-C', cwd, ...args], {
    encoding: 'utf8',
    timeout: 60000
  }).trim()
}

export function sha256File(filePath) {
  const data = readFileSync(filePath)
  return createHash('sha256').update(data).digest('hex').toUpperCase()
}

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms)
}

function removeDirSyncWithRetries(targetDir, attempts = 20, delayMs = 300) {
  if (!targetDir || !existsSync(targetDir)) return
  for (let i = 0; i < attempts; i++) {
    try {
      rmSync(targetDir, { recursive: true, force: true, maxRetries: 4, retryDelay: 150 })
      if (!existsSync(targetDir)) return
    } catch {
      if (i === attempts - 1) return
    }
    sleepSync(delayMs)
  }
}

export function createTempPlainFolder({ name = 'plain-folder', files = {} } = {}) {
  const rootDir = path.join(os.tmpdir(), `porpita-folder-${randomUUID().slice(0, 10)}`)
  const folderPath = path.join(rootDir, name)
  mkdirSync(folderPath, { recursive: true })
  const defaults = {
    'readme.txt': 'Non-git local workspace fixture\n',
    ...files
  }
  for (const [rel, content] of Object.entries(defaults)) {
    const dest = path.join(folderPath, rel)
    mkdirSync(path.dirname(dest), { recursive: true })
    writeFileSync(dest, content, 'utf8')
  }
  return {
    rootDir,
    folderPath,
    cleanup() {
      removeDirSyncWithRetries(rootDir)
    }
  }
}

export function createTempGitRepo({
  name = 'e2e-repo',
  files = {},
  worktrees = [],
  dirtyFiles = {}
} = {}) {
  const rootDir = path.join(os.tmpdir(), `porpita-git-${randomUUID().slice(0, 10)}`)
  const repoPath = path.join(rootDir, name)
  mkdirSync(repoPath, { recursive: true })

  try {
    runGit(repoPath, ['init', '-b', 'main'])
    runGit(repoPath, ['config', 'user.name', 'Porpita E2E'])
    runGit(repoPath, ['config', 'user.email', 'e2e@porpita.invalid'])

    const defaultFiles = {
      'notes.md':
        '# Release Notes\n\n## Overview\n\nDisposable editor text.\n\n<script>window.__xss = true</script>\n\n![Missing diagram](missing.png)\n',
      'sample.csv': buildSampleCsv(1050),
      'preview.html': '<!doctype html><html><body><h1>Sandbox Preview</h1><p id="html-marker">Porpita HTML Marker</p></body></html>\n',
      'README.md': `# ${name}\n\nFixture repository for Porpita E2E.\n`,
      ...files
    }

    for (const [rel, content] of Object.entries(defaultFiles)) {
      const dest = path.join(repoPath, rel)
      mkdirSync(path.dirname(dest), { recursive: true })
      writeFileSync(dest, content)
    }
    const pngPath = path.join(repoPath, 'sample.png')
    if (!existsSync(pngPath)) {
      writeFileSync(pngPath, Buffer.from(TINY_PNG_BASE64, 'base64'))
    }

    runGit(repoPath, ['add', '.'])
    runGit(repoPath, [
      '-c',
      'core.hooksPath=/dev/null',
      '-c',
      'commit.gpgsign=false',
      'commit',
      '-m',
      'Initial E2E fixture'
    ])

    const createdWorktrees = []
    for (const wt of worktrees) {
      const wtPath = path.join(rootDir, `${name}-${wt.branch}`)
      runGit(repoPath, ['worktree', 'add', '-b', wt.branch, wtPath])
      if (wt.uniqueCommitFile) {
        const target = path.join(wtPath, wt.uniqueCommitFile)
        mkdirSync(path.dirname(target), { recursive: true })
        writeFileSync(target, wt.uniqueCommitContent || `Unique commit on ${wt.branch}\n`, 'utf8')
        runGit(wtPath, ['add', '.'])
        runGit(wtPath, [
          '-c',
          'core.hooksPath=/dev/null',
          '-c',
          'commit.gpgsign=false',
          'commit',
          '-m',
          `Unique commit ${wt.branch}`
        ])
      }
      if (wt.dirtyFile) {
        const target = path.join(wtPath, wt.dirtyFile)
        mkdirSync(path.dirname(target), { recursive: true })
        writeFileSync(target, wt.dirtyContent || `Uncommitted dirty work on ${wt.branch}\n`, 'utf8')
      }
      createdWorktrees.push({ branch: wt.branch, path: wtPath })
    }

    for (const [rel, content] of Object.entries(dirtyFiles)) {
      const dest = path.join(repoPath, rel)
      mkdirSync(path.dirname(dest), { recursive: true })
      writeFileSync(dest, content, 'utf8')
    }

    return {
      rootDir,
      repoPath,
      worktrees: createdWorktrees,
      getHead() {
        return runGit(repoPath, ['rev-parse', 'HEAD'])
      },
      getStatusShort() {
        return runGit(repoPath, ['status', '--short'])
      },
      getBranches() {
        return runGit(repoPath, ['branch', '--list'])
      },
      cleanup() {
        removeDirSyncWithRetries(rootDir)
      }
    }
  } catch (err) {
    removeDirSyncWithRetries(rootDir)
    throw err
  }
}

function buildSampleCsv(rows) {
  const lines = ['id,name,status,score']
  for (let i = 1; i <= rows; i++) {
    lines.push(`${i},item-${String(i).padStart(4, '0')},${i % 2 === 0 ? 'ready' : 'pending'},${(i * 7) % 100}`)
  }
  return lines.join('\n') + '\n'
}

export function createCodexHistoryFixture({
  homeDir,
  repoPath,
  id = '019f1000-1111-7222-8333-444444444456',
  prompt = 'Follow up on the release checklist',
  reply = 'The saved release notes are ready for review.',
  clock = '06'
}) {
  const dir = path.join(homeDir, '.codex', 'sessions', '2026', '09', '04')
  mkdirSync(dir, { recursive: true })
  const timestamp = `2026-09-04T12:00:${clock}.000Z`
  const file = path.join(dir, `rollout-2026-09-04T12-00-${clock}-${id}.jsonl`)
  const records = [
    {
      type: 'session_meta',
      payload: {
        id,
        timestamp,
        cwd: repoPath,
        originator: 'codex_cli_rs',
        source: 'cli',
        history_mode: 'paginated'
      }
    },
    {
      type: 'response_item',
      payload: {
        type: 'message',
        role: 'user',
        id: 'input',
        content: [{ type: 'input_text', text: prompt }]
      }
    },
    {
      type: 'event_msg',
      payload: {
        type: 'item_completed',
        thread_id: id,
        turn_id: 'turn-0',
        completed_at_ms: Date.parse(timestamp),
        item: { type: 'UserMessage', id: 'user-0', content: [{ type: 'text', text: prompt }] }
      }
    },
    {
      type: 'response_item',
      payload: {
        type: 'message',
        role: 'assistant',
        id: 'answer-0',
        content: [{ type: 'output_text', text: reply }]
      }
    },
    {
      type: 'event_msg',
      payload: {
        type: 'item_completed',
        thread_id: id,
        turn_id: 'turn-0',
        completed_at_ms: Date.parse(timestamp),
        item: { type: 'AgentMessage', id: 'answer-0', content: [{ type: 'Text', text: reply }] }
      }
    }
  ]
  writeFileSync(
    file,
    records.map((rec, ordinal) => JSON.stringify({ timestamp, ordinal, ...rec })).join('\n') + '\n',
    'utf8'
  )
  return file
}

export async function startLoopbackHttpServer() {
  const server = http.createServer((req, res) => {
    const url = req.url || '/'
    if (url === '/page2') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
      res.end(
        '<!doctype html><html><head><title>Loopback Page 2</title></head><body><h1>Page Two</h1><p>Findable marker alpha and marker beta here.</p></body></html>'
      )
      return
    }
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
    res.end(
      '<!doctype html><html><head><title>Loopback Page 1</title></head><body><h1>Page One</h1><p>Initial marker one.</p><a href="/page2">Go Page 2</a></body></html>'
    )
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const addr = server.address()
  const port = typeof addr === 'object' && addr ? addr.port : 0
  return {
    port,
    baseUrl: `http://127.0.0.1:${port}`,
    async close() {
      await new Promise((resolve) => server.close(() => resolve()))
    }
  }
}

export function createSyntheticSkillFixture(homeDir, skillName = 'e2e-offline-skill') {
  const skillDir = path.join(homeDir, '.agents', 'skills', skillName)
  mkdirSync(skillDir, { recursive: true })
  const skillFile = path.join(skillDir, 'SKILL.md')
  writeFileSync(
    skillFile,
    `---\nname: ${skillName}\ndescription: Synthetic offline E2E skill fixture\n---\n# ${skillName}\nOffline local skill instructions.\n`,
    'utf8'
  )
  return { skillDir, skillFile, skillName }
}

export function createSyntheticPluginFixture(porpitaRoot, targetParentDir = null) {
  const rootDir =
    targetParentDir || path.join(os.tmpdir(), `porpita-plugin-${randomUUID().slice(0, 10)}`)
  const pluginDir = path.join(rootDir, 'hello-components')
  mkdirSync(pluginDir, { recursive: true })
  const srcExample = path.join(porpitaRoot, 'examples', 'plugins', 'hello-components')
  if (existsSync(srcExample)) {
    cpSync(srcExample, pluginDir, { recursive: true })
  } else {
    writeFileSync(
      path.join(pluginDir, 'orca-plugin.json'),
      JSON.stringify(
        {
          manifestVersion: 2,
          execution: 'sandboxed-ui',
          id: 'e2e-synthetic-plugin',
          name: 'E2E Synthetic Plugin',
          version: '1.0.0',
          description: 'Synthetic E2E declarative plugin',
          engines: { orca: '>=1.4.246' },
          pluginApi: 1,
          contributes: {
            panels: [
              {
                id: 'e2e-panel',
                title: 'E2E Synthetic Panel',
                icon: 'check',
                entry: 'panel.html'
              }
            ]
          },
          capabilities: []
        },
        null,
        2
      ),
      'utf8'
    )
    writeFileSync(
      path.join(pluginDir, 'panel.html'),
      '<!doctype html><html><body><h1>E2E Synthetic Panel</h1></body></html>',
      'utf8'
    )
  }
  return {
    rootDir,
    pluginDir,
    title: existsSync(srcExample) ? 'Hello Components' : 'E2E Synthetic Panel',
    cleanup() {
      if (!targetParentDir) rmSync(rootDir, { recursive: true, force: true })
    }
  }
}

function normFsPath(p) {
  let resolved = path.resolve(p)
  try {
    if (existsSync(resolved)) resolved = realpathSync(resolved)
  } catch {
    // Keep resolved fallback
  }
  return process.platform === 'win32' ? resolved.toLowerCase() : resolved
}

function tryRunGit(cwd, args) {
  if (!cwd || !existsSync(cwd)) return null
  try {
    return execFileSync('git', ['-C', cwd, ...args], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
      timeout: 60000
    }).trim()
  } catch {
    return null
  }
}

function isDirtyPorpitaUserRoot(targetDir) {
  const topLevel = tryRunGit(targetDir, ['rev-parse', '--show-toplevel'])
  if (!topLevel || normFsPath(topLevel) !== normFsPath(targetDir)) return false
  if (existsSync(path.join(targetDir, 'delivery-manifest.json'))) return true
  const head = tryRunGit(targetDir, ['rev-parse', 'HEAD'])
  if (head === PORPITA_BASELINE_HEAD) return true
  const status = tryRunGit(targetDir, ['status', '--short']) || ''
  return status.split(/\r?\n/).some((l) => l.startsWith('D ') || l.startsWith(' D '))
}

function verifyPorpitaDirtyRoot(targetDir, issues) {
  const pHead = runGit(targetDir, ['rev-parse', 'HEAD'])
  if (pHead !== PORPITA_BASELINE_HEAD) {
    issues.push(`Porpita HEAD mismatch: expected ${PORPITA_BASELINE_HEAD}, got ${pHead}`)
  }

  const pStatusLines = runGit(targetDir, ['status', '--short'])
    .split(/\r?\n/)
    .filter(Boolean)
  const deletions = pStatusLines.filter((l) => l.startsWith('D ') || l.startsWith(' D '))
  const untracked = pStatusLines.filter((l) => l.startsWith('?? '))
  const other = pStatusLines.filter(
    (l) => !l.startsWith('D ') && !l.startsWith(' D ') && !l.startsWith('?? ')
  )
  if (deletions.length !== PORPITA_DELETED_COUNT) {
    issues.push(
      `Porpita deleted tracked count mismatch: expected ${PORPITA_DELETED_COUNT}, got ${deletions.length}`
    )
  }
  if (untracked.length !== 1 || !untracked[0].endsWith('delivery-manifest.json')) {
    issues.push(`Porpita untracked entries unexpected: ${JSON.stringify(untracked)}`)
  }
  if (other.length > 0) {
    issues.push(`Porpita unexpected status entries: ${JSON.stringify(other)}`)
  }
  const manifestPath = path.join(targetDir, 'delivery-manifest.json')
  if (!existsSync(manifestPath)) {
    issues.push('Porpita delivery-manifest.json missing')
  } else {
    const manifestHash = sha256File(manifestPath)
    if (manifestHash !== PORPITA_DELIVERY_MANIFEST_SHA256) {
      issues.push(
        `Porpita delivery-manifest.json SHA256 mismatch: expected ${PORPITA_DELIVERY_MANIFEST_SHA256}, got ${manifestHash}`
      )
    }
  }
  return { mode: 'dirty-user-root', root: targetDir, head: pHead, deletionsCount: deletions.length, untracked }
}

export function verifyGitBaselines({
  agentCollabRoot = null,
  porpitaRoot = null,
  historyRoot = null
} = {}) {
  const issues = []
  const resolvedAcRoot = resolveAgentCollabRoot(agentCollabRoot)

  const acGitDir = tryRunGit(resolvedAcRoot, ['rev-parse', '--git-dir'])
  const acCommonDir = tryRunGit(resolvedAcRoot, ['rev-parse', '--git-common-dir'])
  const acIsPrimaryCheckout = Boolean(
    acGitDir &&
      acCommonDir &&
      normFsPath(path.resolve(resolvedAcRoot, acGitDir)) ===
        normFsPath(path.resolve(resolvedAcRoot, acCommonDir))
  )
  const acHead = tryRunGit(resolvedAcRoot, ['rev-parse', 'HEAD'])
  const acDiffFiles = (tryRunGit(resolvedAcRoot, ['diff', '--name-only']) || '')
    .split(/\r?\n/)
    .filter(Boolean)
    .sort()
  const acIsDirtyRoot =
    acIsPrimaryCheckout &&
    (acHead === AGENT_COLLAB_BASELINE_HEAD ||
      acDiffFiles.some((f) => Object.prototype.hasOwnProperty.call(AGENT_COLLAB_TRACKED_MODS, f)))

  const actualHashes = {}
  if (acIsDirtyRoot) {
    if (acHead !== AGENT_COLLAB_BASELINE_HEAD) {
      issues.push(
        `Agent-collaboration HEAD mismatch: expected ${AGENT_COLLAB_BASELINE_HEAD}, got ${acHead}`
      )
    }
    const expectedFiles = Object.keys(AGENT_COLLAB_TRACKED_MODS).sort()
    if (JSON.stringify(acDiffFiles) !== JSON.stringify(expectedFiles)) {
      issues.push(
        `Agent-collaboration modified tracked files changed: expected ${expectedFiles.length} (${expectedFiles.join(', ')}), got ${acDiffFiles.length} (${acDiffFiles.join(', ')})`
      )
    }
    for (const rel of expectedFiles) {
      const abs = path.join(resolvedAcRoot, rel)
      if (!existsSync(abs)) {
        issues.push(`Missing Agent-collaboration tracked file: ${rel}`)
        continue
      }
      const hash = sha256File(abs)
      actualHashes[rel] = hash
      if (hash !== AGENT_COLLAB_TRACKED_MODS[rel]) {
        issues.push(
          `Agent-collaboration baseline file modified: ${rel} expected SHA256=${AGENT_COLLAB_TRACKED_MODS[rel]}, got ${hash}`
        )
      }
    }
  } else if (!existsSync(resolvedAcRoot)) {
    issues.push(`Missing Agent-collaboration root: ${resolvedAcRoot}`)
  }

  for (const dir of ['RFC_TEMP_SOURCE', 'integration_evidence', 'docs/client/porpita-ui-spec']) {
    if (!existsSync(path.join(resolvedAcRoot, dir))) {
      issues.push(`Missing Agent-collaboration baseline dir: ${dir}`)
    }
  }

  const targetHistory = historyRoot || porpitaRoot
  let porpitaInfo = { mode: 'skipped', head: null, deletionsCount: 0, untracked: [] }
  let historyInfo = null

  if (targetHistory) {
    const resolvedTarget = path.resolve(targetHistory)
    if (!existsSync(resolvedTarget)) {
      issues.push(`Missing history/porpita root: ${resolvedTarget}`)
    } else if (isDirtyPorpitaUserRoot(resolvedTarget)) {
      porpitaInfo = verifyPorpitaDirtyRoot(resolvedTarget, issues)
      historyInfo = { mode: 'dirty-user-root', root: resolvedTarget }
    } else {
      const topLevel = tryRunGit(resolvedTarget, ['rev-parse', '--show-toplevel'])
      const isTopLevel = Boolean(topLevel && normFsPath(topLevel) === normFsPath(resolvedTarget))
      const hasDocs = existsSync(path.join(resolvedTarget, 'docs'))
      const hasPkg = existsSync(path.join(resolvedTarget, 'package.json'))
      if (!hasDocs && !hasPkg) {
        issues.push(`History/porpita root lacks docs or package.json: ${resolvedTarget}`)
      }
      historyInfo = {
        mode: isTopLevel ? 'clean-clone' : 'history-subdir',
        root: resolvedTarget,
        head: tryRunGit(resolvedTarget, ['rev-parse', 'HEAD'])
      }
    }
  }

  const siblingPorpita = path.resolve(resolvedAcRoot, '..', 'Porpita')
  const sameAsTarget =
    targetHistory && normFsPath(siblingPorpita) === normFsPath(targetHistory)
  if (!sameAsTarget && (acIsDirtyRoot || !targetHistory) && existsSync(siblingPorpita)) {
    if (isDirtyPorpitaUserRoot(siblingPorpita)) {
      porpitaInfo = verifyPorpitaDirtyRoot(siblingPorpita, issues)
    }
  }

  return {
    ok: issues.length === 0,
    issues,
    agentCollab: {
      mode: acIsDirtyRoot ? 'dirty-user-root' : acIsPrimaryCheckout ? 'clean-clone' : 'worktree',
      root: resolvedAcRoot,
      head: acHead,
      trackedModsCount: acDiffFiles.length,
      hashes: actualHashes
    },
    porpita: porpitaInfo,
    history: historyInfo
  }
}
