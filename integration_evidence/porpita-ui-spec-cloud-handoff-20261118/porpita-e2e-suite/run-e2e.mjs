import { mkdirSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { cleanupAllAcsCores } from './lib/acs-core-harness.mjs'
import { cleanupAllElectronApps } from './lib/electron-harness.mjs'
import {
  resolveAgentCollabRoot,
  resolveDefaultHistoryRoot,
  resolveDefaultPorpitaRoot,
  resolveDefaultRefRoot,
  resolveDefaultSpecRoot
} from './lib/paths.mjs'
import { ENV_BOUNDED_ITEMS, runTestCase } from './lib/test-context.mjs'
import { TIER1_TESTS } from './tests/tier1-features.mjs'
import { TIER2_TESTS } from './tests/tier2-boundaries.mjs'
import { TIER3_TESTS } from './tests/tier3-pairwise.mjs'
import { TIER4_TESTS } from './tests/tier4-scenarios.mjs'

function parseArgs(argv) {
  const opts = {
    tier: 'all',
    mode: 'full',
    agentCollabRoot: null,
    porpitaRoot: null,
    specRoot: null,
    historyRoot: null,
    refRoot: null,
    report: null,
    filter: null
  }
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]
    const next = () => {
      if (i + 1 >= argv.length) throw new Error(`Missing value for ${arg}`)
      return argv[++i]
    }
    if (arg === '--tier') opts.tier = next()
    else if (arg === '--mode') opts.mode = next()
    else if (arg === '--agent-collab-root') opts.agentCollabRoot = next()
    else if (arg === '--porpita-root') opts.porpitaRoot = next()
    else if (arg === '--spec-root') opts.specRoot = next()
    else if (arg === '--history-root') opts.historyRoot = next()
    else if (arg === '--ref-root') opts.refRoot = next()
    else if (arg === '--report') opts.report = next()
    else if (arg === '--filter') opts.filter = next()
    else if (arg === '--help' || arg === '-h') {
      console.log(
        'Usage: node run-e2e.mjs [--tier 1|2|3|4|all] [--mode smoke|full] [--agent-collab-root <path>] [--porpita-root <path>] [--spec-root <path>] [--history-root <path>] [--ref-root <path>] [--report <path>] [--filter <substring>]'
      )
      process.exit(0)
    } else {
      throw new Error(`Unknown CLI argument: ${arg}`)
    }
  }
  if (!['1', '2', '3', '4', 'all'].includes(opts.tier)) {
    throw new Error(`Invalid --tier: ${opts.tier}`)
  }
  if (!['smoke', 'full'].includes(opts.mode)) {
    throw new Error(`Invalid --mode: ${opts.mode}`)
  }
  const agentCollabRoot = resolveAgentCollabRoot(opts.agentCollabRoot)
  const porpitaRoot = path.resolve(opts.porpitaRoot || resolveDefaultPorpitaRoot(agentCollabRoot))
  const specRoot = path.resolve(opts.specRoot || resolveDefaultSpecRoot(agentCollabRoot))
  const historyRoot = path.resolve(
    opts.historyRoot || resolveDefaultHistoryRoot({ agentCollabRoot, specRoot, porpitaRoot })
  )
  const refRoot = path.resolve(
    opts.refRoot || resolveDefaultRefRoot({ agentCollabRoot, specRoot })
  )
  return {
    ...opts,
    agentCollabRoot,
    porpitaRoot,
    specRoot,
    historyRoot,
    refRoot
  }
}

function selectTests(opts) {
  const all = [...TIER1_TESTS, ...TIER2_TESTS, ...TIER3_TESTS, ...TIER4_TESTS]
  let selected =
    opts.tier === 'all' ? all : all.filter((t) => String(t.tier) === opts.tier)
  if (opts.filter) {
    const needle = opts.filter.toLowerCase()
    selected = selected.filter(
      (t) =>
        t.id.toLowerCase().includes(needle) ||
        t.featureArea.toLowerCase().includes(needle) ||
        t.refs.some((r) => r.toLowerCase().includes(needle))
    )
  }
  return selected
}

