import { execFileSync, spawnSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import {
  cpSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  rmdirSync,
  unlinkSync,
  writeFileSync
} from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { ENV_BOUNDED_ITEMS } from './test-context.mjs'

const AGENT_COLLAB_ROOT = 'D:\\Chatgpt\\Agent-collaboration'
const VENV_PYTHON = path.join(AGENT_COLLAB_ROOT, '.venv', 'Scripts', 'python.exe')
const CHECK_DESIGN_EVIDENCE_SCRIPT =
  'C:\\Users\\D26FO\\.gemini\\config\\plugins\\ui-spec-studio\\skills\\ui-spec\\scripts\\check_design_evidence.py'

function removeJunctionSafe(junctionPath) {
  try {
    const st = lstatSync(junctionPath)
    if (st.isSymbolicLink() || st.isDirectory()) {
      if (process.platform === 'win32') {
        try {
          rmdirSync(junctionPath)
        } catch {
          execFileSync('cmd', ['/c', 'rmdir', junctionPath], { stdio: 'ignore', timeout: 5000 })
        }
      } else {
        unlinkSync(junctionPath)
      }
    }
  } catch {
    // Not present
  }
}

const STAGED_AUDIT_CACHE = new Map()

export function runStagedBuildCoverage({
  specRoot,
  porpitaRoot,
  historyRoot = 'D:\\Chatgpt\\Porpita',
  injectBrokenAnchor = false
}) {
  const cacheKey = `${specRoot}::${porpitaRoot}::${historyRoot}`
  if (!injectBrokenAnchor && STAGED_AUDIT_CACHE.has(cacheKey)) {
    return STAGED_AUDIT_CACHE.get(cacheKey)
  }

  const stagedRoot = path.join(os.tmpdir(), `porpita-spec-audit-${randomUUID().slice(0, 10)}`)
  const evidenceJunction = path.join(stagedRoot, 'evidence')
  mkdirSync(stagedRoot, { recursive: true })

  try {
    cpSync(path.join(specRoot, 'catalog'), path.join(stagedRoot, 'catalog'), { recursive: true })
    cpSync(path.join(specRoot, 'tools'), path.join(stagedRoot, 'tools'), { recursive: true })
    cpSync(
      path.join(specRoot, 'PLAYBACK_SCENARIOS.md'),
      path.join(stagedRoot, 'PLAYBACK_SCENARIOS.md')
    )
    const srcAudit = path.join(specRoot, 'coverage-audit.json')
    if (existsSync(srcAudit)) {
      cpSync(srcAudit, path.join(stagedRoot, 'baseline-coverage-audit.json'))
    }

    const realEvidence = path.join(specRoot, 'evidence')
    if (process.platform === 'win32') {
      execFileSync('cmd', ['/c', 'mklink', '/J', evidenceJunction, realEvidence], {
        stdio: 'ignore',
        timeout: 10000
      })
    } else {
      throw new Error('Windows junction expected on win32')
    }

    if (injectBrokenAnchor) {
      const psvPath = path.join(stagedRoot, 'catalog', '01-shell-workspace.psv')
      const content = readFileSync(psvPath, 'utf8')
      writeFileSync(
        psvPath,
        content +
          '\nA.99 | Negative Probe Broken Anchor | NonExistentAnchorForNegativeProbe.tsx | N/A | 保留 | N/A | J01\n',
        'utf8'
      )
    }

    const indexOutDir = path.join(stagedRoot, 'source-index')
    const idxRun = spawnSync(
      'node',
      [path.join(stagedRoot, 'tools', 'source-index.cjs'), porpitaRoot, indexOutDir],
      { encoding: 'utf8', timeout: 180000 }
    )

    const covRun = spawnSync(
      VENV_PYTHON,
      [
        path.join(stagedRoot, 'tools', 'build_coverage.py'),
        '--source',
        porpitaRoot,
        '--history',
        historyRoot
      ],
      { encoding: 'utf8', timeout: 180000 }
    )

    const summaryPath = path.join(indexOutDir, 'summary.json')
    const auditPath = path.join(stagedRoot, 'coverage-audit.json')
    const summary = existsSync(summaryPath) ? JSON.parse(readFileSync(summaryPath, 'utf8')) : null
    const audit = existsSync(auditPath) ? JSON.parse(readFileSync(auditPath, 'utf8')) : null

    let stdoutJson = null
    try {
      stdoutJson = covRun.stdout?.trim() ? JSON.parse(covRun.stdout.trim()) : null
    } catch {
      stdoutJson = null
    }

    const result = {
      sourceIndexExitCode: idxRun.status,
      sourceIndexStdout: idxRun.stdout || '',
      sourceIndexStderr: idxRun.stderr || '',
      buildCoverageExitCode: covRun.status,
      buildCoverageStdout: covRun.stdout || '',
      buildCoverageStderr: covRun.stderr || '',
      stdoutJson,
      summary,
      audit
    }
    if (!injectBrokenAnchor && idxRun.status === 0) {
      STAGED_AUDIT_CACHE.set(cacheKey, result)
    }
    return result
  } finally {
    removeJunctionSafe(evidenceJunction)
    for (let i = 0; i < 8; i++) {
      try {
        rmSync(stagedRoot, { recursive: true, force: true })
        break
      } catch {
        if (i === 7) break
        Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 200)
      }
    }
  }
}

