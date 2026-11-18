import assert from 'node:assert/strict'

/**
 * Explicit error class for genuine pre-M1..M4 target gaps observed during --mode smoke.
 * In --mode full, any PendingMilestoneError is treated as a hard test FAILURE.
 */
export class PendingMilestoneError extends Error {
  constructor(milestone, expected, observed, details = {}) {
    super(`[PENDING ${milestone}] expected=${expected}; observed=${observed}`)
    this.name = 'PendingMilestoneError'
    this.milestone = milestone
    this.expected = expected
    this.observed = observed
    this.details = details
  }
}

export function pendingIfSmoke(mode, milestone, expected, observed, details = {}) {
  if (mode === 'smoke') {
    throw new PendingMilestoneError(milestone, expected, observed, details)
  }
  assert.fail(`[${milestone}] expected: ${expected}; observed: ${observed}`)
}

/**
 * Authoritative ENV_BOUNDED registry derived from ORIGINAL_REQUEST.md (R3),
 * COVERAGE_CLOSURE.md, ORCA-FIRST.zh-CN.md (T01-T12), and acceptance-scenarios.json (UX01-UX22).
 */
export const ENV_BOUNDED_ITEMS = [
  {
    id: 'EB-01',
    category: 'live_llm_auth',
    refs: ['J05', 'T01', 'T02', 'UX03', 'UX04', 'UX05', 'UX07', 'UX08', 'UX10', 'UX12', 'UX13'],
    condition: 'Live authenticated LLM streaming/tool-calls/approval/quota (Codex/OpenCode/Claude API keys)',
    closureKeywords: ['未登录', 'Chat', '流式', '额度', '登录']
  },
  {
    id: 'EB-02',
    category: 'live_oauth_saas',
    refs: ['J07', 'J08', 'J09', 'UX13'],
    condition: 'Live external OAuth SaaS integrations (GitHub/GitLab/Linear/Jira credentials)',
    closureKeywords: ['托管审阅', '真实任务账号', '任务']
  },
  {
    id: 'EB-03',
    category: 'physical_multi_host',
    refs: ['J04', 'J07', 'J11', 'J12', 'T03', 'T06', 'UX21'],
    condition: 'Physical multi-host networking, real SSH across two separate machines, physical mobile device pairing/relay',
    closureKeywords: ['两台', '物理', '直连 SSH', '跨物理设备']
  },
  {
    id: 'EB-04',
    category: 'foreground_focus_and_screen_reader',
    refs: ['J13', 'UX19'],
    condition: 'Visible OS foreground window focus & OS screen readers (Windows Narrator, macOS VoiceOver, Linux Orca AT-SPI) because ORCA_BACKGROUND_LAUNCH=1 enforces hidden CDP windows',
    closureKeywords: ['读屏', '前台', 'Narrator', 'Orca']
  },
  {
    id: 'EB-05',
    category: 'non_windows_or_arm64_packaging',
    refs: ['J01', 'J13', 'UX01', 'UX18', 'UX20'],
    condition: 'macOS, Linux desktop native installers, Windows ARM64 packaging, and live signed installer upgrade/uninstall',
    closureKeywords: ['macOS', 'Linux', 'Windows ARM64', '安装版']
  },
  {
    id: 'EB-06',
    category: 'hardware_devices',
    refs: ['J13', 'UX19'],
    condition: 'Physical hardware microphone / WebAuthn / audio dictation',
    closureKeywords: ['设备', '硬件', '平台']
  }
]

export function makeTestResult({ id, tier, featureArea, refs, status, durationMs, evidence = {}, error = null }) {
  return {
    id,
    tier,
    featureArea,
    refs,
    status,
    durationMs,
    evidence,
    error
  }
}

export async function runTestCase(spec, ctx) {
  const start = Date.now()
  const timeoutMs = spec.timeoutMs ?? 360_000
  let timer = null
  let timedOut = false
  try {
    const evidence =
      (await Promise.race([
        spec.run(ctx),
        new Promise((_, reject) => {
          timer = setTimeout(() => {
            timedOut = true
            reject(new Error(`Test ${spec.id} timed out after ${timeoutMs}ms`))
          }, timeoutMs)
        })
      ])) ?? {}
    clearTimeout(timer)
    return makeTestResult({
      id: spec.id,
      tier: spec.tier,
      featureArea: spec.featureArea,
      refs: spec.refs,
      status: 'PASS',
      durationMs: Date.now() - start,
      evidence
    })
  } catch (err) {
    if (timer) clearTimeout(timer)
    if (timedOut && typeof ctx.onTimeout === 'function') {
      await ctx.onTimeout().catch(() => {})
    }
    if (err instanceof PendingMilestoneError) {
      return makeTestResult({
        id: spec.id,
        tier: spec.tier,
        featureArea: spec.featureArea,
        refs: spec.refs,
        status: ctx.mode === 'smoke' ? 'PENDING_MILESTONE' : 'FAIL',
        durationMs: Date.now() - start,
        evidence: {
          milestone: err.milestone,
          expected: err.expected,
          observed: err.observed,
          ...err.details
        },
        error: err.message
      })
    }
    return makeTestResult({
      id: spec.id,
      tier: spec.tier,
      featureArea: spec.featureArea,
      refs: spec.refs,
      status: 'FAIL',
      durationMs: Date.now() - start,
      evidence: err.evidence ?? {},
      error: err?.stack || err?.message || String(err)
    })
  }
}
