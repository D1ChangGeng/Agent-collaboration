const { createRequire } = require('node:module')
const { execFileSync } = require('node:child_process')
const { createHash } = require('node:crypto')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { pathToFileURL } = require('node:url')

function isPorpitaCheckout(dir) {
  if (!dir) return false
  const resolved = path.resolve(dir)
  return (
    fs.existsSync(path.join(resolved, 'package.json')) &&
    fs.existsSync(path.join(resolved, 'src/renderer/src/App.tsx'))
  )
}

function isAgentCollabCheckout(dir) {
  if (!dir) return false
  const resolved = path.resolve(dir)
  return (
    fs.existsSync(path.join(resolved, 'runtime/communication_http.py')) &&
    fs.existsSync(path.join(resolved, 'docs/client/porpita-ui-spec'))
  )
}

function getDefaultOutputDir(isBaseline) {
  const osTag =
    process.platform === 'win32'
      ? 'windows'
      : process.platform === 'darwin'
        ? 'macos'
        : process.platform
  const suffix = isBaseline ? '-baseline' : ''
  return path.resolve(__dirname, `../evidence/iteration-93-${osTag}${suffix}`)
}

function resolveCliOptions(argv) {
  let sourceFlag = null
  let acRootFlag = null
  let outputFlag = null
  let isBaseline = false
  const positional = []

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]
    if (arg === '--baseline') {
      isBaseline = true
    } else if (arg === '--strict') {
      isBaseline = false
    } else if (arg === '--source' && argv[i + 1]) {
      sourceFlag = argv[++i]
    } else if (arg.startsWith('--source=')) {
      sourceFlag = arg.slice('--source='.length)
    } else if (arg === '--ac-root' && argv[i + 1]) {
      acRootFlag = argv[++i]
    } else if (arg.startsWith('--ac-root=')) {
      acRootFlag = arg.slice('--ac-root='.length)
    } else if ((arg === '--output' || arg === '--output-dir') && argv[i + 1]) {
      outputFlag = argv[++i]
    } else if (arg.startsWith('--output=')) {
      outputFlag = arg.slice('--output='.length)
    } else if (arg.startsWith('--output-dir=')) {
      outputFlag = arg.slice('--output-dir='.length)
    } else if (!arg.startsWith('-')) {
      positional.push(arg)
    }
  }

  let source = sourceFlag || process.env.PORPITA_SPEC_SOURCE || null
  let acRoot =
    acRootFlag ||
    process.env.PORPITA_SPEC_AC_ROOT ||
    process.env.PORPITA_E2E_AGENT_COLLAB_ROOT ||
    process.env.AGENT_COLLAB_ROOT ||
    null

  const remainingPositional = []
  for (const pos of positional) {
    if (!source && isPorpitaCheckout(pos)) {
      source = pos
    } else if (!acRoot && isAgentCollabCheckout(pos)) {
      acRoot = pos
    } else {
      remainingPositional.push(pos)
    }
  }
  if (!source && isPorpitaCheckout(process.cwd())) {
    source = process.cwd()
  }
  if (!source) {
    throw new Error(
      'Unable to resolve Porpita source checkout. Set PORPITA_SPEC_SOURCE or pass --source <porpita-dir>.'
    )
  }

  const candidateAcRoot = path.resolve(__dirname, '../../../..')
  if (!acRoot && isAgentCollabCheckout(candidateAcRoot)) {
    acRoot = candidateAcRoot
  }
  if (!acRoot && isAgentCollabCheckout(process.cwd())) {
    acRoot = process.cwd()
  }
  if (!acRoot) {
    throw new Error(
      'Unable to resolve Agent-collaboration root checkout. Set PORPITA_SPEC_AC_ROOT or pass --ac-root <ac-dir>.'
    )
  }

  const resolvedSource = path.resolve(source)
  const resolvedAcRoot = path.resolve(acRoot)
  const outputDir = path.resolve(
    outputFlag || remainingPositional[0] || getDefaultOutputDir(isBaseline)
  )
  return { source: resolvedSource, acRoot: resolvedAcRoot, outputDir, isBaseline }
}

const { source, acRoot, outputDir, isBaseline } = resolveCliOptions(process.argv.slice(2))
const entry = process.env.PORPITA_SPEC_ENTRY
  ? path.resolve(process.env.PORPITA_SPEC_ENTRY)
  : path.join(source, 'out/main/index.js')
if (!fs.existsSync(entry)) {
  throw new Error(`Porpita built main entry not found at ${entry}. Build out/ before running.`)
}

const acsHarnessPath = process.env.PORPITA_SPEC_ACS_HARNESS
  ? path.resolve(process.env.PORPITA_SPEC_ACS_HARNESS)
  : path.join(
      acRoot,
      'integration_evidence/porpita-ui-spec-cloud-handoff-20261118/porpita-e2e-suite/lib/acs-core-harness.mjs'
    )
if (!fs.existsSync(acsHarnessPath)) {
  throw new Error(`ACS loopback harness not found at ${acsHarnessPath}`)
}

const load = createRequire(path.join(source, 'package.json'))
const { _electron } = load('playwright')
const executablePath = process.env.PORPITA_SPEC_EXE || load('electron')

fs.mkdirSync(outputDir, { recursive: true })

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function buildIsolatedEnv(userData, home, lang = 'en_US.UTF-8') {
  const env = Object.fromEntries(
    Object.entries(process.env).filter(
      ([key, value]) =>
        value !== undefined &&
        !/^(HOME|USERPROFILE|HOMEDRIVE|HOMEPATH|APPDATA|LOCALAPPDATA|XDG_CONFIG_HOME|XDG_DATA_HOME|XDG_CACHE_HOME|XDG_STATE_HOME|CLAUDE_CONFIG_DIR|CODEX_HOME|ELECTRON_RUN_AS_NODE|ORCA_.*|PORPITA_.*|ACS_.*|CODEX_.*|OPENAI_.*|ANTHROPIC_.*|GH_.*|GITHUB_.*|GITLAB_.*|AWS_.*|AZURE_.*)$/i.test(
          key
        )
    )
  )
  const platformEnv =
    process.platform === 'win32'
      ? {
          USERPROFILE: home,
          APPDATA: path.join(home, 'AppData', 'Roaming'),
          LOCALAPPDATA: path.join(home, 'AppData', 'Local')
        }
      : {
          XDG_CONFIG_HOME: path.join(home, '.config'),
          XDG_DATA_HOME: path.join(home, '.local', 'share'),
          XDG_CACHE_HOME: path.join(home, '.cache'),
          XDG_STATE_HOME: path.join(home, '.local', 'state')
        }
  return Object.assign(
    env,
    {
      HOME: home,
      NO_PROXY: '127.0.0.1,localhost',
      ORCA_BACKGROUND_LAUNCH: '1',
      ORCA_E2E_HEADLESS: '1',
      ORCA_E2E_USER_DATA_DIR: userData,
      ORCA_E2E_HOME_DIR: home,
      GIT_CONFIG_NOSYSTEM: '1',
      GIT_CONFIG_GLOBAL: path.join(home, 'gitconfig'),
      LANG: lang
    },
    platformEnv
  )
}