let cleaningUp = false
async function globalCleanup() {
  if (cleaningUp) return
  cleaningUp = true
  await cleanupAllElectronApps().catch(() => {})
  await cleanupAllAcsCores().catch(() => {})
}

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, async () => {
    await globalCleanup()
    process.exit(130)
  })
}

async function main() {
  const opts = parseArgs(process.argv.slice(2))
  const tests = selectTests(opts)
  if (tests.length === 0) {
    throw new Error('No tests matched the given --tier / --filter criteria')
  }

  const startedAt = new Date().toISOString()
  console.log(
    `[porpita-e2e] mode=${opts.mode} tier=${opts.tier} count=${tests.length} porpitaRoot=${opts.porpitaRoot}`
  )

  const ctx = {
    mode: opts.mode,
    agentCollabRoot: opts.agentCollabRoot,
    porpitaRoot: opts.porpitaRoot,
    specRoot: opts.specRoot,
    historyRoot: opts.historyRoot,
    refRoot: opts.refRoot,
    onTimeout: async () => {
      await cleanupAllElectronApps().catch(() => {})
      await cleanupAllAcsCores().catch(() => {})
    }
  }

  const results = []
  try {
    for (const spec of tests) {
      const res = await runTestCase(spec, ctx)
      results.push(res)
      const tag =
        res.status === 'PASS'
          ? 'PASS'
          : res.status === 'PENDING_MILESTONE'
            ? `PENDING(${res.evidence?.milestone || '?'})`
            : 'FAIL'
      console.log(`  [${tag}] ${res.id} (${res.durationMs}ms)${res.error ? ` — ${res.error.split('\n')[0]}` : ''}`)
    }
  } finally {
    await globalCleanup()
  }

  const counts = {
    total: results.length,
    passed: results.filter((r) => r.status === 'PASS').length,
    pendingMilestone: results.filter((r) => r.status === 'PENDING_MILESTONE').length,
    failed: results.filter((r) => r.status === 'FAIL').length
  }

  const byTier = {}
  for (const tierNum of [1, 2, 3, 4]) {
    const items = results.filter((r) => r.tier === tierNum)
    if (items.length) {
      byTier[`tier${tierNum}`] = {
        total: items.length,
        passed: items.filter((r) => r.status === 'PASS').length,
        pendingMilestone: items.filter((r) => r.status === 'PENDING_MILESTONE').length,
        failed: items.filter((r) => r.status === 'FAIL').length
      }
    }
  }

  const passedRun =
    opts.mode === 'full'
      ? counts.failed === 0 && counts.pendingMilestone === 0
      : counts.failed === 0

  const report = {
    schemaVersion: 'porpita-e2e-report/1',
    startedAt,
    finishedAt: new Date().toISOString(),
    options: opts,
    passed: passedRun,
    counts,
    byTier,
    envBoundedRegistry: ENV_BOUNDED_ITEMS,
    results
  }

  const reportPath =
    opts.report ||
    path.join(os.tmpdir(), `porpita-e2e-report-${Date.now()}.json`)
  mkdirSync(path.dirname(path.resolve(reportPath)), { recursive: true })
  writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n', 'utf8')

  console.log('\n[porpita-e2e] Summary:')
  console.log(
    `  total=${counts.total} passed=${counts.passed} pendingMilestone=${counts.pendingMilestone} failed=${counts.failed} overall=${passedRun ? 'PASS' : 'FAIL'}`
  )
  console.log(`  report=${reportPath}`)

  process.exit(passedRun ? 0 : 1)
}

main().catch(async (err) => {
  console.error('[porpita-e2e] Fatal runner error:', err)
  await globalCleanup()
  process.exit(2)
})