export function checkMarkdownLinks({ specRoot, orcaFirstPath }) {
  const broken = []
  const checkedFiles = []

  const scanFile = (mdPath) => {
    checkedFiles.push(mdPath)
    const dir = path.dirname(mdPath)
    const text = readFileSync(mdPath, 'utf8')
    // Match [text](url) or [text](<url>) ignoring images/urls starting with http/https/mailto/#
    const linkRegex = /!?\[[^\]]*\]\((?:<([^>]+)>|([^)\s]+))(?:\s+"[^"]*")?\)/g
    let match
    while ((match = linkRegex.exec(text)) !== null) {
      const rawTarget = (match[1] || match[2] || '').trim()
      if (!rawTarget) continue
      if (
        rawTarget.startsWith('http://') ||
        rawTarget.startsWith('https://') ||
        rawTarget.startsWith('mailto:') ||
        rawTarget.startsWith('#') ||
        rawTarget.startsWith('file://')
      ) {
        continue
      }
      // Skip template placeholders
      if (rawTarget.includes('{{') || rawTarget === 'url') continue
      // Strip anchor fragment & query
      const cleanRel = decodeURIComponent(rawTarget.split('#')[0].split('?')[0])
      if (!cleanRel) continue
      // Skip links pointing inside source-index or generated absolute paths like D:/... if outside
      const resolved = path.isAbsolute(cleanRel) ? cleanRel : path.resolve(dir, cleanRel)
      if (!existsSync(resolved)) {
        broken.push({
          file: mdPath,
          target: rawTarget,
          resolved
        })
      }
    }
  }

  for (const entry of readdirSync(specRoot)) {
    if (entry.endsWith('.md')) {
      scanFile(path.join(specRoot, entry))
    }
  }
  if (orcaFirstPath && existsSync(orcaFirstPath)) {
    scanFile(orcaFirstPath)
  }

  return {
    checkedFilesCount: checkedFiles.length,
    brokenCount: broken.length,
    broken
  }
}

export function checkOrcaFirstCrosswalk({ orcaFirstPath, specRoot }) {
  const orcaText = readFileSync(orcaFirstPath, 'utf8')
  const tIds = [...new Set([...orcaText.matchAll(/\b(T(?:0[1-9]|1[0-2]))\b/g)].map((m) => m[1]))].sort()

  const clientDir = path.dirname(orcaFirstPath)
  const expectedArchives = [
    'UX-DESIGN.zh-CN.md',
    'USER-FLOWS.zh-CN.md',
    'PRODUCT-REVIEW.zh-CN.md',
    'PRODUCT-REVIEW.html',
    'COMMUNICATION-EXPERIENCE.zh-CN.md',
    'COMMUNICATION-EXPERIENCE.html',
    'WORKBENCH-ADOPTION.zh-CN.md',
    'WORKBENCH-ADOPTION.html',
    'review-20261105',
    'communication-20261105',
    'workbench-20261106'
  ]
  const missingArchives = expectedArchives.filter((rel) => !existsSync(path.join(clientDir, rel)))

  // Check whether porpita-ui-spec/*.md cross-references ORCA-FIRST and T01..T12
  const specMdText = readdirSync(specRoot)
    .filter((f) => f.endsWith('.md'))
    .map((f) => readFileSync(path.join(specRoot, f), 'utf8'))
    .join('\n')

  const referencedOrcaFirst = /ORCA-FIRST\.zh-CN\.md/i.test(specMdText)
  const tracedTs = tIds.filter((tid) => new RegExp(`\\b${tid}\\b`).test(specMdText))
  const untracedTs = tIds.filter((tid) => !new RegExp(`\\b${tid}\\b`).test(specMdText))

  return {
    foundTIds: tIds,
    missingArchives,
    referencedOrcaFirst,
    tracedTs,
    untracedTs
  }
}