function killPidTree(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return
  if (process.platform === 'win32') {
    try {
      execFileSync('taskkill', ['/pid', String(pid), '/T', '/F'], {
        stdio: 'ignore',
        timeout: 5000,
        windowsHide: true
      })
      return
    } catch {
      // Fallback below
    }
  } else {
    try {
      process.kill(-pid, 'SIGTERM')
    } catch {}
    try {
      execFileSync('pkill', ['-TERM', '-P', String(pid)], { stdio: 'ignore', timeout: 2000 })
    } catch {}
    try {
      process.kill(-pid, 'SIGKILL')
    } catch {}
    try {
      execFileSync('pkill', ['-KILL', '-P', String(pid)], { stdio: 'ignore', timeout: 2000 })
    } catch {}
  }
  try {
    process.kill(pid, 'SIGKILL')
  } catch {}
}

function killDaemonPids(userData) {
  const daemonDir = path.join(userData, 'daemon')
  if (!fs.existsSync(daemonDir)) return
  for (const name of fs.readdirSync(daemonDir)) {
    if (!name.endsWith('.pid')) continue
    try {
      const pid = Number.parseInt(fs.readFileSync(path.join(daemonDir, name), 'utf8').trim(), 10)
      killPidTree(pid)
    } catch {}
  }
}

function removeDirBestEffort(dir) {
  if (!dir || !fs.existsSync(dir)) return
  for (let i = 0; i < 8; i++) {
    try {
      fs.rmSync(dir, { recursive: true, force: true })
      return
    } catch {
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 250)
    }
  }
}

function buildSeedAppData(locale, theme = 'dark') {
  const seenAt = Date.parse('2026-01-01T00:00:00.000Z')
  const tipIds = [
    'chat-ui-here',
    'voice-dictation',
    'porpita-cli',
    'cmd-j-palette',
    'agent-session-search'
  ]
  const interactionIds = [
    'agent-chat-composer',
    'agent-chat-send',
    'agent-chat-model-select',
    'agent-chat-permission',
    'agent-terminal-launch',
    'sidebar-search',
    'quick-open',
    'jump-palette',
    'workspace-board',
    'source-control',
    'file-explorer',
    'browser-pane',
    'settings',
    'voice-dictation',
    'skills-page',
    'automations-page',
    'artifacts-page',
    'tasks-page',
    'plugins'
  ]
  const tourIds = [
    'workspace-board',
    'browser',
    'tasks',
    'automations',
    'workspace-creation'
  ]
  return {
    settings: {
      uiLanguage: locale,
      theme,
      reducedMotion: false,
      telemetry: {
        optedIn: true,
        installId: '00000000-0000-4000-8000-000000000000',
        existedBeforeTelemetryRelease: false
      }
    },
    onboarding: {
      flowVersion: 4,
      closedAt: 1,
      outcome: 'completed',
      lastCompletedStep: 5
    },
    ui: {
      featureTipsSeenIds: tipIds,
      featureInteractions: Object.fromEntries(
        interactionIds.map((id) => [id, { firstInteractedAt: seenAt }])
      ),
      contextualToursSeenIds: tourIds,
      contextualToursAutoEligible: false,
      showWelcomeSection: false
    }
  }
}

async function launchIsolatedApp(tempBase, tag, { locale = 'en', theme = 'dark' } = {}) {
  const runRoot = path.join(tempBase, tag)
  const home = path.join(runRoot, 'home')
  const userData = path.join(runRoot, 'userData')
  for (const dir of [
    home,
    userData,
    path.join(home, 'AppData', 'Roaming'),
    path.join(home, 'AppData', 'Local'),
    path.join(home, '.config'),
    path.join(home, '.local', 'share'),
    path.join(home, '.cache'),
    path.join(home, '.local', 'state'),
    path.join(home, '.claude'),
    path.join(home, '.codex')
  ]) {
    fs.mkdirSync(dir, { recursive: true })
  }
  fs.writeFileSync(
    path.join(userData, 'orca-data.json'),
    JSON.stringify(buildSeedAppData(locale, theme), null, 2),
    'utf8'
  )
  const langEnv = locale === 'zh' ? 'zh_CN.UTF-8' : 'en_US.UTF-8'
  const env = buildIsolatedEnv(userData, home, langEnv)
  const app = await _electron.launch({
    executablePath,
    args: [entry, ...(process.env.ORCA_E2E_ELECTRON_ARGS ? process.env.ORCA_E2E_ELECTRON_ARGS.split(' ') : [])],
    cwd: source,
    env,
    timeout: 60000
  })

  try {
    const page = await app.firstWindow({ timeout: 45000 })
    await page.waitForLoadState('domcontentloaded', { timeout: 30000 })
    await page.waitForFunction(() => (document.body.innerText || '').trim().length > 0, {
      timeout: 30000
    })
    const cdp = await page.context().newCDPSession(page)
    const isolation = await app.evaluate(async ({ app: electronApp, BrowserWindow }) => {
      return {
        userData: electronApp.getPath('userData'),
        home: electronApp.getPath('home'),
        version: process.versions.electron,
        windows: BrowserWindow.getAllWindows().map((w) => ({
          visible: w.isVisible(),
          focused: w.isFocused()
        }))
      }
    })
    for (const w of isolation.windows) {
      if (w.visible || w.focused) {
        throw new Error(`Expected background launch (!visible && !focused), got ${JSON.stringify(w)}`)
      }
    }
    return { app, page, cdp, userData, home, isolation }
  } catch (err) {
    try {
      const pid = app.process()?.pid
      await Promise.race([app.close(), delay(3000)])
      killPidTree(pid)
    } catch {}
    killDaemonPids(userData)
    throw err
  }
}

async function closeIsolatedApp(inst) {
  if (!inst) return
  const pid = inst.app.process()?.pid
  try {
    await Promise.race([inst.app.close(), delay(4000)])
  } catch {}
  killPidTree(pid)
  killDaemonPids(inst.userData)
}

