const { createRequire } = require('node:module')
const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

function isPorpitaCheckout(dir) {
  if (!dir) return false
  const resolved = path.resolve(dir)
  return (
    fs.existsSync(path.join(resolved, 'package.json')) &&
    fs.existsSync(path.join(resolved, 'src/renderer/src/App.tsx'))
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
  return path.resolve(__dirname, `../evidence/iteration-94-${osTag}${suffix}`)
}

function resolveCliOptions(argv) {
  let sourceFlag = null
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
  const remainingPositional = []
  for (const pos of positional) {
    if (!source && isPorpitaCheckout(pos)) {
      source = pos
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

  const resolvedSource = path.resolve(source)
  const outputDir = path.resolve(
    outputFlag || remainingPositional[0] || getDefaultOutputDir(isBaseline)
  )
  return { source: resolvedSource, outputDir, isBaseline }
}

const { source, outputDir, isBaseline } = resolveCliOptions(process.argv.slice(2))
const entry = process.env.PORPITA_SPEC_ENTRY
  ? path.resolve(process.env.PORPITA_SPEC_ENTRY)
  : path.join(source, 'out/main/index.js')
if (!fs.existsSync(entry)) {
  throw new Error(`Porpita built main entry not found at ${entry}. Build out/ before running.`)
}

const load = createRequire(path.join(source, 'package.json'))
const { _electron } = load('playwright')
const executablePath = process.env.PORPITA_SPEC_EXE || load('electron')

fs.mkdirSync(outputDir, { recursive: true })

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const SELECTORS = {
  groupSelector: '[data-workspace-preview-group], [data-workspace-group-selector]',
  tabStrip: '[data-workspace-tab-strip], .terminal-tab-strip',
  workspaceTab: 'button[data-workspace-preview-tab], button[data-workspace-tab]',
  sessionIndex: '[data-session-index]',
  sessionIndexRow: '[data-session-index-row]',
  sessionIndexHistory: '[data-session-index-history]',
  splitLayout: '[data-workspace-preview-chat-layout], [data-workspace-split-layout]',
  explorer: '[data-workspace-preview-explorer], [data-workspace-explorer]',
  explorerScope: '[data-workspace-preview-scope], [data-workspace-explorer-scope]'
}

function buildIsolatedEnv(userData, home, lang = 'en_US.UTF-8') {
  // Deliberately strip VITE_PORPITA_WORKSPACE_PREVIEW and all ORCA_*/PORPITA_* overrides
  const env = Object.fromEntries(
    Object.entries(process.env).filter(
      ([key, value]) =>
        value !== undefined &&
        !/^(HOME|USERPROFILE|HOMEDRIVE|HOMEPATH|APPDATA|LOCALAPPDATA|XDG_CONFIG_HOME|XDG_DATA_HOME|XDG_CACHE_HOME|XDG_STATE_HOME|CLAUDE_CONFIG_DIR|CODEX_HOME|ELECTRON_RUN_AS_NODE|VITE_PORPITA_WORKSPACE_PREVIEW|ORCA_.*|PORPITA_.*|ACS_.*|CODEX_.*|OPENAI_.*|ANTHROPIC_.*|GH_.*|GITHUB_.*|GITLAB_.*|AWS_.*|AZURE_.*)$/i.test(
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
    } catch {}
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
    'right-sidebar',
    'terminal-split',
    'browser-pane',
    'git-diff',
    'settings-navigation'
  ]
  const tourIds = [
    'workspace-board',
    'workspace-agent-sessions',
    'browser',
    'client-hosted-browser',
    'tasks',
    'automations',
    'floating-workspace',
    'workspace-creation',
    'projects-collapse-all'
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
        interactionIds.map((id) => [id, { firstInteractedAt: seenAt, interactionCount: 1 }])
      ),
      contextualToursSeenIds: tourIds,
      contextualToursAutoEligible: false,
      showWelcomeSection: false
    }
  }
}

function runGit(cwd, args) {
  return execFileSync('git', args, {
    cwd,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true
  }).trim()
}

function createTempGitRepo(parentDir, name, files = {}) {
  const repoPath = path.join(parentDir, name)
  fs.mkdirSync(repoPath, { recursive: true })
  runGit(repoPath, ['init', '-b', 'main'])
  runGit(repoPath, ['config', 'user.name', 'Round 94 Observer'])
  runGit(repoPath, ['config', 'user.email', 'round94@example.invalid'])
  const allFiles = {
    'README.md': `# ${name}\n\nFixture repository for Round 94 M3 verification.\n`,
    'notes.md': `# ${name} Notes\n\n- Line 1 baseline\n- Line 2 release check\n`,
    ...files
  }
  for (const [rel, content] of Object.entries(allFiles)) {
    const abs = path.join(repoPath, rel)
    fs.mkdirSync(path.dirname(abs), { recursive: true })
    fs.writeFileSync(abs, content, 'utf8')
  }
  runGit(repoPath, ['add', '-A'])
  runGit(repoPath, ['commit', '-m', `Initial commit for ${name}`])
  return repoPath
}

function createCodexHistoryFixture(homeDir, repoPath, opts = {}) {
  const id = opts.id || '019f9400-1111-7222-8333-444444444494'
  const prompt = opts.prompt || 'Release checklist verification prompt r94'
  const reply = opts.reply || 'The saved release notes for Round 94 are ready.'
  const clock = opts.clock || '09'
  const dir = path.join(homeDir, '.codex', 'sessions', '2026', '09', '04')
  fs.mkdirSync(dir, { recursive: true })
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
        id: 'input-r94',
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
        completed_at_ms: Date.parse(timestamp) + 2000,
        item: { type: 'AgentMessage', id: 'agent-0', content: [{ type: 'text', text: reply }] }
      }
    }
  ]
  fs.writeFileSync(file, records.map((r) => JSON.stringify(r)).join('\n') + '\n', 'utf8')
  return { file, id, prompt, reply }
}