export function checkReferenceCrosswalk({ refRoot, specRoot }) {
  const deliverables = [
    'UI_SPEC_SUMMARY.md',
    'OBJECT_MODEL.md',
    'INTERACTION_SPEC.md',
    'ORCA_REUSE_MAP.md',
    'SIDEPANEL_CAPABILITY_MATRIX.md',
    'SESSION_INDEX_SPEC.md',
    'TAB_GROUP_SPEC.md',
    'WORKSPACE_LAYOUT_SPEC.md',
    'PLAYBACK_SCENARIOS.md',
    'OPEN_QUESTIONS.md',
    'DECISION_LOG.md'
  ]
  const openQuestionsPath = path.join(refRoot, 'DECISIONS_AND_OPEN_QUESTIONS.md')
  const openQuestionsText = readFileSync(openQuestionsPath, 'utf8')
  const openMatch = openQuestionsText.match(/## 待 UI SPEC 研究（Open）([\s\S]*?)## 明确不做/)
  const openNums = openMatch
    ? [...openMatch[1].matchAll(/^\s*(\d+)\.\s+/gm)].map((m) => Number.parseInt(m[1], 10))
    : []

  const specMdFiles = readdirSync(specRoot).filter((f) => f.endsWith('.md'))
  const specMdText = specMdFiles.map((f) => readFileSync(path.join(specRoot, f), 'utf8')).join('\n')

  const missingDeliverablesInRef = deliverables.filter(
    (name) => !specMdText.includes(name) && !existsSync(path.join(specRoot, name))
  )

  // Check Open Questions #1..#12 traceability in DECISIONS_AND_SEQUENCE.md or spec docs
  const hasExplicitOpenCrosswalk =
    /(?:Open\s*#?\s*1|开放问题\s*#?\s*1|Open Questions)/i.test(specMdText) &&
    openNums.every((n) => new RegExp(`(?:#|问题\\s*|Open\\s*)${n}\\b`).test(specMdText))

  return {
    deliverablesCount: deliverables.length,
    openQuestionsCount: openNums.length,
    missingDeliverablesInRef,
    hasExplicitOpenCrosswalk,
    specMdFiles
  }
}

export function checkApiScopeParity({ clientDocsDir }) {
  const scopePath = path.join(clientDocsDir, 'communication-api-scope.json')
  const fullOpenApiPath = path.join(clientDocsDir, 'communication-openapi.yaml')
  const p1OpenApiPath = path.join(clientDocsDir, 'communication-p1-openapi.yaml')

  const scope = JSON.parse(readFileSync(scopePath, 'utf8'))
  const fullYaml = readFileSync(fullOpenApiPath, 'utf8')
  const p1Yaml = readFileSync(p1OpenApiPath, 'utf8')

  const ops = scope.operations || []
  const p1Ops = ops.filter((o) => o.tier === 'P1_required')
  const p2Ops = ops.filter((o) => o.tier === 'P2_optional')

  const fullOpIds = new Set([...fullYaml.matchAll(/operationId:\s*([A-Za-z0-9_]+)/g)].map((m) => m[1]))
  const p1OpIds = new Set([...p1Yaml.matchAll(/operationId:\s*([A-Za-z0-9_]+)/g)].map((m) => m[1]))

  const missingInFull = ops.map((o) => o.operation_id).filter((id) => !fullOpIds.has(id))
  const missingInP1 = p1Ops.map((o) => o.operation_id).filter((id) => !p1OpIds.has(id))
  const extraP2InP1 = p2Ops.map((o) => o.operation_id).filter((id) => p1OpIds.has(id))

  return {
    totalOps: ops.length,
    p1Count: p1Ops.length,
    p2Count: p2Ops.length,
    fullOpenApiCount: fullOpIds.size,
    p1OpenApiCount: p1OpIds.size,
    missingInFull,
    missingInP1,
    extraP2InP1
  }
}

export function checkEnvBoundedHonesty({ specRoot }) {
  const closurePath = path.join(specRoot, 'COVERAGE_CLOSURE.md')
  const closureText = readFileSync(closurePath, 'utf8')
  const auditPath = path.join(specRoot, 'coverage-audit.json')
  const audit = existsSync(auditPath) ? JSON.parse(readFileSync(auditPath, 'utf8')) : null

  const uncoveredCategories = []
  for (const item of ENV_BOUNDED_ITEMS) {
    const matched = item.closureKeywords.some((kw) => closureText.includes(kw))
    if (!matched) {
      uncoveredCategories.push(item.id)
    }
  }

  // Check for dishonest closure phrases in COVERAGE_CLOSURE.md (e.g. claiming physical multi-host or macOS closed without qualifier)
  const dishonestFindings = []
  const lines = closureText.split(/\r?\n/)
  for (const line of lines) {
    if (/macOS|Linux|Windows ARM64/.test(line) && /已全部关闭|完全闭环|无需验证/.test(line)) {
      dishonestFindings.push(`Dishonest platform closure claim: ${line}`)
    }
    if (/两台物理|真实登录账号/.test(line) && /已全部关闭|完全闭环/.test(line)) {
      dishonestFindings.push(`Dishonest physical/account closure claim: ${line}`)
    }
  }

  // Inspect catalog/iteration-*-assurance.txt to make sure no row blindly says "已全部闭环"
  const catalogDir = path.join(specRoot, 'catalog')
  const assuranceFiles = readdirSync(catalogDir).filter(
    (f) => f.startsWith('iteration-') && f.endsWith('-assurance.txt')
  )
  const assuranceRows = []
  for (const f of assuranceFiles) {
    const content = readFileSync(path.join(catalogDir, f), 'utf8')
    for (const raw of content.split(/\r?\n/)) {
      if (!raw || raw.startsWith('#')) continue
      const parts = raw.split('|')
      if (parts.length >= 4) {
        assuranceRows.push({ file: f, rowId: parts[0].trim(), result: parts[3].trim(), criterion: parts[4] || '' })
      }
    }
  }

  return {
    uncoveredCategories,
    dishonestFindings,
    closureLength: closureText.length,
    auditDomains: audit?.domains ?? null,
    auditRows: audit?.rows ?? null,
    assuranceRowsCount: assuranceRows.length
  }
}

export function runDesignEvidenceCheck({ agentCollabRoot = AGENT_COLLAB_ROOT, porpitaRoot }) {
  const candidates = [
    path.join(porpitaRoot, '.ui-spec', 'design-evidence.json'),
    path.join(agentCollabRoot, '.ui-spec', 'design-evidence.json')
  ]
  const found = candidates.find((p) => existsSync(p))
  if (!found) {
    return {
      applicable: false,
      exitCode: 0,
      reason: 'No .ui-spec/design-evidence.json present (porpita-ui-spec uses native build_coverage.py + observations.json)'
    }
  }
  const projectRoot = path.dirname(path.dirname(found))
  const res = spawnSync(
    VENV_PYTHON,
    [CHECK_DESIGN_EVIDENCE_SCRIPT, '--project-root', projectRoot],
    { encoding: 'utf8', timeout: 30000 }
  )
  let parsed = null
  try {
    parsed = res.stdout?.trim() ? JSON.parse(res.stdout.trim()) : null
  } catch {
    parsed = null
  }
  return {
    applicable: true,
    recordPath: found,
    exitCode: res.status,
    stdout: res.stdout || '',
    stderr: res.stderr || '',
    parsed
  }
}