async function setWindowSize(inst, width, height) {
  await inst.app.evaluate(
    async ({ BrowserWindow }, size) => {
      const win = BrowserWindow.getAllWindows()[0]
      if (win) win.setSize(size.width, size.height)
    },
    { width, height }
  )
  await inst.page.waitForFunction(
    (expected) =>
      Math.abs(window.innerWidth - expected.width) <= 4 &&
      Math.abs(window.innerHeight - expected.height) <= 4,
    { width, height },
    { timeout: 10000 }
  )
  await inst.page.evaluate(async () => {
    await document.fonts.ready
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))
  })
  await delay(150)
}

async function captureScreen(inst, name, metrics = {}) {
  await inst.page.evaluate(async () => {
    await document.fonts.ready
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))
  })
  const imageFile = `${name}.png`
  const metaFile = `${name}.json`
  const shot = await inst.cdp.send('Page.captureScreenshot', { format: 'png' })
  fs.writeFileSync(path.join(outputDir, imageFile), Buffer.from(shot.data, 'base64'))
  const dom = await inst.page.evaluate(() => ({
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2
  }))
  const record = {
    name,
    imageFile,
    window: dom,
    ...metrics
  }
  fs.writeFileSync(path.join(outputDir, metaFile), JSON.stringify(record, null, 2) + '\n', 'utf8')
  console.log(`Captured ${name}: ${dom.innerWidth}x${dom.innerHeight} overflowX=${dom.overflowX}`)
  return record
}

async function measureContainerGeometry(page, containerSel) {
  return await page.evaluate((sel) => {
    const root = document.querySelector(sel)
    if (!root) return { found: false, ok: false, issues: [`missing:${sel}`] }
    const rr = root.getBoundingClientRect()
    const issues = []
    const overflowX = root.scrollWidth > root.clientWidth + 2
    if (overflowX) {
      issues.push(`overflowX:${root.scrollWidth}>${root.clientWidth}`)
    }
    const items = Array.from(
      root.querySelectorAll('button, input, select, textarea, [role="radio"], [role="switch"], a')
    ).filter((el) => {
      const r = el.getBoundingClientRect()
      const s = getComputedStyle(el)
      return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 1 && r.height > 1
    })
    const rects = []
    for (const el of items) {
      const r = el.getBoundingClientRect()
      let left = r.left
      let top = r.top
      let right = r.right
      let bottom = r.bottom
      let anc = el.parentElement
      while (anc && anc !== document.body && anc !== document.documentElement) {
        const as = getComputedStyle(anc)
        const clipX = /^(auto|scroll|hidden|clip)$/.test(as.overflowX)
        const clipY = /^(auto|scroll|hidden|clip)$/.test(as.overflowY)
        if (clipX || clipY) {
          const ar = anc.getBoundingClientRect()
          if (clipX) {
            left = Math.max(left, ar.left)
            right = Math.min(right, ar.right)
          }
          if (clipY) {
            top = Math.max(top, ar.top)
            bottom = Math.min(bottom, ar.bottom)
          }
        }
        anc = anc.parentElement
      }
      if (right - left <= 1 || bottom - top <= 1) continue
      rects.push({
        el,
        label: (el.innerText || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 40),
        left,
        top,
        right,
        bottom,
        unclippedRight: r.right
      })
    }
    for (const item of rects) {
      if (item.unclippedRight > rr.right + 2 || item.unclippedRight > window.innerWidth + 1) {
        issues.push(`clippedRight:${item.label}:${Math.round(item.unclippedRight)}>${Math.round(rr.right)}`)
      }
    }
    for (let i = 0; i < rects.length; i++) {
      for (let j = i + 1; j < rects.length; j++) {
        const a = rects[i]
        const b = rects[j]
        if (a.el.contains(b.el) || b.el.contains(a.el)) continue
        const ow = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left))
        const oh = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top))
        if (ow * oh > 4) {
          issues.push(`overlap:${a.label}|${b.label}:${Math.round(ow * oh)}`)
        }
      }
    }
    return {
      found: true,
      ok: issues.length === 0,
      scrollWidth: root.scrollWidth,
      clientWidth: root.clientWidth,
      overflowX,
      itemCount: rects.length,
      issues
    }
  }, containerSel)
}

async function openSettingsGeneralCollab(page) {
  const sec = page.locator('section[data-settings-section="general"]').first()
  if (!(await sec.isVisible().catch(() => false))) {
    const settingsBtn = page.getByRole('button', { name: /^(Settings|设置)$/i }).first()
    await settingsBtn.waitFor({ state: 'visible', timeout: 10000 })
    await settingsBtn.click()
    const generalNav = page.locator('aside button').filter({ hasText: /^(General|常规|通用)$/i }).first()
    if (await generalNav.isVisible().catch(() => false)) {
      await generalNav.click()
    }
    await sec.waitFor({ state: 'visible', timeout: 10000 })
  }
  return sec
}

async function returnFromSettings(page) {
  const backBtn = page.getByRole('button', { name: /^(Back to app|返回应用)$/i }).first()
  if (await backBtn.isVisible().catch(() => false)) {
    await backBtn.click()
    await page.locator('section[data-settings-section]').first().waitFor({ state: 'hidden', timeout: 10000 })
  }
}

function getCollabTrigger(page) {
  return page
    .getByRole('button', { name: /^(Collaboration|协作|协作消息|Collaboration messages)$/i })
    .first()
}

function isConnectedStatusText(text) {
  const normalized = String(text || '').trim()
  return /^(Connected|已连接)$/i.test(normalized)
}

function isDisconnectedStatusText(text) {
  const normalized = String(text || '').trim()
  return /^(Not connected|未连接)$/i.test(normalized)
}

async function openCollabDialog(page) {
  const trigger = getCollabTrigger(page)
  await trigger.waitFor({ state: 'visible', timeout: 10000 })
  await trigger.evaluate((el) => {
    el.setAttribute('data-r93-collab-trigger', '1')
  })
  await trigger.click()
  const dlg = page.getByRole('dialog').first()
  await dlg.waitFor({ state: 'visible', timeout: 10000 })
  return dlg
}

async function closeDialogVerifyFocus(page) {
  await page.keyboard.press('Escape')
  await page.getByRole('dialog').first().waitFor({ state: 'hidden', timeout: 8000 })
  await delay(100)
  return await page.evaluate(() => {
    const active = document.activeElement
    return Boolean(active && active.getAttribute('data-r93-collab-trigger') === '1')
  })
}