async function launchIsolatedApp(tempBase, profileName, opts = {}) {
  const root = path.join(tempBase, profileName)
  const userData = path.join(root, 'userData')
  const home = path.join(root, 'home')
  fs.mkdirSync(userData, { recursive: true })
  fs.mkdirSync(home, { recursive: true })
  fs.writeFileSync(path.join(home, 'gitconfig'), '[user]\n\tname = R94 Observer\n\temail = r94@example.invalid\n', 'utf8')

  const seed = opts.seed !== false
  const locale = opts.locale || 'en'
  const theme = opts.theme || 'dark'
  if (seed) {
    fs.writeFileSync(
      path.join(userData, 'orca-data.json'),
      JSON.stringify(buildSeedAppData(locale, theme), null, 2),
      'utf8'
    )
  }
  if (typeof opts.setupProfile === 'function') {
    opts.setupProfile({ root, userData, home })
  }

  const langEnv = locale === 'zh' ? 'zh_CN.UTF-8' : 'en_US.UTF-8'
  const env = buildIsolatedEnv(userData, home, langEnv)
  const args = [entry, `--user-data-dir=${userData}`, '--no-sandbox']
  const app = await _electron.launch({ executablePath, args, env, cwd: source })
  try {
    const page = await app.firstWindow({ timeout: 30000 })
    await page.waitForLoadState('domcontentloaded', { timeout: 25000 })
    await page.waitForFunction(
      () => Boolean(document.body && document.body.innerText.trim().length > 0),
      { timeout: 25000 }
    )
    const cdp = await page.context().newCDPSession(page)
    const isolation = await app.evaluate(({ app: electronApp, BrowserWindow }) => ({
      userData: electronApp.getPath('userData'),
      home: electronApp.getPath('home'),
      version: process.versions.electron,
      windows: BrowserWindow.getAllWindows().map((w) => ({
        visible: w.isVisible(),
        focused: w.isFocused()
      }))
    }))
    if (isolation.windows.some((w) => w.visible || w.focused)) {
      throw new Error(`Background launch violation: visible/focused window detected: ${JSON.stringify(isolation)}`)
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

async function quitGracefully(inst, timeoutMs = 30000) {
  const { app, userData } = inst
  const child = app.process()
  const exited = new Promise((resolve) => {
    if (child.exitCode !== null) resolve(child.exitCode)
    else child.once('exit', (code) => resolve(code))
  })
  await app
    .evaluate(({ app: electronApp }) => setTimeout(() => electronApp.quit(), 40))
    .catch(() => {})
  const res = await Promise.race([exited, delay(timeoutMs).then(() => 'timeout')])
  if (res === 'timeout') {
    await closeIsolatedApp(inst)
    throw new Error('Electron graceful quit timed out')
  }
  killDaemonPids(userData)
  return res
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
  await delay(180)
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
  const record = { name, imageFile, window: dom, ...metrics }
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
      if (s.display === 'none' || s.visibility === 'hidden' || r.width <= 1 || r.height <= 1) {
        return false
      }
      let cur = el
      while (cur && cur !== document.body && cur !== document.documentElement) {
        if (getComputedStyle(cur).opacity === '0') return false
        cur = cur.parentElement
      }
      return true
    })
    const rects = []
    for (const el of items) {
      const r = el.getBoundingClientRect()
      let left = r.left
      let top = r.top
      let right = r.right
      let bottom = r.bottom
      let xScrollAncestor = false
      let anc = el.parentElement
      while (anc && anc !== document.body && anc !== document.documentElement) {
        const as = getComputedStyle(anc)
        const clipX = /^(auto|scroll|hidden|clip)$/.test(as.overflowX)
        const clipY = /^(auto|scroll|hidden|clip)$/.test(as.overflowY)
        if (clipX || clipY) {
          if (/^(auto|scroll)$/.test(as.overflowX) && anc.scrollWidth > anc.clientWidth + 2) {
            xScrollAncestor = true
          }
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
        unclippedRight: r.right,
        xScrollAncestor
      })
    }
    for (const item of rects) {
      if (!item.xScrollAncestor && (item.unclippedRight > rr.right + 2 || item.unclippedRight > window.innerWidth + 1)) {
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

async function detectWorkspaceShell(page) {
  return await page.evaluate(() => {
    const previewToggle = [...document.querySelectorAll('button')].some((b) =>
      /Workspaces \(preview\)|工作空间（预览）/i.test(b.textContent || '')
    )
    const hasWorkspaceTabs =
      Boolean(document.querySelector('[data-workspace-preview]')) ||
      Boolean(document.querySelector('[data-workspace-tab-strip]')) ||
      Boolean(document.querySelector('[data-workspace-group-selector], [data-workspace-preview-group]')) ||
      Boolean(document.querySelector('[data-session-index]')) ||
      [...document.querySelectorAll('button')].some((b) =>
        /New workspace|新建工作空间|New work object|新建工作对象/i.test(b.textContent || '')
      )
    const hasSettingsBtn = Boolean(
      [...document.querySelectorAll('button')].find((b) =>
        /^(Settings|设置)$/i.test((b.getAttribute('aria-label') || b.textContent || '').trim())
      )
    )
    const hasCollabBtn = Boolean(
      [...document.querySelectorAll('button')].find((b) =>
        /^(Collaboration|协作|协作消息|Collaboration messages)$/i.test(
          (b.getAttribute('aria-label') || b.textContent || '').trim()
        )
      )
    )
    const hasSidebar = Boolean(document.querySelector('[data-contextual-tour-target="sidebar-navigation"]'))
    return {
      previewToggle,
      hasWorkspaceTabs,
      hasSettingsBtn,
      hasCollabBtn,
      hasSidebar,
      integrated: !previewToggle && hasWorkspaceTabs
    }
  })
}

async function dismissDialogs(page) {
  const dismissPattern =
    /^(Got it|知道了|Dismiss setup scripts|关闭安装脚本|Not now|稍后|Skip tour|Close tour|跳过导览|关闭导览|Dismiss|忽略|Maybe later|以后再说)$/i
  for (let i = 0; i < 5; i++) {
    const dlg = page
      .locator('[role="dialog"]:visible, [role="alertdialog"]:visible')
      .last()
    if (await dlg.isVisible().catch(() => false)) {
      const btn = dlg.getByRole('button', { name: dismissPattern }).first()
      if (await btn.isVisible().catch(() => false)) {
        await btn.click().catch(() => {})
        await delay(200)
        continue
      }
    }
    const pageBtn = page.getByRole('button', { name: dismissPattern }).first()
    if (await pageBtn.isVisible().catch(() => false)) {
      await pageBtn.click().catch(() => {})
      await delay(200)
      continue
    }
    break
  }
}

async function addLocalFolderProject(app, page, folderPath) {
  await app.evaluate(({ dialog }, targetPath) => {
    dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [targetPath] })
  }, folderPath)
  await dismissDialogs(page)
  const addBtns = page.getByRole('button', { name: /^(Add project|添加项目)$/i })
  const count = await addBtns.count()
  await addBtns.nth(count > 1 ? count - 1 : 0).waitFor({ state: 'visible', timeout: 15000 })
  await addBtns.nth(count > 1 ? count - 1 : 0).click()
  const browseBtn = page.getByRole('button', { name: /Browse folder|浏览文件夹/i }).first()
  await browseBtn.waitFor({ state: 'visible', timeout: 8000 })
  await browseBtn.click()
  await delay(500)
  for (let i = 0; i < 3; i++) {
    const confirmBtn = page
      .getByRole('button', {
        name: /^(Open as Folder|作为文件夹打开|Trust repository|信任仓库|Trust folder|信任文件夹|Allow|允许)$/i
      })
      .first()
    if (await confirmBtn.isVisible().catch(() => false)) {
      await confirmBtn.click()
      await delay(400)
      continue
    }
    break
  }
  await dismissDialogs(page)
  await page.getByText(path.basename(folderPath)).first().waitFor({ state: 'visible', timeout: 15000 })
  const worktrees = page.locator('[data-worktree-sidebar] [role="option"][data-worktree-id]')
  if ((await worktrees.count()) > 0) {
    await worktrees.last().click({ timeout: 5000 }).catch(() => {})
    await delay(500)
  }
  await dismissDialogs(page)
}

async function main() {
  const tempBase = fs.mkdtempSync(path.join(os.tmpdir(), 'porpita-r94-'))
  let inst = null
  let instClean = null
  let instZh = null

  const summary = {
    mode: isBaseline ? 'baseline' : 'strict',
    source,
    outputDir,
    findings: [],
    checks: {},
    captures: []
  }

  try {
    const repoA = createTempGitRepo(tempBase, 'r94-repo-alpha', {
      'shared.md': '# Repo Alpha Unique\n\nAlpha file body.\n'
    })
    const repoB = createTempGitRepo(tempBase, 'r94-repo-beta', {
      'shared.md': '# Repo Beta Unique\n\nBeta file body.\n'
    })

    // =========================================================================
    // 1. Empty integrated shell (1280x800) & narrow group selector (360x400)
    // =========================================================================
    inst = await launchIsolatedApp(tempBase, 'en-main', {
      locale: 'en',
      theme: 'dark',
      setupProfile: ({ home }) => {
        createCodexHistoryFixture(home, repoA, {
          prompt: 'Release checklist verification prompt r94',
          reply: 'The saved release notes for Round 94 are ready.'
        })
      }
    })
    await setWindowSize(inst, 1280, 800)
    await dismissDialogs(inst.page)

    const shell1280 = await detectWorkspaceShell(inst.page)
    const bodyText1280 = await inst.page.locator('body').innerText()
    const hasLandingAddProject = /Add project|添加项目/i.test(bodyText1280)
    let generalDeleteProtected = false
    let generalRenameProtected = false
    const groupBtn = inst.page.locator(SELECTORS.groupSelector).first()
    if (await groupBtn.isVisible().catch(() => false)) {
      await groupBtn.click()
      await delay(150)
      const deleteGeneralMenuCount = await inst.page
        .getByRole('menuitem', { name: /Delete.*General|删除.*通用/i })
        .count()
      const deleteGeneralAttrCount = await inst.page
        .locator('[data-workspace-group-delete]')
        .count()
      const renameGeneralAttrCount = await inst.page
        .locator('[data-workspace-group-rename]')
        .count()
      generalDeleteProtected = deleteGeneralMenuCount === 0 && deleteGeneralAttrCount === 0
      generalRenameProtected = renameGeneralAttrCount === 0
      if (!generalRenameProtected) {
        summary.findings.push('General tab group unexpectedly exposed [data-workspace-group-rename]')
      }
      await inst.page.keyboard.press('Escape')
      await delay(150)
    }

    summary.captures.push(
      await captureScreen(inst, 'r94-f07-empty-shell-1280', {
        shell1280,
        hasLandingAddProject,
        generalDeleteProtected
      })
    )
    summary.checks.emptyShell1280 = { shell1280, hasLandingAddProject, generalDeleteProtected }
    if (!shell1280.integrated || shell1280.previewToggle || !shell1280.hasSettingsBtn || !shell1280.hasCollabBtn || !hasLandingAddProject || !generalDeleteProtected) {
      summary.findings.push(
        `Empty integrated shell check failed: ${JSON.stringify(summary.checks.emptyShell1280)}`
      )
    }

    // Narrow 600x400 (minimum window size) selector clamp & overflow check
    await setWindowSize(inst, 600, 400)
    const narrow600Metrics = await inst.page.evaluate((sel) => {
      const el = document.querySelector(sel)
      const r = el ? el.getBoundingClientRect() : null
      const parentR = el && el.parentElement ? el.parentElement.getBoundingClientRect() : null
      const stripWidth = parentR ? parentR.width : window.innerWidth
      return {
        found: Boolean(el),
        width: r ? Math.round(r.width) : 0,
        stripWidth: Math.round(stripWidth),
        maxAllowed: Math.round(Math.min(132, window.innerWidth * 0.31) + 2),
        insideViewport: Boolean(r && r.left >= -1 && r.right <= window.innerWidth + 1),
        overflowX: document.documentElement.scrollWidth > window.innerWidth + 2
      }
    }, SELECTORS.groupSelector)
    summary.captures.push(
      await captureScreen(inst, 'r94-f08-narrow-selector-600', { narrow600Metrics })
    )
    summary.checks.narrowSelector600 = narrow600Metrics
    if (
      !narrow600Metrics.found ||
      narrow600Metrics.width <= 0 ||
      narrow600Metrics.width > narrow600Metrics.maxAllowed ||
      !narrow600Metrics.insideViewport ||
      narrow600Metrics.overflowX
    ) {
      summary.findings.push(`600x400 group selector clamp failed: ${JSON.stringify(narrow600Metrics)}`)
    }

    await setWindowSize(inst, 1280, 800)

    // =========================================================================
    // 2. Add RepoA + RepoB, verify SidebarSessionIndex + Vault handoff + 600x400
    // =========================================================================
    await addLocalFolderProject(inst.app, inst.page, repoA)
    await addLocalFolderProject(inst.app, inst.page, repoB)

    const sessionIndex = inst.page.locator(SELECTORS.sessionIndex).first()
    const sessionIndexVisible = await sessionIndex
      .waitFor({ state: 'visible', timeout: 8000 })
      .then(
        () => true,
        () => false
      )
    let sessionSearchZeroMatchText = ''
    let clearFiltersRestoredEmpty = false
    let historyHandoffVisible = false
    if (sessionIndexVisible) {
      const siInput = sessionIndex.locator('input').first()
      if (await siInput.isVisible().catch(() => false)) {
        await siInput.fill('__no_match_r94__')
        await delay(200)
        const zeroStatus = sessionIndex.locator('[role="status"]').first()
        if (await zeroStatus.isVisible().catch(() => false)) {
          sessionSearchZeroMatchText = (await zeroStatus.innerText()).trim()
        }
        await dismissDialogs(inst.page)
        const clearFiltersBtn = sessionIndex.locator('[data-session-index-clear-filters]').first()
        if (await clearFiltersBtn.isVisible().catch(() => false)) {
          await clearFiltersBtn.click()
          await delay(150)
          clearFiltersRestoredEmpty = (await siInput.inputValue().catch(() => '')) === ''
        }
        if (!clearFiltersRestoredEmpty) {
          summary.findings.push('SidebarSessionIndex [data-session-index-clear-filters] did not clear query')
        }
        await siInput.fill('Release checklist')
        await delay(200)
        const histBtn = sessionIndex.getByRole('button', { name: /Search history|搜索历史/i }).first()
        if (await histBtn.isVisible().catch(() => false)) {
          await histBtn.click()
          historyHandoffVisible = await inst.page
            .getByText(/Release checklist/i)
            .first()
            .waitFor({ state: 'visible', timeout: 8000 })
            .then(
              () => true,
              () => false
            )
        }
        await siInput.fill('')
        await delay(150)
      }
    }
    const worktreeCount = await inst.page
      .locator('[data-worktree-sidebar] [role="option"][data-worktree-id]')
      .count()
    const sessionRowCount = await inst.page.locator(SELECTORS.sessionIndexRow).count()
    const sessionIndexGeo1280 = await measureContainerGeometry(inst.page, SELECTORS.sessionIndex)
    summary.captures.push(
      await captureScreen(inst, 'r94-f07-session-index-1280', {
        sessionIndexVisible,
        worktreeCount,
        sessionRowCount,
        sessionSearchZeroMatchText,
        historyHandoffVisible,
        sessionIndexGeo1280
      })
    )
    summary.checks.sessionIndex1280 = {
      sessionIndexVisible,
      worktreeCount,
      sessionRowCount,
      sessionSearchZeroMatchText,
      historyHandoffVisible,
      sessionIndexGeo1280
    }
    if (!sessionIndexVisible || worktreeCount < 2 || !historyHandoffVisible || !sessionIndexGeo1280.ok) {
      summary.findings.push(
        `SidebarSessionIndex or history handoff failed: ${JSON.stringify(summary.checks.sessionIndex1280)}`
      )
    }

    // Close Right Sidebar so Left Sidebar stays expanded at 600x400 to test SidebarSessionIndex geometry
    const rightExpandedToggle = inst.page
      .locator('[data-workspace-sidebar-toggle="right"][aria-expanded="true"]')
      .first()
    if (await rightExpandedToggle.isVisible().catch(() => false)) {
      await rightExpandedToggle.click()
      await delay(200)
    }

    // 600x400 Sidebar bounded scroll / zero horizontal overflow check
    await setWindowSize(inst, 600, 400)
    const leftNav600 = inst.page.locator('[data-contextual-tour-target="sidebar-navigation"]').first()
    if (!(await leftNav600.isVisible().catch(() => false))) {
      const leftOpenBtn = inst.page.locator('[data-workspace-sidebar-toggle="left"]').first()
      if (await leftOpenBtn.isVisible().catch(() => false)) {
        await leftOpenBtn.click()
        await inst.page.mouse.move(1, 1)
        await inst.page.evaluate(() => document.activeElement && typeof document.activeElement.blur === 'function' && document.activeElement.blur())
        await delay(200)
      }
    }
    const sidebarGeo600 = await measureContainerGeometry(
      inst.page,
      '[data-contextual-tour-target="sidebar-navigation"]'
    )
    const sessionIndexGeo600 = await measureContainerGeometry(inst.page, SELECTORS.sessionIndex)
    const firstWorktreeVisible600 = await inst.page.evaluate(() => {
      const card = document.querySelector('[data-worktree-sidebar] [role="option"][data-worktree-id]')
      const list = card?.closest('[role="listbox"], [data-worktree-list]') || card?.parentElement
      const cr = card ? card.getBoundingClientRect() : null
      const lr = list ? list.getBoundingClientRect() : null
      return {
        found: Boolean(cr),
        cardHeight: cr ? Math.round(cr.height) : 0,
        listHeight: lr ? Math.round(lr.height) : 0
      }
    })
    summary.captures.push(
      await captureScreen(inst, 'r94-f08-session-index-600', {
        sidebarGeo600,
        sessionIndexGeo600,
        firstWorktreeVisible600
      })
    )
    summary.checks.sessionIndex600 = {
      sidebarGeo600,
      sessionIndexGeo600,
      firstWorktreeVisible600
    }
    if (
      !sidebarGeo600.found ||
      !sidebarGeo600.ok ||
      !sessionIndexGeo600.found ||
      !sessionIndexGeo600.ok ||
      firstWorktreeVisible600.listHeight < 40
    ) {
      summary.findings.push(
        `600x400 SidebarSessionIndex geometry failed: ${JSON.stringify(summary.checks.sessionIndex600)}`
      )
    }
    await setWindowSize(inst, 1280, 800)

    // =========================================================================
    // 3. Dual-Pane Split Workspace (1280x800, 640x580 focused, 820x580 restored)
    // =========================================================================
    const newWorkBtn = inst.page.getByRole('button', { name: /^(New work object|新建工作对象)$/i }).first()
    if (await newWorkBtn.isVisible().catch(() => false)) {
      await newWorkBtn.click()
      const newWsItem = inst.page.getByRole('menuitem', { name: /^(New workspace|新建工作空间)$/i }).first()
      if (await newWsItem.isVisible().catch(() => false)) {
        await newWsItem.click()
        await delay(300)
      }
    }
    const sessionCards = inst.page.locator('[data-workspace-preview-session]')
    for (let attempt = 0; attempt < 4; attempt++) {
      if ((await sessionCards.count()) >= 2) break
      const addSessionBtn = inst.page.getByRole('button', { name: /Add session|添加会话/i }).first()
      if (!(await addSessionBtn.isVisible().catch(() => false))) break
      await addSessionBtn.click()
      await delay(250)
      const pickerBtn = inst.page
        .getByRole('button', {
          name: /New chat in active worktree|在当前工作树新建|新建会话/i
        })
        .first()
      if (await pickerBtn.isVisible().catch(() => false)) {
        await pickerBtn.click()
        await delay(300)
      }
    }

    // Ensure Right Sidebar is closed during dual-pane resize & 646px threshold checks
    const rightOpenForSplit = inst.page
      .locator('[data-workspace-sidebar-toggle="right"][aria-expanded="true"]')
      .first()
    let collapsedRightForSplit = false
    if (await rightOpenForSplit.isVisible().catch(() => false)) {
      await rightOpenForSplit.click()
      collapsedRightForSplit = true
      await delay(200)
    }

    const splitLayout = inst.page.locator(SELECTORS.splitLayout).first()
    const split1280Visible = await splitLayout
      .waitFor({ state: 'visible', timeout: 8000 })
      .then(
        () => true,
        () => false
      )
    const splitAttr1280 = split1280Visible ? await splitLayout.getAttribute('data-preview-split') : null
    let dividerArrowShifted = false
    let dividerEscReverted = false
    const separator = splitLayout.getByRole('separator').first()
    if (await separator.isVisible().catch(() => false)) {
      const initialVal = Number.parseFloat((await separator.getAttribute('aria-valuenow')) || '0')
      await separator.focus()
      await inst.page.keyboard.press('ArrowRight')
      await delay(150)
      const shiftedVal = Number.parseFloat((await separator.getAttribute('aria-valuenow')) || '0')
      dividerArrowShifted = shiftedVal > initialVal
      const box = await separator.boundingBox()
      if (box) {
        await inst.page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
        await inst.page.mouse.down()
        await inst.page.mouse.move(box.x + 120, box.y + box.height / 2)
        await inst.page.keyboard.press('Escape')
        await inst.page.mouse.up()
        await delay(120)
        const revertedVal = Number.parseFloat((await separator.getAttribute('aria-valuenow')) || '0')
        dividerEscReverted = Math.abs(revertedVal - shiftedVal) <= 0.5
      }
    }
    summary.captures.push(
      await captureScreen(inst, 'r94-f08-dual-pane-1280', {
        split1280Visible,
        splitAttr1280,
        dividerArrowShifted,
        dividerEscReverted
      })
    )

    // 640x580 below 646px cutoff -> focused (collapse left sidebar so container hits exact 646px cutoff at 820px)
    const leftSidebarNav = inst.page.locator('[data-contextual-tour-target="sidebar-navigation"]').first()
    const leftSidebarToggle = inst.page.locator('[data-workspace-sidebar-toggle="left"]').first()
    let collapsedLeftForSplit = false
    if ((await leftSidebarNav.isVisible().catch(() => false)) && (await leftSidebarToggle.isVisible().catch(() => false))) {
      await leftSidebarToggle.click()
      await inst.page.mouse.move(1, 1)
      await inst.page.evaluate(() => document.activeElement && typeof document.activeElement.blur === 'function' && document.activeElement.blur())
      collapsedLeftForSplit = true
      await delay(200)
    }
    await setWindowSize(inst, 640, 580)
    await delay(250)
    const splitAttr640 = await splitLayout.getAttribute('data-preview-split').catch(() => null)
    summary.captures.push(
      await captureScreen(inst, 'r94-f08-dual-pane-640-focused', { splitAttr640 })
    )

    // 820x580 above 646px cutoff -> restored side-by-side
    await setWindowSize(inst, 820, 580)
    await delay(250)
    const splitAttr820 = await splitLayout.getAttribute('data-preview-split').catch(() => null)
    summary.captures.push(
      await captureScreen(inst, 'r94-f08-dual-pane-820', { splitAttr820 })
    )
    summary.checks.dualPaneSplit = {
      split1280Visible,
      splitAttr1280,
      dividerArrowShifted,
      dividerEscReverted,
      splitAttr640,
      splitAttr820
    }
    if (
      !split1280Visible ||
      splitAttr1280 !== 'side-by-side' ||
      !dividerArrowShifted ||
      !dividerEscReverted ||
      splitAttr640 !== 'focused' ||
      splitAttr820 !== 'side-by-side'
    ) {
      summary.findings.push(`Dual-pane split thresholds failed: ${JSON.stringify(summary.checks.dualPaneSplit)}`)
    }
    await setWindowSize(inst, 1280, 800)
    if (
      collapsedLeftForSplit &&
      !(await leftSidebarNav.isVisible().catch(() => false)) &&
      (await leftSidebarToggle.isVisible().catch(() => false))
    ) {
      await leftSidebarToggle.click()
      await delay(200)
    }

    // =========================================================================
    // 4. Standalone <-> Embedded Fixed-Scope Explorer across RepoA / RepoB
    // =========================================================================
    if (collapsedRightForSplit) {
      const rightOpenBtn = inst.page
        .locator('[data-workspace-sidebar-toggle="right"][aria-expanded="false"]')
        .first()
      if (await rightOpenBtn.isVisible().catch(() => false)) {
        await rightOpenBtn.click()
        await delay(200)
      }
    }
    const sidebarWorktreeCards = inst.page.locator('[data-worktree-sidebar] [role="option"][data-worktree-id]')
    await sidebarWorktreeCards.first().click()
    await delay(250)
    await inst.page.getByRole('button', { name: /^(New work object|新建工作对象)$/i }).first().click()
    await inst.page.getByRole('menuitem', { name: /^(Open Explorer|打开资源管理器)$/i }).first().click()

    const standaloneExplorer = inst.page
      .locator(`${SELECTORS.explorer}[data-presentation="standalone"]`)
      .first()
    const standaloneVisible = await standaloneExplorer
      .waitFor({ state: 'visible', timeout: 8000 })
      .then(
        () => true,
        () => false
      )
    const scopeInitial = standaloneVisible
      ? (await standaloneExplorer.locator(SELECTORS.explorerScope).first().innerText()).trim()
      : ''
    // Switch active worktree to the opposite repo and verify fixed scope stays unchanged
    const oppositeCard = /r94-repo-alpha/i.test(scopeInitial)
      ? sidebarWorktreeCards.last()
      : sidebarWorktreeCards.first()
    await oppositeCard.click()
    await delay(250)
    const activeSwitchedLabel = (await oppositeCard.innerText().catch(() => '')).trim()
    const scopeAfterRepoSwitch = standaloneVisible
      ? (await standaloneExplorer.locator(SELECTORS.explorerScope).first().innerText()).trim()
      : ''
    summary.captures.push(
      await captureScreen(inst, 'r94-f08-explorer-standalone-1280', {
        standaloneVisible,
        scopeInitial,
        activeSwitchedLabel,
        scopeAfterRepoSwitch
      })
    )

    // Move Standalone Explorer -> Embedded Fixed-Scope Explorer
    if (standaloneVisible) {
      await standaloneExplorer.getByRole('button', { name: /Explorer placement|资源管理器位置/i }).first().click()
      await inst.page.getByRole('menuitem', { name: /^(Move to |移动到)/i }).first().click()
    }
    const embeddedExplorer = inst.page
      .locator(`${SELECTORS.explorer}[data-presentation="embedded"]`)
      .first()
    const embeddedVisible = await embeddedExplorer
      .waitFor({ state: 'visible', timeout: 8000 })
      .then(
        () => true,
        () => false
      )
    const scopeEmbedded = embeddedVisible
      ? (await embeddedExplorer.locator(SELECTORS.explorerScope).first().innerText()).trim()
      : ''
    summary.captures.push(
      await captureScreen(inst, 'r94-f08-explorer-embedded-1280', {
        embeddedVisible,
        scopeEmbedded
      })
    )
    summary.checks.fixedExplorerContinuity = {
      standaloneVisible,
      scopeInitial,
      scopeAfterRepoSwitch,
      embeddedVisible,
      scopeEmbedded
    }
    if (
      !standaloneVisible ||
      !embeddedVisible ||
      !scopeInitial ||
      scopeAfterRepoSwitch !== scopeInitial ||
      scopeEmbedded !== scopeInitial
    ) {
      summary.findings.push(
        `Standalone <-> Embedded Fixed Explorer continuity failed: ${JSON.stringify(summary.checks.fixedExplorerContinuity)}`
      )
    }

    // =========================================================================
    // 5. Tab Groups + 20-tab overflow & Esc aborted tab drag
    // =========================================================================
    await groupBtn.click()
    await inst.page.getByRole('menuitem', { name: /New tab group|新建标签组/i }).first().click()
    await inst.page.getByRole('dialog').locator('input').first().fill('Sprint Overflow')
    await inst.page
      .getByRole('dialog')
      .getByRole('button', { name: /^(Create group|Create|创建|确认)$/i })
      .first()
      .click()
    await delay(150)

    await groupBtn.click()
    await delay(150)
    const renameGroupItem = inst.page.locator('[data-workspace-group-rename]').first()
    const customDeleteGroupCount = await inst.page.locator('[data-workspace-group-delete]').count()
    let customGroupRenamed = false
    if (await renameGroupItem.isVisible().catch(() => false)) {
      await renameGroupItem.click()
      await inst.page.getByRole('dialog').locator('input').first().fill('Sprint Renamed')
      await inst.page
        .getByRole('dialog')
        .getByRole('button', { name: /^(Save|保存|Confirm|确认)$/i })
        .first()
        .click()
      await delay(150)
      customGroupRenamed = /Sprint Renamed/i.test(await groupBtn.innerText().catch(() => ''))
    } else {
      await inst.page.keyboard.press('Escape')
      await delay(100)
    }
    if (!customGroupRenamed || customDeleteGroupCount === 0) {
      summary.findings.push(
        `Custom group rename/delete affordance failed: renamed=${customGroupRenamed}, deleteCount=${customDeleteGroupCount}`
      )
    }

    for (let t = 0; t < 20; t++) {
      await inst.page.getByRole('button', { name: /^(New work object|新建工作对象)$/i }).first().click()
      await inst.page.getByRole('menuitem', { name: /^(New workspace|新建工作空间)$/i }).first().click()
    }
    await delay(200)
    const tabOverflowStats = await inst.page.evaluate((stripSel) => {
      const strip = document.querySelector(stripSel)
      return {
        tabCount: document.querySelectorAll('[data-workspace-preview-tab], [data-workspace-tab]').length,
        stripScrollable: strip ? strip.scrollWidth >= strip.clientWidth : false,
        docOverflowX: document.documentElement.scrollWidth > window.innerWidth + 2
      }
    }, SELECTORS.tabStrip)

    // Verify Esc mid-drag on visible tab produces zero side effects
    const visibleDragTab = inst.page.locator(SELECTORS.workspaceTab).last()
    await visibleDragTab.scrollIntoViewIfNeeded().catch(() => {})
    const tabBox = await visibleDragTab.boundingBox()
    let escTabDragUnchanged = false
    if (tabBox) {
      await inst.page.mouse.move(tabBox.x + tabBox.width / 2, tabBox.y + tabBox.height / 2)
      await inst.page.mouse.down()
      await inst.page.mouse.move(tabBox.x + tabBox.width / 2, tabBox.y + 120)
      await inst.page.keyboard.press('Escape')
      await inst.page.mouse.up()
      await inst.page.evaluate(() => window.getSelection()?.removeAllRanges())
      await delay(150)
      const afterEscCount = await inst.page.locator(SELECTORS.workspaceTab).count()
      escTabDragUnchanged = afterEscCount === tabOverflowStats.tabCount
    }
    summary.captures.push(
      await captureScreen(inst, 'r94-f08-tab-groups-overflow-1280', {
        tabOverflowStats,
        escTabDragUnchanged
      })
    )
    summary.checks.tabGroupsOverflow = { ...tabOverflowStats, escTabDragUnchanged }
    if (tabOverflowStats.tabCount < 20 || tabOverflowStats.docOverflowX || !escTabDragUnchanged) {
      summary.findings.push(
        `Tab groups 20-tab overflow or Esc drag guard failed: ${JSON.stringify(summary.checks.tabGroupsOverflow)}`
      )
    }

    // =========================================================================
    // 6. Close Workspace vs Unsaved Editor Tab guard
    // =========================================================================
    let unsavedEditorDialogVisible = false
    let editorCancelKeptDirty = false
    // Activate 'worktree-tool' surface and open Right Sidebar Files -> 'notes.md'
    const showToolsBtn = inst.page.getByRole('button', { name: /Show worktree tools|显示工作树工具/i }).first()
    if (await showToolsBtn.isVisible().catch(() => false)) {
      await showToolsBtn.click()
      await delay(300)
    }
    const rightClosedBtn = inst.page
      .locator('[data-workspace-sidebar-toggle="right"][aria-expanded="false"]')
      .first()
    if (await rightClosedBtn.isVisible().catch(() => false)) {
      await rightClosedBtn.click()
      await delay(250)
    }
    const rightExplorerTab = inst.page
      .locator(
        '[data-right-sidebar-layout] button[aria-label*="Explorer"], [data-right-sidebar-layout] button[aria-label*="Files"], [data-right-sidebar-layout] button[aria-label*="资源管理器"]'
      )
      .first()
    if (
      await rightExplorerTab
        .waitFor({ state: 'visible', timeout: 5000 })
        .then(
          () => true,
          () => false
        )
    ) {
      await rightExplorerTab.click()
      await inst.page.mouse.move(1, 1)
      await inst.page.evaluate(
        () =>
          document.activeElement &&
          typeof document.activeElement.blur === 'function' &&
          document.activeElement.blur()
      )
      await delay(300)
    }
    await dismissDialogs(inst.page)
    const notesItem = inst.page.getByText('notes.md', { exact: true }).first()
    if (await notesItem.waitFor({ state: 'visible', timeout: 5000 }).then(() => true, () => false)) {
      await notesItem.dblclick()
      await delay(600)
    } else {
      await inst.page.keyboard.press(process.platform === 'darwin' ? 'Meta+p' : 'Control+p')
      await delay(250)
      const quickOpenInput = inst.page
        .locator('input[placeholder*="Go to file"], input[placeholder*="转到文件"]')
        .first()
      if (await quickOpenInput.isVisible().catch(() => false)) {
        await quickOpenInput.fill('notes.md')
        await delay(300)
        await inst.page.keyboard.press('Enter')
        await delay(500)
      }
    }
    const cmContent = inst.page
      .locator('.ProseMirror, .tiptap, .cm-content, .monaco-editor textarea')
      .first()
    if (await cmContent.waitFor({ state: 'visible', timeout: 5000 }).then(() => true, () => false)) {
      await inst.page
        .getByText(/r94-repo-.* Notes/i)
        .first()
        .waitFor({ state: 'visible', timeout: 5000 })
        .catch(() => {})
      const firstLine = cmContent.locator('h1, p, .cm-line').first()
      if (await firstLine.isVisible().catch(() => false)) {
        await firstLine.click()
      } else {
        await cmContent.click()
      }
      await inst.page.keyboard.press('End')
      await inst.page.keyboard.type(' Unsaved Round 94 edit check')
      await inst.page
        .getByText(/Unsaved Round 94 edit check/)
        .first()
        .waitFor({ state: 'visible', timeout: 3000 })
        .catch(() => {})
      await delay(250)
      // Hover active notes.md tab so EditorFileTabCloseButton (hidden group-hover:flex when dirty) becomes clickable
      const notesTab = inst.page.locator('[data-tab-id]').filter({ hasText: 'notes.md' }).last()
      if (await notesTab.isVisible().catch(() => false)) {
        await notesTab.hover()
        await delay(150)
      }
      const closeEditorBtn = notesTab
        .locator('button[aria-label^="Close"], button[aria-label^="关闭"], [aria-label^="Close"], [aria-label^="关闭"]')
        .first()
      if (await closeEditorBtn.isVisible().catch(() => false)) {
        await closeEditorBtn.click()
      } else {
        await inst.page.keyboard.press(process.platform === 'darwin' ? 'Meta+w' : 'Control+w')
      }
        const unsavedPrompt = inst.page
          .locator('[role="alertdialog"], [role="dialog"]')
          .filter({ hasText: /Save|Unsaved|Discard|保存|未保存|放弃/i })
          .first()
        unsavedEditorDialogVisible = await unsavedPrompt
          .waitFor({ state: 'visible', timeout: 5000 })
          .then(
            () => true,
            () => false
          )
        summary.captures.push(
          await captureScreen(inst, 'r94-f08-close-unsaved-1280', {
            unsavedEditorDialogVisible
          })
        )
        if (unsavedEditorDialogVisible) {
          const cancelBtn = unsavedPrompt.getByRole('button', { name: /^(Cancel|取消)$/i }).first()
          if (await cancelBtn.isVisible().catch(() => false)) {
            await cancelBtn.click()
            await delay(200)
            editorCancelKeptDirty = await inst.page.getByText(/Unsaved Round 94 edit check/).isVisible().catch(() => false)
          }
        }
    }
    if (!unsavedEditorDialogVisible) {
      summary.captures.push(
        await captureScreen(inst, 'r94-f08-close-unsaved-1280', {
          unsavedEditorDialogVisible,
          editorCancelKeptDirty
        })
      )
    }
    summary.checks.closeUnsaved = { unsavedEditorDialogVisible, editorCancelKeptDirty }
    if (!unsavedEditorDialogVisible) {
      summary.findings.push(
        `Unsaved Editor Tab close guard did not surface cleanly: ${JSON.stringify(summary.checks.closeUnsaved)}`
      )
    }

    await closeIsolatedApp(inst)
    inst = null

    // =========================================================================
    // 7. Cold-Start Layout Persistence + Corrupt porpita-workspaces.json Recovery
    // =========================================================================
    instClean = await launchIsolatedApp(tempBase, 'persist-check', { locale: 'en', theme: 'dark' })
    await setWindowSize(instClean, 1280, 800)
    await addLocalFolderProject(instClean.app, instClean.page, repoA)
    await instClean.page.getByRole('button', { name: /^(New work object|新建工作对象)$/i }).first().click()
    await instClean.page.getByRole('menuitem', { name: /^(New workspace|新建工作空间)$/i }).first().click()
    await delay(400)
    const tabsBeforeQuit = await instClean.page.locator(SELECTORS.workspaceTab).count()
    const cleanExitCode = await quitGracefully(instClean)
    const persistUserData = instClean.userData
    const layoutFile = path.join(persistUserData, 'porpita-workspaces.json')
    const layoutExists = fs.existsSync(layoutFile)
    const layoutParsed = layoutExists ? JSON.parse(fs.readFileSync(layoutFile, 'utf8')) : null
    instClean = null

    // Relaunch same profile (seed=false) -> confirm cold-start restore
    instClean = await launchIsolatedApp(tempBase, 'persist-check', { seed: false })
    await setWindowSize(instClean, 1280, 800)
    await instClean.page.locator(SELECTORS.workspaceTab).first().waitFor({ state: 'visible', timeout: 15000 })
    const tabsAfterRestore = await instClean.page.locator(SELECTORS.workspaceTab).count()
    const coldStartRestored =
      cleanExitCode === 0 &&
      layoutExists &&
      Boolean(layoutParsed && (layoutParsed.version >= 3 || layoutParsed.workspaces)) &&
      tabsAfterRestore >= tabsBeforeQuit
    await quitGracefully(instClean)
    instClean = null

    // Inject corrupt porpita-workspaces.json -> verify recoverable notice & no crash
    fs.writeFileSync(layoutFile, '{ "corrupt": [invalid json', 'utf8')
    instClean = await launchIsolatedApp(tempBase, 'persist-check', { seed: false })
    await setWindowSize(instClean, 1280, 800)
    const corruptShell = await detectWorkspaceShell(instClean.page)
    const corruptNoticeCheck = await instClean.page.evaluate(() => {
      const candidates = Array.from(document.querySelectorAll('[role="status"], [role="alert"]'))
      const recovery = candidates.find((el) =>
        /Could not open saved workspaces|无法打开已保存的工作区|Reset layout|重置布局/i.test(el.textContent || '')
      )
      const hasRetry = Boolean(
        [...document.querySelectorAll('button')].find((b) => /^(Retry|重试)$/i.test((b.textContent || '').trim()))
      )
      const hasResetLayout = Boolean(
        [...document.querySelectorAll('button')].find((b) =>
          /^(Reset layout|重置布局)$/i.test((b.textContent || '').trim())
        )
      )
      return {
        hasNotice: Boolean(recovery),
        noticeText: (recovery?.textContent || '').trim(),
        hasRetry,
        hasResetLayout,
        tabCount: document.querySelectorAll('[data-workspace-preview-tab], [data-workspace-tab]').length
      }
    })
    summary.captures.push(
      await captureScreen(instClean, 'r94-f08-corrupt-layout-recovery-1280', {
        cleanExitCode,
        layoutExists,
        layoutVersion: layoutParsed?.version ?? null,
        tabsBeforeQuit,
        tabsAfterRestore,
        coldStartRestored,
        corruptShell,
        corruptNoticeCheck
      })
    )
    summary.checks.persistenceAndCorruptRecovery = {
      cleanExitCode,
      layoutExists,
      layoutVersion: layoutParsed?.version ?? null,
      tabsBeforeQuit,
      tabsAfterRestore,
      coldStartRestored,
      corruptShell,
      corruptNoticeCheck
    }
    if (
      !coldStartRestored ||
      !corruptShell.integrated ||
      !corruptNoticeCheck.hasNotice ||
      !corruptNoticeCheck.hasRetry ||
      !corruptNoticeCheck.hasResetLayout
    ) {
      summary.findings.push(
        `Cold-start persistence or corrupt layout recovery failed: ${JSON.stringify(summary.checks.persistenceAndCorruptRecovery)}`
      )
    }
    await closeIsolatedApp(instClean)
    instClean = null

    // =========================================================================
    // 8. Simplified Chinese ('zh') integrated shell parity check
    // =========================================================================
    instZh = await launchIsolatedApp(tempBase, 'zh-parity', { locale: 'zh', theme: 'dark' })
    await setWindowSize(instZh, 1280, 800)
    await dismissDialogs(instZh.page)
    const shellZh1280 = await detectWorkspaceShell(instZh.page)
    summary.captures.push(
      await captureScreen(instZh, 'r94-f07-zh-shell-1280', { shellZh1280 })
    )
    summary.checks.zhShellParity = shellZh1280
    if (!shellZh1280.integrated || shellZh1280.previewToggle) {
      summary.findings.push(`Chinese integrated shell parity failed: ${JSON.stringify(shellZh1280)}`)
    }

    summary.isolation = instZh.isolation
    fs.writeFileSync(path.join(outputDir, 'run.json'), JSON.stringify(summary, null, 2) + '\n', 'utf8')
    console.log('SUMMARY:', JSON.stringify({ mode: summary.mode, findings: summary.findings, checks: summary.checks }, null, 2))
    if (!isBaseline && summary.findings.length > 0) {
      process.exitCode = 1
    }
  } finally {
    await Promise.race([closeIsolatedApp(inst).catch(() => {}), delay(8000)])
    await Promise.race([closeIsolatedApp(instClean).catch(() => {}), delay(8000)])
    await Promise.race([closeIsolatedApp(instZh).catch(() => {}), delay(8000)])
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