async function connectExistingService(sec, baseUrl, token) {
  const existingRadio = sec.getByRole('radio', { name: /Connect an existing service|连接已有服务/i }).first()
  const existingBtn = sec.getByRole('button', { name: /Connect an existing service|连接已有服务/i }).first()
  if (await existingRadio.isVisible().catch(() => false)) {
    await existingRadio.click()
  } else {
    await existingBtn.click()
  }
  await sec.getByLabel(/Service address|服务地址/i).fill(baseUrl)
  await sec.getByLabel(/Connection key|连接密钥/i).fill(token)
  await sec.getByRole('button', { name: /^(Connect|连接)$/i }).first().click()
  await sec.getByText(/^(Connected|已连接)$/i).first().waitFor({ state: 'visible', timeout: 15000 })
}

async function main() {
  const { startLoopbackAcsCore, cleanupAllAcsCores } = await import(pathToFileURL(acsHarnessPath).href)
  const tempBase = fs.mkdtempSync(path.join(os.tmpdir(), 'porpita-r93-'))
  const summary = {
    mode: isBaseline ? 'baseline' : 'strict',
    source,
    acRoot,
    outputDir,
    findings: [],
    checks: {},
    captures: []
  }

  let core = null
  let instZh = null
  let instEn = null

  try {
    core = await startLoopbackAcsCore({ mode: 'full', agentCollabRoot: acRoot })
    const pid = core.info.project_id

    // =========================================================================
    // Phase 1: Chinese ('zh') F05 Sync, Copy Unification & F06 UI Completeness
    // =========================================================================
    instZh = await launchIsolatedApp(tempBase, 'zh-run', { locale: 'zh', theme: 'dark' })
    await setWindowSize(instZh, 1280, 800)

    // 1. Pre-connect Collaboration Dialog copy & Escape focus restoration
    const dlgEmpty = await openCollabDialog(instZh.page)
    const emptyInfo = await dlgEmpty.evaluate((el) => {
      const sel = el.querySelector('select')
      const status = el.querySelector('[role="status"]')
      return {
        selectAriaLabel: sel ? sel.getAttribute('aria-label') || '' : '',
        selectText: sel ? (sel.innerText || '').trim() : '',
        statusText: status ? (status.innerText || '').trim() : '',
        dialogText: (el.innerText || '').trim()
      }
    })
    const emptyCopyCheck = {
      ...emptyInfo,
      noLegacyWorkspacePlaceholder: !/尚未连接工作区/.test(emptyInfo.selectText),
      hasCollabProjectCopy: /协作项目/.test(`${emptyInfo.selectAriaLabel} ${emptyInfo.selectText}`)
    }
    summary.captures.push(
      await captureScreen(instZh, 'r93-f05-collab-empty-zh-1280', { emptyCopyCheck })
    )
    const emptyEscapeFocusRestored = await closeDialogVerifyFocus(instZh.page)
    summary.checks.emptyCopyCheck = { ...emptyCopyCheck, emptyEscapeFocusRestored }
    if (!emptyCopyCheck.noLegacyWorkspacePlaceholder || !emptyCopyCheck.hasCollabProjectCopy) {
      summary.findings.push('F05 zh pre-connect copy still uses legacy 工作区 instead of 协作项目')
    }
    if (!emptyEscapeFocusRestored) {
      summary.findings.push('O/K pre-connect Collaboration Dialog Escape did not restore focus')
    }

    // 2. Settings -> General -> Collaboration 600x400 narrow responsive form layout
    const secZh = await openSettingsGeneralCollab(instZh.page)
    const existingRadio = secZh.getByRole('radio', { name: /Connect an existing service|连接已有服务/i }).first()
    if (await existingRadio.isVisible().catch(() => false)) {
      await existingRadio.click()
    } else {
      await secZh.getByRole('button', { name: /Connect an existing service|连接已有服务/i }).first().click()
    }
    await secZh.getByLabel(/Service address|服务地址/i).fill(core.baseUrl)
    await secZh.getByLabel(/Connection key|连接密钥/i).fill(core.tokens.client)

    await setWindowSize(instZh, 600, 400)
    const collabSettingsCard = secZh.locator('form').locator('..').first()
    await collabSettingsCard.evaluate((el) => {
      el.setAttribute('data-r93-collab-settings', '1')
    })
    await collabSettingsCard.scrollIntoViewIfNeeded()
    const settingsGeo600 = await measureContainerGeometry(
      instZh.page,
      '[data-r93-collab-settings="1"]'
    )
    summary.captures.push(
      await captureScreen(instZh, 'r93-n01-settings-collab-600', { settingsGeo600 })
    )
    summary.checks.settingsGeo600 = settingsGeo600
    if (!settingsGeo600.ok) {
      summary.findings.push(`Settings 600x400 collaboration geometry failed: ${settingsGeo600.issues.join(', ')}`)
    }

    // 3. Connect in Settings -> verify Connected -> immediate Titlebar sync
    await setWindowSize(instZh, 1280, 800)
    await secZh.getByRole('button', { name: /^(Connect|连接)$/i }).first().click()
    await secZh.getByText(/^(Connected|已连接)$/i).first().waitFor({ state: 'visible', timeout: 15000 })
    const disconnectBtnVisible = await secZh
      .getByRole('button', { name: /^(Disconnect|断开|断开连接)$/i })
      .first()
      .isVisible()
      .catch(() => false)
    summary.captures.push(
      await captureScreen(instZh, 'r93-n01-settings-connected-zh-1280', { disconnectBtnVisible })
    )

    await returnFromSettings(instZh.page)
    const dlgAfterConnect = await openCollabDialog(instZh.page)
    await delay(300)
    const connectSyncInfo = await dlgAfterConnect.evaluate((el) => {
      const status = el.querySelector('[role="status"]')
      const options = Array.from(el.querySelectorAll('select option')).map((o) => o.textContent || '')
      return {
        statusText: status ? (status.textContent || '').trim() : '',
        options
      }
    })
    const connectSyncedImmediate =
      isConnectedStatusText(connectSyncInfo.statusText) &&
      connectSyncInfo.options.length > 0 &&
      !/尚未连接/.test(connectSyncInfo.options[0] || '')
    await closeDialogVerifyFocus(instZh.page)
    summary.checks.connectSync = { ...connectSyncInfo, disconnectBtnVisible, connectSyncedImmediate }
    if (!connectSyncedImmediate) {
      summary.findings.push(`Primary Settings connect did not immediately sync Titlebar: ${JSON.stringify(connectSyncInfo)}`)
    }

    // 4. Disconnect -> immediate Titlebar sync -> Secondary Reconnect -> immediate Titlebar sync & unread dot
    const secDisc = await openSettingsGeneralCollab(instZh.page)
    await secDisc.getByRole('button', { name: /^(Disconnect|断开|断开连接)$/i }).first().click()
    await secDisc.getByText(/^(Not connected|未连接)$/i).first().waitFor({ state: 'visible', timeout: 10000 })
    await returnFromSettings(instZh.page)

    const dlgAfterDisc = await openCollabDialog(instZh.page)
    await delay(200)
    const discStatus = ((await dlgAfterDisc.locator('[role="status"]').first().textContent()) || '').trim()
    const disconnectSyncedImmediate = isDisconnectedStatusText(discStatus)
    await closeDialogVerifyFocus(instZh.page)
    summary.checks.disconnectSync = { discStatus, disconnectSyncedImmediate }
    if (!disconnectSyncedImmediate) {
      summary.findings.push(`Settings Disconnect did not immediately sync Titlebar: ${discStatus}`)
    }

    // Secondary Reconnect (exact N.general.01 F05 bug check!)
    const secRec = await openSettingsGeneralCollab(instZh.page)
    const reconnectBtn = secRec.getByRole('button', { name: /^(Reconnect|重新连接)$/i }).first()
    await reconnectBtn.waitFor({ state: 'visible', timeout: 10000 })
    await reconnectBtn.click()
    await secRec.getByText(/^(Connected|已连接)$/i).first().waitFor({ state: 'visible', timeout: 15000 })

    await core.peerSend({
      actor: 'peer_b',
      to: core.addresses.client,
      content: 'Loopback peer hello after secondary reconnect needle-r93'
    })

    await returnFromSettings(instZh.page)
    const triggerEl = getCollabTrigger(instZh.page)
    await instZh.page
      .waitForFunction(
        () => {
          const el = document.querySelector('[data-collaboration-unread]')
          return el && Number(el.getAttribute('data-collaboration-unread') || 0) >= 1
        },
        undefined,
        { timeout: 10000 }
      )
      .catch(() => {})
    const unreadDotBeforeOpen = await triggerEl
      .locator('span')
      .first()
      .waitFor({ state: 'visible', timeout: 2000 })
      .then(
        () => true,
        () => false
      )
    const triggerAttrsReconnect = await triggerEl.evaluate((el) => ({
      state: el.getAttribute('data-collaboration-state'),
      unread: el.getAttribute('data-collaboration-unread'),
      notices: el.getAttribute('data-collaboration-notices')
    }))
    const dlgAfterReconnect = await openCollabDialog(instZh.page)
    await delay(600)
    const reconnectSyncInfo = await dlgAfterReconnect.evaluate((el) => {
      const sel = el.querySelector('select')
      const status = el.querySelector('[role="status"]')
      const options = Array.from(el.querySelectorAll('select option')).map((o) => (o.textContent || '').trim())
      const contacts = Array.from(el.querySelectorAll('aside button')).map((b) => (b.textContent || '').trim())
      const titleText = el.querySelector('h2')?.textContent?.trim() || ''
      return {
        titleText,
        selectAriaLabel: sel ? sel.getAttribute('aria-label') || '' : '',
        statusText: status ? (status.textContent || '').trim() : '',
        options,
        contacts
      }
    })
    const reconnectTitlebarSyncedImmediate =
      triggerAttrsReconnect.state === 'connected' &&
      Number(triggerAttrsReconnect.unread || 0) >= 1 &&
      isConnectedStatusText(reconnectSyncInfo.statusText) &&
      reconnectSyncInfo.options.length > 0 &&
      !/尚未连接/.test(reconnectSyncInfo.options[0] || '') &&
      reconnectSyncInfo.contacts.length > 0 &&
      unreadDotBeforeOpen
    summary.captures.push(
      await captureScreen(instZh, 'r93-n01-secondary-reconnect-zh-1280', {
        unreadDotBeforeOpen,
        triggerAttrsReconnect,
        reconnectSyncInfo,
        reconnectTitlebarSyncedImmediate
      })
    )
    summary.checks.secondaryReconnectSync = {
      unreadDotBeforeOpen,
      triggerAttrsReconnect,
      ...reconnectSyncInfo,
      reconnectTitlebarSyncedImmediate
    }
    if (!reconnectTitlebarSyncedImmediate) {
      summary.findings.push(
        `N.general.01 secondary Reconnect did not immediately sync Titlebar status/projects/contacts: ${JSON.stringify(reconnectSyncInfo)}`
      )
    }

    // 5. Contacts selection, Draft rev 0 -> persistence, Attachment upload/download round-trip, Send & Reply
    const peerBtn = dlgAfterReconnect.locator('aside').getByRole('button', { name: /^slot-b$/i }).first()
    await peerBtn.click()
    const composer = dlgAfterReconnect.locator('textarea').first()
    await composer.waitFor({ state: 'visible', timeout: 10000 })

    // Verify server initial draft rev 0 updated_at === null before typing
    const convRes = await core.request(
      'GET',
      `/projects/${pid}/conversations/resolve?with=${encodeURIComponent(core.addresses.peer_b)}`,
      { token: core.tokens.client }
    )
    const cid = convRes.json.conversation_id
    const initialDraft = await core.request('GET', `/projects/${pid}/conversations/${cid}/draft`, {
      token: core.tokens.client
    })

    const draftText = 'Round 93 UI draft persistence check'
    await composer.fill(draftText)
    let savedDraft = null
    for (let i = 0; i < 20; i++) {
      await delay(250)
      const d = await core.request('GET', `/projects/${pid}/conversations/${cid}/draft`, {
        token: core.tokens.client
      })
      if (d.json && d.json.revision >= 1 && d.json.content === draftText) {
        savedDraft = d.json
        break
      }
    }
    await closeDialogVerifyFocus(instZh.page)
    const dlgDraftReload = await openCollabDialog(instZh.page)
    await dlgDraftReload.locator('aside').getByRole('button', { name: /^slot-b$/i }).first().click()
    const reloadedTextarea = dlgDraftReload.locator('textarea').first()
    await reloadedTextarea.waitFor({ state: 'visible', timeout: 10000 })
    const reloadedDraftValue = await reloadedTextarea.inputValue()
    const draftOk =
      initialDraft.json?.revision === 0 &&
      initialDraft.json?.updated_at === null &&
      Boolean(savedDraft && savedDraft.updated_at) &&
      reloadedDraftValue === draftText
    summary.checks.draftContract = {
      initialRevision: initialDraft.json?.revision,
      initialUpdatedAt: initialDraft.json?.updated_at,
      savedRevision: savedDraft?.revision ?? null,
      savedUpdatedAt: savedDraft?.updated_at ?? null,
      reloadedDraftValue,
      draftOk
    }
    if (!draftOk) {
      summary.findings.push(`Draft contract/reload failed: ${JSON.stringify(summary.checks.draftContract)}`)
    }

    // Attachment upload + send + reply + download round-trip
    const attFilePath = path.join(tempBase, 'r93-attachment.txt')
    const attPayload = Buffer.from('Round 93 attachment payload bytes\n', 'utf8')
    const attExpectedSha = createHash('sha256').update(attPayload).digest('hex')
    fs.writeFileSync(attFilePath, attPayload)
    await dlgDraftReload.locator('input[type="file"]').first().setInputFiles(attFilePath)
    await dlgDraftReload.getByText('r93-attachment.txt').first().waitFor({ state: 'visible', timeout: 10000 })

    const sendBodyText = 'Round 93 attached message needle-r93'
    await reloadedTextarea.fill(sendBodyText)
    await dlgDraftReload.getByRole('button', { name: /^(Send|发送)$/i }).first().click()
    await dlgDraftReload.locator('article').filter({ hasText: sendBodyText }).first().waitFor({
      state: 'visible',
      timeout: 15000
    })

    // Download attachment & check verified reveal button
    const sentArticle = dlgDraftReload.locator('article').filter({ hasText: sendBodyText }).first()
    const attDlBtn = sentArticle.locator('button').filter({ hasText: 'r93-attachment.txt' }).first()
    await attDlBtn.click()
    const revealSavedBtn = sentArticle
      .getByRole('button', { name: /Show saved file in folder|在文件夹中显示已保存文件/i })
      .first()
    const attachmentDownloadVerified = await revealSavedBtn
      .waitFor({ state: 'visible', timeout: 10000 })
      .then(
        () => true,
        () => false
      )

    // Linked reply on peer's initial hello
    const peerArticle = dlgDraftReload
      .locator('article')
      .filter({ hasText: 'Loopback peer hello' })
      .first()
    await peerArticle.getByRole('button', { name: /^(Reply|回复)$/i }).first().click()
    await reloadedTextarea.fill('Linked reply message needle-r93')
    await dlgDraftReload.getByRole('button', { name: /^(Send|发送)$/i }).first().click()
    const linkedReplyArticle = dlgDraftReload
      .locator('article')
      .filter({ hasText: 'Linked reply message needle-r93' })
      .first()
    const linkedReplyRendered = await linkedReplyArticle
      .waitFor({ state: 'visible', timeout: 30000 })
      .then(
        () => true,
        () => false
      )
    if (linkedReplyRendered) {
      await linkedReplyArticle.scrollIntoViewIfNeeded().catch(() => {})
    }

    summary.captures.push(
      await captureScreen(instZh, 'r93-k03-compose-attach-delivery-zh-1280', {
        attachmentExpectedSha: attExpectedSha,
        attachmentDownloadVerified,
        linkedReplyRendered
      })
    )
    summary.checks.composeAndAttachment = {
      attachmentDownloadVerified,
      linkedReplyRendered
    }
    if (!attachmentDownloadVerified || !linkedReplyRendered) {
      summary.findings.push(
        `Attachment download or linked reply failed: ${JSON.stringify(summary.checks.composeAndAttachment)}`
      )
    }

    // 6. NativeLink + DeliverySummary (native accepted) + CommunicationSource (View execution)
    const bindLinkRes = await core.request('PUT', `/projects/${pid}/native-links/r93-nlink`, {
      token: core.tokens.client,
      headers: { 'Idempotency-Key': 'r93-bind-link' },
      body: core.nativeLinkFixture
    })
    const invokeMsgText = 'Invoke native execution check needle-r93'
    await reloadedTextarea.fill(invokeMsgText)
    await dlgDraftReload.getByRole('button', { name: /^(Send|发送)$/i }).first().click()
    const invokeArticle = dlgDraftReload.locator('article').filter({ hasText: invokeMsgText }).first()
    await invokeArticle.waitFor({ state: 'visible', timeout: 30000 })

    await core.dispatchPending()
    await dlgDraftReload.getByRole('button', { name: /Refresh connection|刷新连接/i }).first().click()
    const nativeAcceptedRendered = await invokeArticle
      .getByText(/Native input accepted|原生输入已接纳/i)
      .first()
      .waitFor({ state: 'visible', timeout: 12000 })
      .then(
        () => true,
        () => false
      )

    await invokeArticle.locator('details summary').first().click()
    const viewExecBtn = invokeArticle
      .getByRole('button', { name: /View execution|查看执行/i })
      .first()
    const viewExecutionVisible = await viewExecBtn
      .waitFor({ state: 'visible', timeout: 8000 })
      .then(
        () => true,
        () => false
      )
    if (viewExecutionVisible) {
      await viewExecBtn.scrollIntoViewIfNeeded().catch(() => {})
    }

    const msgHandleText = ((await invokeArticle.locator('details code').first().textContent()) || '').trim()
    let nativeSourceApiAvailable = false
    if (msgHandleText) {
      const readSrc = await core.request(
        'GET',
        `/projects/${pid}/messages/${encodeURIComponent(msgHandleText)}?include_native_source=true`,
        { token: core.tokens.client }
      )
      nativeSourceApiAvailable = readSrc.status === 200 && readSrc.json?.native_source?.available === true
    }

    summary.captures.push(
      await captureScreen(instZh, 'r93-k04-delivery-source-1280', {
        nativeLinkBoundStatus: bindLinkRes.status,
        nativeAcceptedRendered,
        viewExecutionVisible,
        msgHandleText,
        nativeSourceApiAvailable
      })
    )

    let sourceClickHandled = false
    if (viewExecutionVisible) {
      await viewExecBtn.click()
      for (let i = 0; i < 40; i++) {
        await delay(200)
        const dlgStillOpen = await dlgDraftReload.isVisible().catch(() => false)
        const unavailVisible = await invokeArticle
          .locator('[role="status"]')
          .first()
          .isVisible()
          .catch(() => false)
        if (!dlgStillOpen || unavailVisible) {
          sourceClickHandled = true
          break
        }
      }
    }
    summary.checks.deliveryAndSource = {
      nativeLinkBoundStatus: bindLinkRes.status,
      nativeAcceptedRendered,
      viewExecutionVisible,
      nativeSourceApiAvailable,
      sourceClickHandled
    }
    if (!nativeAcceptedRendered || !viewExecutionVisible || !nativeSourceApiAvailable || !sourceClickHandled) {
      summary.findings.push(
        `K.04/R.09 NativeLink or CommunicationSource failed: ${JSON.stringify(summary.checks.deliveryAndSource)}`
      )
    }

    // Ensure dialog open & peer_b selected for Step 7
    let dlgWork = dlgDraftReload
    if (!(await dlgWork.isVisible().catch(() => false))) {
      dlgWork = await openCollabDialog(instZh.page)
      await dlgWork.locator('aside').getByRole('button', { name: /^slot-b$/i }).first().click()
      await dlgWork.locator('textarea').first().waitFor({ state: 'visible', timeout: 10000 })
    }

    // 7. Message Search hits + Search error alert (revoked token -> restored token)
    const searchInput = dlgWork.getByLabel(/Search messages|搜索消息/i).first()
    await searchInput.fill('needle-r93')
    await searchInput.press('Enter')
    const backBtn = dlgWork.getByRole('button', { name: /Back to conversation|返回会话/i }).first()
    await backBtn.waitFor({ state: 'visible', timeout: 10000 })
    const hitsCount = await dlgWork.locator('main button p').count()
    summary.captures.push(
      await captureScreen(instZh, 'r93-k02-search-hits-zh-1280', { hitsCount })
    )

    // Revoke token -> trigger search -> verify error alert feedback
    await core.revokeToken('client')
    await searchInput.fill('needle-revoked')
    await searchInput.press('Enter')
    const searchErrorAlert = dlgWork.locator('main [role="alert"]').first()
    const searchErrorAlertVisible = await searchErrorAlert
      .waitFor({ state: 'visible', timeout: 10000 })
      .then(
        () => true,
        () => false
      )
    const searchErrorText = searchErrorAlertVisible
      ? ((await searchErrorAlert.textContent()) || '').trim()
      : ''
    const staleHitsClearedOnSearchError = (await dlgWork.locator('main button p').count()) === 0
    summary.captures.push(
      await captureScreen(instZh, 'r93-r12-search-error-zh-1280', {
        searchErrorAlertVisible,
        searchErrorText,
        staleHitsClearedOnSearchError
      })
    )
    await core.restoreToken('client')
    if (await backBtn.isVisible().catch(() => false)) {
      await backBtn.click()
    }
    await dlgWork.getByRole('button', { name: /Refresh connection|刷新连接/i }).first().click()
    await dlgWork.locator('textarea').first().waitFor({ state: 'visible', timeout: 10000 })
    const searchErrorClearedOnRefresh = !(await dlgWork.locator('main [role="alert"]').first().isVisible().catch(() => false))
    summary.checks.searchFlow = {
      hitsCount,
      searchErrorAlertVisible,
      searchErrorText,
      staleHitsClearedOnSearchError,
      searchErrorClearedOnRefresh
    }
    if (hitsCount < 2 || !searchErrorAlertVisible || !staleHitsClearedOnSearchError || !searchErrorClearedOnRefresh) {
      summary.findings.push(`K.02/R.12 search hits or searchError failed: ${JSON.stringify(summary.checks.searchFlow)}`)
    }

    // 8. Live Notice strip + markSeen + Post-commit fault (503) & PendingInspectionAction recovery
    const emittedNotice = await core.emitNotice({ legacy_null_created_at: false })
    await dlgWork.getByRole('button', { name: /Refresh connection|刷新连接/i }).first().click()
    const dismissNoticeBtn = dlgWork
      .getByRole('button', { name: /^(Dismiss|知道了)$/i })
      .first()
    const noticeUiRendered = await dismissNoticeBtn
      .waitFor({ state: 'visible', timeout: 10000 })
      .then(
        () => true,
        () => false
      )
    const noticesResBefore = await core.request('GET', `/projects/${pid}/notices`, { token: core.tokens.client })
    const noticeApiOk =
      noticesResBefore.status === 200 &&
      Array.isArray(noticesResBefore.json?.items) &&
      noticesResBefore.json.items.some((n) => n.notice_handle === emittedNotice.notice_handle && Boolean(n.created_at))

    await core.setFault({ drop_next_send_response: true })
    const faultMsgText = 'Pending inspection recovery msg r93'
    const workTextarea = dlgWork.locator('textarea').first()
    await workTextarea.waitFor({ state: 'visible', timeout: 10000 })
    await workTextarea.fill(faultMsgText)
    await dlgWork.getByRole('button', { name: /^(Send|发送)$/i }).first().click()

    const inspectBtn = dlgWork
      .getByRole('button', { name: /Inspect original request|核查原请求/i })
      .first()
    const retryBtn = dlgWork
      .getByRole('button', { name: /Retry original request|重试原请求/i })
      .first()
    const pendingInspectVisible = await inspectBtn
      .waitFor({ state: 'visible', timeout: 12000 })
      .then(
        () => true,
        () => false
      )
    const retryOriginalVisible = await retryBtn.isVisible().catch(() => false)
    summary.captures.push(
      await captureScreen(instZh, 'r93-r12-pending-inspection-zh-1280', {
        noticeApiOk,
        noticeUiRendered,
        pendingInspectVisible,
        retryOriginalVisible
      })
    )

    let noticeUiDismissed = false
    let noticeMarkedSeenOnServer = false
    if (noticeUiRendered) {
      await dismissNoticeBtn.click()
      noticeUiDismissed = await dismissNoticeBtn
        .waitFor({ state: 'hidden', timeout: 8000 })
        .then(
          () => true,
          () => false
        )
      await delay(300)
      const noticesResAfter = await core.request('GET', `/projects/${pid}/notices`, { token: core.tokens.client })
      noticeMarkedSeenOnServer = Boolean(
        noticesResAfter.json?.items?.find((n) => n.notice_handle === emittedNotice.notice_handle)?.seen === true
      )
    }

    let stillRetainedAfterReadOnlyInspect = false
    let pendingInspectRecovered = false
    if (pendingInspectVisible) {
      // Read-only inspect without operation_ref stays non-destructive and retains draft/intent
      await inspectBtn.click()
      await delay(500)
      stillRetainedAfterReadOnlyInspect =
        (await workTextarea.inputValue().catch(() => '')) === faultMsgText &&
        (await retryBtn.isVisible().catch(() => false))
      if (await retryBtn.isVisible().catch(() => false)) {
        // Explicit idempotent retry resolves the committed message on the original requestId
        await retryBtn.click()
        pendingInspectRecovered = await inspectBtn
          .waitFor({ state: 'hidden', timeout: 15000 })
          .then(
            () => true,
            () => false
          )
      }
    }
    const faultArticlesCount = await dlgWork.locator('article').filter({ hasText: faultMsgText }).count()
    summary.checks.pendingInspectionAndNotice = {
      noticeApiOk,
      noticeUiRendered,
      noticeUiDismissed,
      noticeMarkedSeenOnServer,
      pendingInspectVisible,
      retryOriginalVisible,
      stillRetainedAfterReadOnlyInspect,
      pendingInspectRecovered,
      faultArticlesCount
    }
    if (
      !noticeApiOk ||
      !noticeUiRendered ||
      !noticeUiDismissed ||
      !noticeMarkedSeenOnServer ||
      !pendingInspectVisible ||
      !retryOriginalVisible ||
      !stillRetainedAfterReadOnlyInspect ||
      !pendingInspectRecovered ||
      faultArticlesCount !== 1
    ) {
      summary.findings.push(
        `K.04/R.12 Notice or PendingInspection recovery failed: ${JSON.stringify(summary.checks.pendingInspectionAndNotice)}`
      )
    }

    // 9. Narrow 600x400 Collaboration Dialog geometry, history readability & Escape return-focus
    await setWindowSize(instZh, 600, 400)
    const dialogGeo600 = await measureContainerGeometry(instZh.page, '[role="dialog"]')
    const dialogViewportCheck = await instZh.page.evaluate(() => {
      const dlg = document.querySelector('[role="dialog"]')
      if (!dlg) return { inside: false, historyHeight: 0 }
      const r = dlg.getBoundingClientRect()
      const hist = dlg.querySelector('[aria-label="Message history"], [aria-label="消息历史"]')
      const hr = hist ? hist.getBoundingClientRect() : null
      return {
        left: Math.round(r.left),
        top: Math.round(r.top),
        right: Math.round(r.right),
        bottom: Math.round(r.bottom),
        historyHeight: hr ? Math.round(hr.height) : 0,
        inside: r.left >= -1 && r.top >= -1 && r.right <= window.innerWidth + 1 && r.bottom <= window.innerHeight + 1
      }
    })
    summary.captures.push(
      await captureScreen(instZh, 'r93-k00-collab-dialog-600', { dialogGeo600, dialogViewportCheck })
    )
    const dialogEscapeFocusRestored = await closeDialogVerifyFocus(instZh.page)
    summary.checks.narrowDialog600 = { dialogGeo600, dialogViewportCheck, dialogEscapeFocusRestored }
    if (
      !dialogGeo600.ok ||
      !dialogViewportCheck.inside ||
      dialogViewportCheck.historyHeight < 64 ||
      !dialogEscapeFocusRestored
    ) {
      summary.findings.push(
        `Narrow 600x400 Collaboration Dialog or Escape focus failed: ${JSON.stringify(summary.checks.narrowDialog600)}`
      )
    }

    await closeIsolatedApp(instZh)
    instZh = null

    // =========================================================================
    // Phase 2: English ('en') Copy Parity & Secondary Reconnect Sync
    // =========================================================================
    instEn = await launchIsolatedApp(tempBase, 'en-run', { locale: 'en', theme: 'dark' })
    await setWindowSize(instEn, 1280, 800)

    const dlgEnEmpty = await openCollabDialog(instEn.page)
    const enEmptyInfo = await dlgEnEmpty.evaluate((el) => {
      const sel = el.querySelector('select')
      return {
        selectAriaLabel: sel ? sel.getAttribute('aria-label') || '' : '',
        selectText: sel ? (sel.innerText || '').trim() : ''
      }
    })
    await closeDialogVerifyFocus(instEn.page)

    const secEn = await openSettingsGeneralCollab(instEn.page)
    await connectExistingService(secEn, core.baseUrl, core.tokens.client)
    await secEn.getByRole('button', { name: /^Disconnect$/i }).first().click()
    await secEn.getByText(/^Not connected$/i).first().waitFor({ state: 'visible', timeout: 10000 })
    await secEn.getByRole('button', { name: /^Reconnect$/i }).first().click()
    await secEn.getByText(/^Connected$/i).first().waitFor({ state: 'visible', timeout: 15000 })
    summary.captures.push(
      await captureScreen(instEn, 'r93-n01-settings-collab-en-1280', { enEmptyInfo })
    )

    await returnFromSettings(instEn.page)
    const dlgEnSync = await openCollabDialog(instEn.page)
    await delay(500)
    const enStatusText = ((await dlgEnSync.locator('[role="status"]').first().textContent()) || '').trim()
    const enContact = dlgEnSync.locator('aside').getByRole('button', { name: /^slot-b$/i }).first()
    if (await enContact.isVisible().catch(() => false)) {
      await enContact.click()
      await delay(300)
    }
    const enCollabProjectCopyOk =
      /Collaboration project/i.test(`${enEmptyInfo.selectAriaLabel} ${enEmptyInfo.selectText}`) &&
      !/^Workspace$/i.test(enEmptyInfo.selectAriaLabel) &&
      !/No workspace connected/i.test(enEmptyInfo.selectText)
    const enReconnectSyncedImmediate = /^Connected$/i.test(enStatusText)
    summary.captures.push(
      await captureScreen(instEn, 'r93-k01-collab-en-1280', {
        enEmptyInfo,
        enStatusText,
        enCollabProjectCopyOk,
        enReconnectSyncedImmediate
      })
    )
    const enEscapeFocusRestored = await closeDialogVerifyFocus(instEn.page)
    summary.checks.enParity = {
      ...enEmptyInfo,
      enStatusText,
      enCollabProjectCopyOk,
      enReconnectSyncedImmediate,
      enEscapeFocusRestored
    }
    if (!enCollabProjectCopyOk || !enReconnectSyncedImmediate || !enEscapeFocusRestored) {
      summary.findings.push(`English F05/F06 parity or reconnect failed: ${JSON.stringify(summary.checks.enParity)}`)
    }

    summary.isolation = instEn.isolation
    fs.writeFileSync(path.join(outputDir, 'run.json'), JSON.stringify(summary, null, 2) + '\n', 'utf8')
    console.log('SUMMARY:', JSON.stringify({ mode: summary.mode, findings: summary.findings, checks: summary.checks }, null, 2))
    if (!isBaseline && summary.findings.length > 0) {
      process.exitCode = 1
    }
  } finally {
    await Promise.race([closeIsolatedApp(instZh).catch(() => {}), delay(8000)])
    await Promise.race([closeIsolatedApp(instEn).catch(() => {}), delay(8000)])
    await Promise.race([cleanupAllAcsCores().catch(() => {}), delay(25000)])
    removeDirBestEffort(tempBase)
  }
}

main()
  .then(() => {
    process.exit(process.exitCode || 0)
  })
  .catch((err) => {
    console.error(err)
    process.exit(1)
  })
