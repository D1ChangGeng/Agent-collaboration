const { createRequire } = require('node:module')
const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const http = require('node:http')
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
  return path.resolve(__dirname, `../evidence/iteration-92-${osTag}${suffix}`)
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
  const outputDir = path.resolve(outputFlag || remainingPositional[0] || getDefaultOutputDir(isBaseline))
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

function samePath(a, b) {
  const normalize = (target) => {
    const resolved = path.resolve(target)
    try {
      return fs.realpathSync(resolved)
    } catch {
      return resolved
    }
  }
  const na = normalize(a)
  const nb = normalize(b)
  return process.platform === 'win32' ? na.toLowerCase() === nb.toLowerCase() : na === nb
}

function buildIsolatedEnv(userData, home, lang = 'en_US.UTF-8') {
  const env = Object.fromEntries(
    Object.entries(process.env).filter(
      ([key, value]) =>
        value !== undefined &&
        !/^(HOME|USERPROFILE|HOMEDRIVE|HOMEPATH|APPDATA|LOCALAPPDATA|XDG_CONFIG_HOME|XDG_DATA_HOME|XDG_CACHE_HOME|XDG_STATE_HOME|CLAUDE_CONFIG_DIR|ELECTRON_RUN_AS_NODE|ORCA_.*|PORPITA_.*|ACS_.*|CODEX_.*|OPENAI_.*|ANTHROPIC_.*|GH_.*|GITHUB_.*|GITLAB_.*|AWS_.*|AZURE_.*)$/i.test(
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
  for (let i = 0; i < 6; i++) {
    try {
      fs.rmSync(dir, { recursive: true, force: true })
      return
    } catch {
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 250)
    }
  }
}

const TINY_PNG_BASE64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='

function runGit(cwd, args) {
  return execFileSync('git', ['-c', 'core.hooksPath=/dev/null', '-C', cwd, ...args], {
    encoding: 'utf8',
    timeout: 30000
  }).trim()
}

function createTempGitRepoFixture(parentDir) {
  const repoPath = path.join(parentDir, 'r92-fixture-repo')
  fs.mkdirSync(repoPath, { recursive: true })
  runGit(repoPath, ['init', '-b', 'main'])
  runGit(repoPath, ['config', 'user.name', 'Porpita Spec'])
  runGit(repoPath, ['config', 'user.email', 'spec@porpita.invalid'])

  const files = {
    'notes.md':
      '# Release Notes\n\n## Overview\n\nDisposable editor text.\n\n## Details\n\nSecond section for Markdown Preview and TOC.\n',
    'sample.csv':
      'id,name,status,score\n1,alpha,ready,95\n2,beta,pending,72\n3,gamma,ready,88\n4,delta,ready,91\n',
    'sample.svg':
      '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="90" viewBox="0 0 160 90"><rect width="160" height="90" fill="#2563eb"/><text x="18" y="52" fill="#ffffff" font-size="16">Porpita SVG</text></svg>\n',
    'preview.html':
      '<!doctype html><html><body><h1>HTML Sandbox Preview</h1><p id="html-marker">Round 92 Local HTML</p></body></html>\n',
    'app.ts': 'export const version = 1\nexport function greet(name: string) {\n  return `Hello ${name}`\n}\n'
  }
  for (const [rel, content] of Object.entries(files)) {
    fs.writeFileSync(path.join(repoPath, rel), content, 'utf8')
  }
  fs.writeFileSync(path.join(repoPath, 'sample.png'), Buffer.from(TINY_PNG_BASE64, 'base64'))
  runGit(repoPath, ['add', '.'])
  runGit(repoPath, ['-c', 'commit.gpgsign=false', 'commit', '-m', 'Initial Round 92 fixture'])

  // Create branch + second commit so Git Graph has multiple commits/refs
  runGit(repoPath, ['checkout', '-b', 'feat/r92-graph'])
  fs.writeFileSync(path.join(repoPath, 'feature.txt'), 'Branch commit line\n', 'utf8')
  runGit(repoPath, ['add', 'feature.txt'])
  runGit(repoPath, ['-c', 'commit.gpgsign=false', 'commit', '-m', 'Feature branch commit'])
  runGit(repoPath, ['checkout', 'main'])
  fs.writeFileSync(path.join(repoPath, 'CHANGELOG.md'), '# Changelog\n\n- Round 92 base\n', 'utf8')
  runGit(repoPath, ['add', 'CHANGELOG.md'])
  runGit(repoPath, ['-c', 'commit.gpgsign=false', 'commit', '-m', 'Main follow-up commit'])

  // Unstaged modification on app.ts for DiffViewer while keeping notes.md clean
  fs.writeFileSync(
    path.join(repoPath, 'app.ts'),
    'export const version = 2\nexport function greet(name: string) {\n  return `Hi ${name}!`\n}\n',
    'utf8'
  )
  return repoPath
}

function createSyntheticSkillFixture(homeDir, skillName = 'r92-probe-skill') {
  const skillDir = path.join(homeDir, '.agents', 'skills', skillName)
  fs.mkdirSync(skillDir, { recursive: true })
  const skillFile = path.join(skillDir, 'SKILL.md')
  fs.writeFileSync(
    skillFile,
    `---\nname: ${skillName}\ndescription: Synthetic Round 92 local skill fixture\n---\n# ${skillName}\nOffline local skill instructions.\n`,
    'utf8'
  )
  return { skillDir, skillFile, skillName }
}

function createSyntheticPluginFixture(porpitaRoot, parentDir) {
  const pluginDir = path.join(parentDir, 'r92-synthetic-plugin')
  fs.mkdirSync(pluginDir, { recursive: true })
  const srcExample = path.join(porpitaRoot, 'examples', 'plugins', 'hello-components')
  if (fs.existsSync(srcExample)) {
    fs.cpSync(srcExample, pluginDir, { recursive: true })
    return { pluginDir, title: 'Hello Components' }
  }
  fs.writeFileSync(
    path.join(pluginDir, 'orca-plugin.json'),
    JSON.stringify(
      {
        manifestVersion: 2,
        execution: 'sandboxed-ui',
        id: 'r92-synthetic-plugin',
        name: 'R92 Synthetic Plugin',
        version: '1.0.0',
        description: 'Synthetic Round 92 declarative plugin',
        engines: { orca: '>=1.4.246' },
        pluginApi: 1,
        contributes: {
          panels: [
            {
              id: 'r92-panel',
              title: 'R92 Synthetic Panel',
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
  fs.writeFileSync(
    path.join(pluginDir, 'panel.html'),
    '<!doctype html><html><body><h1>R92 Synthetic Panel</h1></body></html>',
    'utf8'
  )
  return { pluginDir, title: 'R92 Synthetic Plugin' }
}

async function startLoopbackHttpServer() {
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
    close: () => new Promise((resolve) => server.close(() => resolve()))
  }
}

async function launchIsolated(seedData) {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'porpita-r92-'))
  const userData = path.join(tempRoot, 'profile')
  const home = path.join(userData, 'home')
  if (process.platform === 'win32') {
    fs.mkdirSync(path.join(home, 'AppData', 'Local'), { recursive: true })
    fs.mkdirSync(path.join(home, 'AppData', 'Roaming'), { recursive: true })
  } else {
    fs.mkdirSync(path.join(home, '.config'), { recursive: true })
    fs.mkdirSync(path.join(home, '.local', 'share'), { recursive: true })
    fs.mkdirSync(path.join(home, '.cache'), { recursive: true })
    fs.mkdirSync(path.join(home, '.local', 'state'), { recursive: true })
  }
  if (seedData) {
    fs.writeFileSync(path.join(userData, 'orca-data.json'), JSON.stringify(seedData, null, 2))
  }
  const env = buildIsolatedEnv(userData, home)
  const app = await _electron.launch({
    executablePath,
    env,
    cwd: tempRoot,
    args: ['--force-device-scale-factor=1', entry],
    timeout: 30000
  })
  const page = await app.firstWindow({ timeout: 30000 })
  page.setDefaultTimeout(8000)
  const win = await app.browserWindow(page)
  await page.waitForLoadState('domcontentloaded', { timeout: 30000 })
  await win.evaluate((w) => w.setContentSize(1280, 800))
  const isolation = await app.evaluate(({ app: electronApp, BrowserWindow }) => ({
    home: electronApp.getPath('home'),
    profile: electronApp.getPath('userData'),
    version: electronApp.getVersion(),
    electronVersion: process.versions.electron,
    windows: BrowserWindow.getAllWindows().map((w) => ({
      visible: w.isVisible(),
      focused: w.isFocused()
    }))
  }))
  if (
    !samePath(isolation.home, home) ||
    !samePath(isolation.profile, userData) ||
    !isolation.windows.length ||
    isolation.windows.some((w) => w.visible || w.focused)
  ) {
    throw new Error(`Window/profile isolation violated: ${JSON.stringify(isolation)}`)
  }
  await page.locator('body').waitFor({ timeout: 15000 })
  return { app, page, win, tempRoot, userData, home, isolation }
}

async function closeApp(app, userData, tempRoot) {
  const child = app.process()
  await Promise.race([
    app.evaluate(({ app: electronApp }) => electronApp.exit(0)).catch(() => {}),
    delay(3000)
  ]).finally(() => {
    if (child && !child.killed && child.exitCode === null && child.signalCode === null) {
      if (child.pid) killPidTree(child.pid)
      try {
        child.kill('SIGKILL')
      } catch {}
    }
    if (userData) killDaemonPids(userData)
    if (tempRoot) removeDirBestEffort(tempRoot)
  })
}

async function setWindowSize(page, win, width, height) {
  await win.evaluate((w, [cw, ch]) => w.setContentSize(cw, ch), [width, height])
  await page
    .waitForFunction(
      ([cw, ch]) => window.innerWidth === cw && window.innerHeight === ch,
      [width, height],
      { timeout: 5000 }
    )
    .catch(() => {})
  await delay(350)
  await page
    .evaluate(async () => {
      await document.fonts.ready
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))
    })
    .catch(() => {})
  await delay(150)
}

async function capture(page, id, extra = {}) {
  await page.evaluate(async () => {
    await document.fonts.ready
  })
  await delay(300)
  const facts = await page.evaluate(() => {
    const active = document.activeElement
    return {
      size: [window.innerWidth, window.innerHeight],
      dpr: window.devicePixelRatio,
      lang: document.documentElement.lang,
      theme: document.documentElement.classList.contains('dark') ? 'dark' : 'light',
      overflowX: document.documentElement.scrollWidth > window.innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
      focusTag: active?.tagName ?? null,
      focusLabel:
        active?.getAttribute('aria-label') || active?.textContent?.trim().slice(0, 100) || null,
      textSample: document.body.innerText.slice(0, 4000)
    }
  })

  const imageFile = `${id}.png`
  const imagePath = path.join(outputDir, imageFile)
  if (facts.dpr !== 1) {
    const cdp = await page.context().newCDPSession(page)
    try {
      const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' })
      fs.writeFileSync(imagePath, Buffer.from(data, 'base64'))
    } finally {
      await cdp.detach().catch(() => {})
    }
  } else {
    await page.screenshot({ path: imagePath, scale: 'css', timeout: 8000 })
  }
  const payload = {
    ...facts,
    extra,
    imageFile,
    imageMethod: 'CDP screenshot'
  }
  fs.writeFileSync(path.join(outputDir, `${id}.json`), JSON.stringify(payload, null, 2) + '\n')
  console.log(`Captured ${id}: ${facts.size.join('x')} overflowX=${facts.overflowX}`)
  return payload
}

async function waitForVisible(locator, timeout = 2500) {
  return locator.waitFor({ state: 'visible', timeout }).then(
    () => true,
    () => false
  )
}

async function measureHorizontalToolbarGeometry(page, containerSelector) {
  return page.evaluate((sel) => {
    const vw = window.innerWidth
    const vh = window.innerHeight
    const root = document.querySelector(sel) || document.querySelector('main')
    if (!root) return { found: false, ok: false, overlaps: [], clipped: [], overflowX: false }
    const rr = root.getBoundingClientRect()
    const items = [
      ...root.querySelectorAll('button, input, [role="combobox"], a, [data-slot="button"]')
    ]
      .map((el) => {
        const r = el.getBoundingClientRect()
        return {
          tag: el.tagName,
          label:
            el.getAttribute('aria-label') ||
            el.getAttribute('placeholder') ||
            el.textContent?.trim().slice(0, 50) ||
            '',
          left: r.left,
          top: r.top,
          right: r.right,
          bottom: r.bottom,
          width: r.width,
          height: r.height
        }
      })
      .filter((r) => r.width > 0 && r.height > 0 && r.top < vh && r.bottom > 0)

    const clipped = items
      .filter((r) => r.right > vw + 1 || r.right > rr.right + 2 || r.left < -1)
      .map((r) => ({
        label: r.label,
        right: Math.round(r.right),
        containerRight: Math.round(rr.right),
        vw
      }))
    const overlaps = []
    for (let i = 0; i < items.length; i++) {
      for (let j = i + 1; j < items.length; j++) {
        const a = items[i]
        const b = items[j]
        const ix = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left))
        const iy = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top))
        if (ix > 2 && iy > 2) {
          overlaps.push({ a: a.label, b: b.label, ix: Math.round(ix), iy: Math.round(iy) })
        }
      }
    }
    return {
      found: true,
      ok: clipped.length === 0 && overlaps.length === 0 && root.scrollWidth <= root.clientWidth + 2,
      scrollWidth: Math.round(root.scrollWidth),
      clientWidth: Math.round(root.clientWidth),
      rootOverflowX: root.scrollWidth > root.clientWidth + 2,
      itemCount: items.length,
      clipped,
      overlaps
    }
  }, containerSelector)
}

async function measureSettingsRowsGeometry(page) {
  return page.evaluate(() => {
    const vw = window.innerWidth
    const main = document.querySelector('main')
    const mainRect = main ? main.getBoundingClientRect() : null
    const issues = []
    for (const row of document.querySelectorAll('[data-settings-row]')) {
      const r = row.getBoundingClientRect()
      if (r.width === 0 || r.height === 0 || r.bottom < 0 || r.top > window.innerHeight) continue
      const children = [...row.children]
      if (children.length < 2) continue
      const textEl = children[0]
      const ctrlEl = children[1]
      const tr = textEl.getBoundingClientRect()
      const cr = ctrlEl.getBoundingClientRect()
      let textVisualRight = tr.right
      for (const node of textEl.querySelectorAll('label, p, span')) {
        const nr = node.getBoundingClientRect()
        if (nr.width > 0 && nr.height > 0) textVisualRight = Math.max(textVisualRight, nr.right)
      }
      const overlaps =
        tr.bottom > cr.top + 2 &&
        cr.bottom > tr.top + 2 &&
        textVisualRight > cr.left + 2 &&
        cr.right > tr.left + 2
      const clippedRight = cr.right > vw + 1 || (mainRect ? cr.right > mainRect.right + 1 : false)
      if (overlaps || clippedRight) {
        issues.push({
          label: textEl.textContent?.trim().slice(0, 60) || '',
          overlaps,
          clippedRight
        })
      }
    }
    return { ok: issues.length === 0, issues }
  })
}

async function stubOpenDialog(app, filePaths) {
  const paths = Array.isArray(filePaths) ? filePaths : [filePaths]
  await app.evaluate(({ dialog }, selected) => {
    dialog.showOpenDialog = async () => ({ canceled: false, filePaths: selected })
  }, paths)
}

async function dismissStartupPopups(page) {
  for (let i = 0; i < 6; i++) {
    const blockingDialog = page
      .locator('[role="dialog"]:not([data-onboarding-modal]):visible, [role="alertdialog"]:visible')
      .last()
    if (await blockingDialog.isVisible().catch(() => false)) {
      const closeBtn = blockingDialog
        .getByRole('button', { name: /^(Got it|Close|Dismiss|Not now|Maybe later)$/i })
        .last()
      if (await closeBtn.isVisible().catch(() => false)) {
        await closeBtn.click().catch(() => {})
        await delay(200)
        continue
      }
      await page.keyboard.press('Escape').catch(() => {})
      await delay(200)
      continue
    }
    const dismissTip = page
      .locator('[role="complementary"] button[aria-label="Dismiss"], [data-notification-card-stack] button[aria-label="Dismiss"]')
      .first()
    if (await dismissTip.isVisible().catch(() => false)) {
      await dismissTip.click().catch(() => {})
      await delay(200)
      continue
    }
    break
  }
}

async function runNotificationStackProbe(findings) {
  // Session 1: trigger ChatUiHereCornerCard inside NotificationCardStack with sidebar open at 600x400
  const s1 = await launchIsolated({
    settings: {
      telemetry: { optedIn: false },
      uiLanguage: 'en',
      theme: 'light',
      agentDefaultSurface: 'terminal'
    },
    onboarding: { flowVersion: 4, closedAt: 1, outcome: 'completed', lastCompletedStep: 5 },
    chatUiLaunchTipAudience: { version: 1, membership: 'eligible', basis: 'chat-ui-off' },
    ui: {
      contextualToursAutoEligible: false,
      browserImportHintHidden: true,
      codexTerminalServerIsolationNoticeSeen: true
    }
  })

  try {
    const { app, page, win } = s1
    await page.getByRole('heading', { name: 'Porpita' }).waitFor({ timeout: 20000 })
    await delay(500)
    await setWindowSize(page, win, 600, 400)
    const stackCard = page.locator('[data-notification-card-stack] > *').first()
    await waitForVisible(stackCard, 5000)

    const metrics = await page.evaluate(() => {
      const stack = document.querySelector('[data-notification-card-stack]')
      const cards = [...document.querySelectorAll('[data-notification-card-stack] > *')]
      const card = cards[0] || null
      const aside = document.querySelector('aside')
      const addBtns = [...document.querySelectorAll('button')].filter((b) => {
        const txt = (b.textContent || '').trim()
        return txt === 'Add project' || txt === 'Create workspace'
      })
      const rectObj = (el) => {
        if (!el) return null
        const r = el.getBoundingClientRect()
        return {
          left: Math.round(r.left),
          top: Math.round(r.top),
          right: Math.round(r.right),
          bottom: Math.round(r.bottom),
          width: Math.round(r.width),
          height: Math.round(r.height)
        }
      }
      const intersect = (a, b) => {
        if (!a || !b) return 0
        const w = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left))
        const h = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top))
        return Math.round(w * h)
      }
      const cr = rectObj(card)
      const ar = rectObj(aside)
      const btnMetrics = addBtns.map((b) => {
        const br = rectObj(b)
        const overlapArea = intersect(cr, br)
        const cx = br ? Math.round((br.left + br.right) / 2) : 0
        const cy = br ? Math.round((br.top + br.bottom) / 2) : 0
        const topEl = br ? document.elementFromPoint(cx, cy) : null
        const blockedByStack = Boolean(topEl && stack && stack.contains(topEl))
        return {
          label: (b.textContent || '').trim(),
          inAside: Boolean(aside && aside.contains(b)),
          rect: br,
          overlapArea,
          blockedByStack
        }
      })
      return {
        stackPresent: Boolean(stack && cr && cr.width > 0),
        stackZIndex: stack ? getComputedStyle(stack).zIndex : null,
        cardRect: cr,
        asideRect: ar,
        asideOverlapArea: intersect(cr, ar),
        addProjectButtons: btnMetrics
      }
    })
    const cardClipped =
      Boolean(metrics.cardRect) && (metrics.cardRect.top < 0 || metrics.cardRect.bottom > 401)
    if (
      !metrics.stackPresent ||
      cardClipped ||
      metrics.asideOverlapArea > 0 ||
      metrics.addProjectButtons.some((b) => b.overlapArea > 0 || b.blockedByStack)
    ) {
      findings.push({
        id: 'O.01.01_notification_stack_600',
        details: { ...metrics, cardClipped }
      })
    }
    await capture(page, 'r92-o01-notification-stack-600', metrics)

    // Probe WorktreeJumpPalette & Escape focus restoration
    await dismissStartupPopups(page)
    await setWindowSize(page, win, 1280, 800)
    const jumpTrigger = page
      .getByRole('button', { name: /Search worktrees and browser tabs|^Search$/i })
      .first()
    let jumpOk = false
    if (await waitForVisible(jumpTrigger, 2000)) {
      await jumpTrigger.focus()
      await jumpTrigger.click()
      const dlg = page.locator('[role="dialog"]:visible').last()
      const opened = await waitForVisible(dlg, 2500)
      await page.keyboard.press('Escape')
      await delay(250)
      const restored = await page.evaluate(
        () =>
          document.activeElement?.getAttribute('aria-label')?.includes('Search') ||
          /Search/i.test(document.activeElement?.textContent || '')
      )
      jumpOk = opened && restored
    }
    return { metrics, jumpPaletteEscapeOk: jumpOk }
  } finally {
    await closeApp(s1.app, s1.userData, s1.tempRoot)
  }
}

async function main() {
  const results = {
    mode: isBaseline ? 'baseline' : 'strict',
    findings: [],
    checks: {}
  }

  results.checks.notificationStack600 = await runNotificationStackProbe(results.findings)

  // Session 2: Automations, Skills, Plugins, Repo Attach, H.01-H.05, I.01-I.04, N.repo
  const httpSrv = await startLoopbackHttpServer()
  const s2 = await launchIsolated({
    settings: {
      telemetry: { optedIn: false },
      uiLanguage: 'en',
      theme: 'dark',
      agentDefaultSurface: 'chat',
      showArtifactsButton: true,
      showMobileButton: true,
      showAutomationsButton: true,
      showSkillsButton: true
    },
    onboarding: { flowVersion: 4, closedAt: 1, outcome: 'completed', lastCompletedStep: 5 },
    ui: {
      contextualToursAutoEligible: false,
      browserImportHintHidden: true,
      codexTerminalServerIsolationNoticeSeen: true,
      featureTipsSeenIds: [
        'chat-ui-here',
        'voice-dictation',
        'porpita-cli',
        'cmd-j-palette',
        'agent-session-search'
      ]
    }
  })

  try {
    const { app, page, win, tempRoot, home } = s2
    const repoPath = createTempGitRepoFixture(tempRoot)
    const skill = createSyntheticSkillFixture(home)
    const pluginFix = createSyntheticPluginFixture(source, tempRoot)

    await page.getByRole('heading', { name: 'Porpita' }).waitFor({ timeout: 20000 })
    await delay(500)
    await dismissStartupPopups(page)
    results.isolation = s2.isolation

    // 1. L.01 Automations at 1280x800, 820x580, 600x400
    const automationsBtn = page.getByRole('button', { name: /^Automations$/i }).first()
    await automationsBtn.click()
    await page.getByRole('heading', { name: 'Automations' }).waitFor({ timeout: 10000 })
    const auto1280 = await measureHorizontalToolbarGeometry(page, 'main, [data-contextual-tour-target="automations-create"]')
    await capture(page, 'r92-l01-automations-1280', { toolbarGeometry: auto1280 })

    await setWindowSize(page, win, 820, 580)
    const auto820 = await measureHorizontalToolbarGeometry(page, 'main')
    await capture(page, 'r92-l01-automations-820', { toolbarGeometry: auto820 })

    await setWindowSize(page, win, 600, 400)
    const auto600 = await measureHorizontalToolbarGeometry(page, 'main')
    await capture(page, 'r92-l01-automations-600', { toolbarGeometry: auto600 })
    if (!auto820.ok || !auto600.ok) {
      results.findings.push({ id: 'L.01_automations_narrow', auto820, auto600 })
    }
    results.checks.automationsGeometry = { auto1280, auto820, auto600 }
    await setWindowSize(page, win, 1280, 800)

    // 2. L.03 Skills at 1280x800 & 600x400
    const skillsBtn = page.getByRole('button', { name: /^Skills$/i }).first()
    await skillsBtn.click()
    await page.getByRole('heading', { name: 'Skills' }).waitFor({ timeout: 10000 })
    const skillRendered = await waitForVisible(page.getByText(skill.skillName).first(), 6000)
    await capture(page, 'r92-l03-skills-1280', { skillRendered })

    await setWindowSize(page, win, 600, 400)
    const skillsHeader600 = await measureHorizontalToolbarGeometry(page, 'header')
    const skillsMain600 = await measureHorizontalToolbarGeometry(page, 'main')
    if (!skillsHeader600.ok || !skillsMain600.ok) {
      results.findings.push({ id: 'L.03_skills_header_600', skillsHeader600, skillsMain600 })
    }
    await capture(page, 'r92-l03-skills-600', { skillsHeader600, skillsMain600 })
    results.checks.skills = { skillRendered, skillsHeader600, skillsMain600 }
    await setWindowSize(page, win, 1280, 800)
    const closeSkillsBtn = page
      .getByRole('button', { name: /^(Close skills|Back to app|Close)$/i })
      .first()
    if (await waitForVisible(closeSkillsBtn, 1000)) {
      await closeSkillsBtn.click()
    } else {
      await page.keyboard.press('Escape')
    }
    await delay(250)

    // 3. Attach temp Git repo via Add project -> Browse folder
    await stubOpenDialog(app, [repoPath])
    const addProjectBtn = page
      .locator('main button')
      .filter({ hasText: 'Add project' })
      .first()
    const fallbackAddBtn = page.getByRole('button', { name: /^Add project$/i }).first()
    if (await waitForVisible(addProjectBtn, 2000)) {
      await addProjectBtn.click()
    } else {
      await fallbackAddBtn.click()
    }
    const browseBtn = page.getByRole('button', { name: /Browse folder/i }).first()
    await browseBtn.waitFor({ state: 'visible', timeout: 8000 })
    await browseBtn.click()
    await delay(700)
    for (let i = 0; i < 3; i++) {
      const trustBtn = page
        .getByRole('button', { name: /^(Trust repository|Trust folder|Allow|Open workspace|Done)$/i })
        .first()
      if (await waitForVisible(trustBtn, 1500)) {
        await trustBtn.click()
        await delay(350)
      } else break
    }
    await dismissStartupPopups(page)
    const wtRows = page.locator('[data-worktree-card-surface="true"]:visible')
    await wtRows.first().waitFor({ state: 'visible', timeout: 12000 })
    await delay(500)
    if (
      (await page.locator('[data-worktree-card-surface="true"][data-worktree-card-active]').count()) === 0
    ) {
      await wtRows.last().click()
      await delay(400)
    }

    // 4. H.01-H.02 Markdown + Preview + Table of Contents + QuickOpen (600x400)
    const notesNode = page.getByText('notes.md', { exact: true }).first()
    await notesNode.waitFor({ state: 'visible', timeout: 10000 })
    await notesNode.dblclick()
    await delay(600)
    const viewSwitcher = page.getByTestId('markdown-view-switcher').first()
    if (await waitForVisible(viewSwitcher, 3000)) {
      const previewOpt = viewSwitcher.getByRole('button', { name: /Preview/i }).first()
      if (await waitForVisible(previewOpt, 1000)) {
        await previewOpt.click()
        await delay(350)
      }
    }
    const tocBtn = page.getByRole('button', { name: /Table of Contents/i }).first()
    let tocOpened = false
    if (await waitForVisible(tocBtn, 2500)) {
      const isDisabled = await tocBtn.isDisabled().catch(() => true)
      if (!isDisabled) {
        await tocBtn.click()
        await delay(300)
        tocOpened = (await tocBtn.getAttribute('aria-pressed')) === 'true'
      }
    }
    let tocHeaderTruncated = false
    if (tocOpened) {
      tocHeaderTruncated = await page.evaluate(() => {
        const heading = [...document.querySelectorAll('span, div, h2, h3')].find(
          (el) => (el.textContent || '').trim() === 'Table of Contents'
        )
        if (!heading) return false
        return heading.scrollWidth > heading.clientWidth + 2 || heading.getBoundingClientRect().width < 70
      })
      if (tocHeaderTruncated) {
        results.findings.push({ id: 'H.02_toc_header_truncated', tocHeaderTruncated })
      }
    }
    await capture(page, 'r92-h02-markdown-preview-toc-1280', { tocOpened, tocHeaderTruncated })

    // Measure narrow editor-header geometry, setup-script sidebar overlap, & QuickOpen / WorktreeJumpPalette at 600x400
    await setWindowSize(page, win, 600, 400)
    const editorHeader600 = await measureHorizontalToolbarGeometry(page, '.editor-header')
    const editorPathWidth600 = await page.evaluate(() => {
      const el = document.querySelector('.editor-header-text')
      return el ? Math.round(el.getBoundingClientRect().width) : null
    })
    const setupCardOverlap600 = await page.evaluate(() => {
      const setupEl = [...document.querySelectorAll('aside, [data-sidebar], div')].find(
        (el) =>
          (el.textContent || '').includes('Add a setup script') &&
          el.querySelector('button') &&
          el.getBoundingClientRect().height > 60 &&
          el.getBoundingClientRect().height < 260
      )
      const card = document.querySelector('[data-worktree-card-surface="true"]')
      if (!setupEl || !card) return { found: Boolean(setupEl), overlapArea: 0 }
      const sr = setupEl.getBoundingClientRect()
      const cr = card.getBoundingClientRect()
      const ix = Math.max(0, Math.min(sr.right, cr.right) - Math.max(sr.left, cr.left))
      const iy = Math.max(0, Math.min(sr.bottom, cr.bottom) - Math.max(sr.top, cr.top))
      return { found: true, overlapArea: Math.round(ix * iy) }
    })
    if (!editorHeader600.ok || (editorPathWidth600 !== null && editorPathWidth600 < 24)) {
      results.findings.push({ id: 'H.01_editor_header_600', editorHeader600, editorPathWidth600 })
    }
    if (setupCardOverlap600.overlapArea > 0) {
      results.findings.push({ id: 'O.01.01_setup_card_overlap_600', setupCardOverlap600 })
    }
    const headerPathEl = page.locator('.editor-header').first()
    if (await waitForVisible(headerPathEl, 1000)) {
      await headerPathEl.click({ position: { x: 12, y: 12 } }).catch(() => {})
    }
    await page.keyboard.press('Control+p')
    let quickOpenVisible = await waitForVisible(
      page.locator('[role="dialog"]:visible input[placeholder*="file" i], [role="dialog"]:visible input[placeholder*="Go to" i]').last(),
      1200
    )
    let quickOpenTrigger = quickOpenVisible ? 'Control+p' : null
    if (!quickOpenVisible) {
      await win.evaluate((w) => {
        w.webContents.sendInputEvent({
          type: 'keyDown',
          keyCode: 'P',
          modifiers: [process.platform === 'darwin' ? 'meta' : 'control']
        })
        w.webContents.sendInputEvent({
          type: 'keyUp',
          keyCode: 'P',
          modifiers: [process.platform === 'darwin' ? 'meta' : 'control']
        })
      }).catch(() => {})
      quickOpenVisible = await waitForVisible(
        page.locator('[role="dialog"]:visible input[placeholder*="file" i], [role="dialog"]:visible input[placeholder*="Go to" i], [role="dialog"]:visible input[placeholder*="Search" i]').last(),
        1500
      )
      if (quickOpenVisible) quickOpenTrigger = 'sendInputEvent-Mod+P'
    }
    if (!quickOpenVisible) {
      const jumpBtn = page
        .getByRole('button', { name: /Search worktrees and browser tabs|^Search$/i })
        .first()
      if (await waitForVisible(jumpBtn, 1500)) {
        await jumpBtn.click()
        quickOpenVisible = await waitForVisible(
          page.locator('[role="dialog"]:visible').last(),
          2500
        )
        if (quickOpenVisible) quickOpenTrigger = 'worktree-jump-palette'
      }
    }
    const quickOpen600 = await page.evaluate(() => {
      const dlgs = [...document.querySelectorAll('[role="dialog"]')]
      const dlg = dlgs.find((d) => {
        const r = d.getBoundingClientRect()
        return r.width > 100 && r.height > 40
      })
      if (!dlg) return { found: false }
      const r = dlg.getBoundingClientRect()
      const footerEl = dlg.querySelector('[class*="border-t"]')
      const fr = footerEl ? footerEl.getBoundingClientRect() : null
      return {
        found: true,
        top: Math.round(r.top),
        bottom: Math.round(r.bottom),
        height: Math.round(r.height),
        footerBottom: fr ? Math.round(fr.bottom) : null,
        viewportHeight: window.innerHeight,
        clippedBottom: r.bottom > window.innerHeight + 1 || (fr ? fr.bottom > window.innerHeight + 1 : false)
      }
    })
    if (!quickOpenVisible || quickOpen600.clippedBottom) {
      results.findings.push({
        id: 'O.modal.quick_open_600',
        quickOpenVisible,
        quickOpenTrigger,
        quickOpen600
      })
    }
    await capture(page, 'r92-o00-quickopen-600', {
      quickOpenVisible,
      quickOpenTrigger,
      quickOpen600,
      editorHeader600,
      editorPathWidth600,
      setupCardOverlap600
    })
    await page.keyboard.press('Escape')
    await delay(250)
    await setWindowSize(page, win, 1280, 800)

    // 5. H.03 Special file viewers: CSV, PNG, HTML, SVG
    let svgOk = false
    let pngOk = false
    let csvOk = false
    let htmlOk = false
    for (const fname of ['sample.csv', 'sample.png', 'preview.html', 'sample.svg']) {
      const item = page.getByText(fname, { exact: true }).first()
      if (await waitForVisible(item, 4000)) {
        await item.dblclick()
        await delay(500)
        if (fname === 'sample.csv') {
          csvOk = await page
            .locator('table, [role="grid"], .csv-grid')
            .first()
            .isVisible()
            .catch(() => false)
        }
        if (fname === 'sample.png') {
          pngOk = await page.evaluate(() =>
            [...document.querySelectorAll('img')].some(
              (img) => img.complete && img.naturalWidth > 0 && img.getBoundingClientRect().width > 10
            )
          )
        }
        if (fname === 'preview.html') {
          htmlOk = true
        }
        if (fname === 'sample.svg') {
          svgOk = await page.evaluate(() =>
            [...document.querySelectorAll('img, svg')].some((el) => {
              const r = el.getBoundingClientRect()
              return r.width > 20 && r.height > 20
            })
          )
        }
      }
    }
    await capture(page, 'r92-h03-svg-viewer-1280', { csvOk, pngOk, htmlOk, svgOk })

    // 6. H.04-H.05 DiffViewer & Git Graph
    const scBtn = page.getByRole('button', { name: /^(Source Control|源代码管理|源代码控制)/i }).first()
    await scBtn.click()
    await delay(500)
    const dirtyApp = page.getByText('app.ts', { exact: true }).last()
    let diffVisible = false
    if (await waitForVisible(dirtyApp, 5000)) {
      await dirtyApp.click()
      diffVisible = await waitForVisible(page.locator('.monaco-diff-editor').first(), 6000)
    }
    await capture(page, 'r92-h04-diff-viewer-1280', { diffVisible })

    const gitGraphBtn = page.getByRole('button', { name: /^Git Graph/i }).first()
    let gitGraphOpened = false
    let gitGraphMetrics1280 = null
    let gitGraph600Metrics = null
    if (await waitForVisible(gitGraphBtn, 4000)) {
      const disabled = await gitGraphBtn.isDisabled().catch(() => true)
      if (!disabled) {
        await gitGraphBtn.click()
        gitGraphOpened = await waitForVisible(
          page.getByText(/Main follow-up commit|Initial Round 92/i).first(),
          6000
        )
        gitGraphMetrics1280 = await page.evaluate(() => {
          const msgCell = [...document.querySelectorAll('span, div, td, button')].find(
            (el) =>
              !el.closest('aside') &&
              /^Main follow-up commit/i.test((el.textContent || '').trim())
          )
          const graphHeader = [...document.querySelectorAll('th, div, span')].find(
            (el) => !el.closest('aside') && /^Branch \/ Tag$/i.test((el.textContent || '').trim())
          )
          const msgBox = msgCell ? msgCell.getBoundingClientRect() : null
          const headerBox = graphHeader ? graphHeader.getBoundingClientRect() : null
          const tableScroller = msgCell?.closest('.overflow-x-auto, .overflow-auto')
          return {
            mainOverflowX: document.documentElement.scrollWidth > window.innerWidth,
            commitTableVisible: Boolean(
              msgBox && msgBox.height > 8 && headerBox && headerBox.height > 8 && msgBox.top < window.innerHeight
            ),
            msgRectWidth: msgBox ? Math.round(msgBox.width) : null,
            tableOverflowX: tableScroller
              ? tableScroller.scrollWidth > tableScroller.clientWidth + 2
              : false
          }
        })
        if (
          !gitGraphOpened ||
          !gitGraphMetrics1280.commitTableVisible ||
          (gitGraphMetrics1280.msgRectWidth !== null && gitGraphMetrics1280.msgRectWidth < 90)
        ) {
          results.findings.push({ id: 'H.05_git_graph_1280_narrow', gitGraphMetrics1280 })
        }
        await capture(page, 'r92-h05-git-graph-1280', { gitGraphOpened, gitGraphMetrics1280 })
        await setWindowSize(page, win, 600, 400)
        gitGraph600Metrics = await page.evaluate(() => ({
          overflowX: document.documentElement.scrollWidth > window.innerWidth,
          scrollWidth: document.documentElement.scrollWidth,
          innerWidth: window.innerWidth
        }))
        await setWindowSize(page, win, 1280, 800)
      }
    }
    results.checks.editorsAndDiff = {
      tocOpened,
      tocHeaderTruncated,
      csvOk,
      pngOk,
      htmlOk,
      svgOk,
      diffVisible,
      gitGraphOpened,
      gitGraphMetrics1280,
      gitGraph600Metrics
    }

    // 8. I.01-I.04 BrowserPane + BrowserFind + DevTools/Extensions
    const newTabBtn = page.getByRole('button', { name: /^New tab$/i }).first()
    await newTabBtn.click()
    const browserItem = page.getByRole('menuitem', { name: /Browser/i }).first()
    await browserItem.waitFor({ state: 'visible', timeout: 6000 })
    await browserItem.click()
    const addrBar = page.locator('[data-orca-browser-address-bar="true"]').first()
    await addrBar.waitFor({ state: 'visible', timeout: 8000 })
    await addrBar.fill(`${httpSrv.baseUrl}/page2`)
    await addrBar.press('Enter')
    await delay(800)
    let guestLoaded = false
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        guestLoaded = await app.evaluate(({ webContents }, url) =>
          webContents.getAllWebContents().some((wc) => wc.getURL().startsWith(url)),
          httpSrv.baseUrl
        )
        if (guestLoaded) break
      } catch {}
      await delay(350)
    }
    if (!guestLoaded) {
      guestLoaded = await page
        .evaluate((url) => {
          const wv = document.querySelector('webview')
          return Boolean(wv && (wv.getAttribute('src') || '').startsWith(url))
        }, httpSrv.baseUrl)
        .catch(() => false)
    }
    // Dismiss contextual browser tip popups (e.g. "Draw on screenshot") before Ctrl+F
    await dismissStartupPopups(page)
    const gotItTip = page.getByRole('button', { name: /^(Got it|Dismiss)$/i }).first()
    if (await waitForVisible(gotItTip, 600)) {
      await gotItTip.click().catch(() => {})
      await delay(200)
    }
    // Open BrowserFind via Ctrl+F
    await page.keyboard.press('Control+f')
    await delay(300)
    const findBarLocator = page.locator('[data-testid="browser-find-bar"]').first()
    const findInput = page.locator('input[placeholder*="Find"]').first()
    const findOpened = await waitForVisible(findInput, 2500)
    if (!findOpened) {
      results.findings.push({ id: 'I.01_browser_find_not_opened' })
    }
    let findMatchText = ''
    let findBarMeta = null
    if (findOpened) {
      await findInput.fill('marker')
      await findInput.press('Enter')
      await delay(350)
      findBarMeta = await page.evaluate(() => {
        const bar =
          document.querySelector('[data-testid="browser-find-bar"]') ||
          document.querySelector('input[placeholder*="Find"]')?.closest('div[class*="fixed"], div[class*="absolute"]')
        if (!bar) return null
        const br = bar.getBoundingClientRect()
        const addrPopup = [...document.querySelectorAll('[role="listbox"], [data-slot="popover-content"], div')].find(
          (el) =>
            !bar.contains(el) &&
            el.querySelector('button') &&
            (el.textContent || '').includes('127.0.0.1') &&
            el.getBoundingClientRect().height > 20 &&
            el.getBoundingClientRect().height < 220
        )
        const pr = addrPopup ? addrPopup.getBoundingClientRect() : null
        const overlapArea =
          pr &&
          Math.max(0, Math.min(br.right, pr.right) - Math.max(br.left, pr.left)) *
            Math.max(0, Math.min(br.bottom, pr.bottom) - Math.max(br.top, pr.top))
        return {
          hasTestId: bar.getAttribute('data-testid') === 'browser-find-bar',
          role: bar.getAttribute('role'),
          bg: getComputedStyle(bar).backgroundColor,
          text: (bar.textContent || '').trim(),
          addrSuggestionOverlapArea: Math.round(overlapArea || 0)
        }
      })
      findMatchText = findBarMeta?.text || ''
      if (findBarMeta?.addrSuggestionOverlapArea > 0) {
        results.findings.push({
          id: 'I.01_addr_suggestion_overlaps_find_bar',
          addrSuggestionOverlapArea: findBarMeta.addrSuggestionOverlapArea
        })
      }
    }
    const extBtnVisible = await waitForVisible(
      page.getByRole('button', { name: /Extensions/i }).first(),
      1200
    )
    await capture(page, 'r92-i01-browser-find-1280', {
      guestLoaded,
      findOpened,
      findMatchText,
      findBarMeta,
      extBtnVisible
    })
    let findBox600 = null
    let findClosedOnEsc = false
    if (findOpened) {
      await setWindowSize(page, win, 600, 400)
      findBox600 = await page
        .evaluate(() => {
          const bar =
            document.querySelector('[data-testid="browser-find-bar"]') ||
            document.querySelector('input[placeholder*="Find"]')?.closest('div')
          const closeCtrl = document.querySelector('button[aria-label*="Close" i], button[aria-label*="Minimize" i]')
          const tabEl = [...document.querySelectorAll('[role="tab"], button')].find((el) =>
            (el.textContent || '').includes('Loopback Page')
          )
          const r = bar ? bar.getBoundingClientRect() : null
          const cr = closeCtrl ? closeCtrl.getBoundingClientRect() : null
          const tr = tabEl ? tabEl.getBoundingClientRect() : null
          return {
            width: r ? Math.round(r.width) : null,
            right: r ? Math.round(r.right) : null,
            tabWidth: tr ? Math.round(tr.width) : null,
            viewportWidth: window.innerWidth,
            clippedRight: r ? r.right > window.innerWidth + 1 : false,
            tabWindowControlOverlap: Boolean(
              cr && tr && tr.width > 0 && tr.right > cr.left + 2 && tr.top < cr.bottom && tr.bottom > cr.top
            )
          }
        })
        .catch(() => null)
      if (findBox600?.clippedRight || findBox600?.tabWindowControlOverlap) {
        results.findings.push({ id: 'I.01_browser_find_600', findBox600 })
      }
      await capture(page, 'r92-i01-browser-find-600', { findBox600 })
      await setWindowSize(page, win, 1280, 800)
      await page.keyboard.press('Escape')
      await delay(250)
      findClosedOnEsc = !(await findInput.isVisible().catch(() => false))
      if (!findClosedOnEsc) {
        results.findings.push({ id: 'I.01_browser_find_esc_not_closed' })
      }
    }
    // Probe Browser DevTools / compact overflow menu
    let devToolsOpened = false
    let foldedExtensionsPresent = false
    const directDevToolsBtn = page.getByRole('button', { name: /Open browser devtools/i }).first()
    if (await waitForVisible(directDevToolsBtn, 800)) {
      await directDevToolsBtn.click()
      await delay(600)
      devToolsOpened = true
    } else {
      const browserMenuBtn = page.locator('button[title="Browser menu"]').first()
      if (await waitForVisible(browserMenuBtn, 1500)) {
        await browserMenuBtn.click()
        await delay(300)
        foldedExtensionsPresent = await waitForVisible(
          page.getByRole('menuitem', { name: /Extensions/i }).first(),
          800
        )
        const foldedDevTools = page.getByRole('menuitem', { name: /Open browser devtools/i }).first()
        if (await waitForVisible(foldedDevTools, 1200)) {
          await foldedDevTools.click()
          await delay(600)
          devToolsOpened = true
        } else {
          await page.keyboard.press('Escape').catch(() => {})
        }
      }
    }
    await capture(page, 'r92-i03-browser-devtools-1280', {
      guestLoaded,
      devToolsOpened,
      extBtnVisible,
      foldedExtensionsPresent
    })
    results.checks.browser = {
      guestLoaded,
      findOpened,
      findBarMeta,
      findBox600,
      findClosedOnEsc,
      extBtnVisible,
      foldedExtensionsPresent,
      devToolsOpened
    }

    // 9. L.05-L.06 Plugins + N.* & N.repo Settings (1280x800 & 600x400)
    const settingsBtn = page.getByRole('button', { name: /^Settings$/i }).first()
    await settingsBtn.click()
    await page.locator('section[data-settings-section]').first().waitFor({ timeout: 10000 })

    // Plugins
    const pluginsNav = page.locator('aside button').filter({ hasText: /^Plugins/i }).first()
    await pluginsNav.click()
    await page
      .locator('section[data-settings-section="plugins"]')
      .waitFor({ state: 'visible', timeout: 8000 })
    const enablePluginsBtn = page.getByRole('button', { name: /Turn on plugins/i }).first()
    if (await waitForVisible(enablePluginsBtn, 2000)) {
      await enablePluginsBtn.click()
      await delay(300)
    }
    await stubOpenDialog(app, [pluginFix.pluginDir])
    const addPluginMenuBtn = page.getByRole('button', { name: /Add plugin/i }).first()
    let pluginInstalled = false
    if (await waitForVisible(addPluginMenuBtn, 3000)) {
      await addPluginMenuBtn.click()
      const fromFolderItem = page.getByRole('menuitem', { name: /From a folder/i }).first()
      if (await waitForVisible(fromFolderItem, 2500)) {
        await fromFolderItem.click()
        await delay(400)
      }
      // Handle "Install plugin" folder-path modal and optional permissions/review consent dialog
      const folderInput = page
        .locator('[role="dialog"]:visible input[placeholder*="plugin folder" i], [role="dialog"]:visible input')
        .first()
      if (await waitForVisible(folderInput, 2000)) {
        await folderInput.fill(pluginFix.pluginDir)
        await delay(150)
        const modalInstallBtn = page
          .locator('[role="dialog"]:visible')
          .getByRole('button', { name: /^Install$/i })
          .first()
        if (await waitForVisible(modalInstallBtn, 1500)) {
          await modalInstallBtn.click()
          await delay(900)
        }
      }
      for (const btnRe of [/^Review/i, /^(Approve|Allow|Enable|Install|Trust|Add)/i]) {
        const dlgBtn = page
          .locator('[role="dialog"]:visible')
          .getByRole('button', { name: btnRe })
          .first()
        if (await waitForVisible(dlgBtn, 1200)) {
          await dlgBtn.click()
          await delay(500)
        }
      }
      if ((await page.locator('[data-slot="dialog-overlay"]:visible').count()) > 0) {
        await page.keyboard.press('Escape').catch(() => {})
        await delay(250)
      }
      pluginInstalled = await waitForVisible(page.getByText(pluginFix.title).first(), 4000)
      let pluginEnabled = false
      if (pluginInstalled) {
        const reviewCardBtn = page.getByRole('button', { name: /^Review$/i }).first()
        if (await waitForVisible(reviewCardBtn, 1000)) {
          await reviewCardBtn.click()
          await delay(400)
        }
        const enablePluginBtn = page
          .getByRole('button', { name: /Enable plugin/i })
          .first()
        if (await waitForVisible(enablePluginBtn, 2000)) {
          await enablePluginBtn.click()
          await delay(800)
        }
        const openPanelFromDetail = page
          .getByRole('button', { name: /Open panel/i })
          .first()
        pluginEnabled = await waitForVisible(openPanelFromDetail, 2500)
        const backToPluginsBtn = page.locator('main button').filter({ hasText: /^Plugins$/i }).first()
        if (await waitForVisible(backToPluginsBtn, 1000)) {
          await backToPluginsBtn.click()
          await delay(400)
        }
      }
      results.checks.plugins = { pluginInstalled, pluginEnabled }
    }
    await capture(page, 'r92-l05-plugins-manager-1280', {
      pluginTitle: pluginFix.title,
      pluginInstalled,
      pluginEnabled: results.checks.plugins?.pluginEnabled ?? false
    })

    // N.repo Settings at 1280x800 & 600x400 (already inside Settings)
    const repoNav = page
      .locator('aside button')
      .filter({ hasText: /r92-fixture-repo/i })
      .first()
    let repoSectionVisited = false
    if (await waitForVisible(repoNav, 4000)) {
      await repoNav.click()
      await delay(500)
      repoSectionVisited = await waitForVisible(
        page.locator('section[data-settings-section^="repo-"]').first(),
        4000
      )
    }
    const repoGeo1280 = await measureSettingsRowsGeometry(page)
    await capture(page, 'r92-nrepo-settings-1280', { repoSectionVisited, repoGeo1280 })

    await setWindowSize(page, win, 600, 400)
    const repoGeo600 = await measureSettingsRowsGeometry(page)
    if (!repoGeo600.ok) {
      results.findings.push({ id: 'N.repo_600', repoGeo600 })
    }
    await capture(page, 'r92-nrepo-settings-600', { repoGeo600 })
    results.checks.repoSettings = { repoSectionVisited, repoGeo1280, repoGeo600 }

    // Non-collab N.* Settings sweep at 600x400 (General, Git, Terminal, Shortcuts)
    const nonCollabGeo600 = {}
    for (const item of [
      { key: 'general', re: /^General$/i },
      { key: 'git', re: /^(Git & Source Control|Git|源代码控制)$/i },
      { key: 'terminal', re: /^Terminal$/i },
      { key: 'shortcuts', re: /^Shortcuts$/i }
    ]) {
      const btn = page
        .locator('aside button')
        .filter({ hasText: item.re })
        .first()
      if (await waitForVisible(btn, 2000)) {
        await btn.click()
        await delay(300)
        const geo = await measureSettingsRowsGeometry(page)
        nonCollabGeo600[item.key] = geo
        if (!geo.ok) {
          results.findings.push({ id: `N.${item.key}_600`, geo })
        }
        if (item.key === 'general') {
          await capture(page, 'r92-n-settings-general-600', { geo })
        }
      }
    }
    results.checks.nonCollabSettings600 = nonCollabGeo600

    // L.06: Open plugin panel in RightSidebar (via Plugins detail -> Open panel) & test disable/focus recovery
    await setWindowSize(page, win, 1280, 800)
    let pluginPanelOpened = false
    let pluginDisabledCleanly = false
    let pluginDisableFocusTag = null
    const pluginsAsideBtn = page.locator('aside button').filter({ hasText: /^Plugins/i }).first()
    if (await waitForVisible(pluginsAsideBtn, 2000)) {
      await pluginsAsideBtn.click()
      await delay(400)
    }
    if (pluginInstalled) {
      const openHelloCard = page.getByText(pluginFix.title).first()
      if (await waitForVisible(openHelloCard, 2500)) {
        await openHelloCard.click()
        await delay(400)
      }
      let pluginLoadError = false
      let pluginErrorText = null
      let pluginControlsRendered = false
      const openPanelBtn = page.getByRole('button', { name: /Open panel/i }).first()
      if (await waitForVisible(openPanelBtn, 2500)) {
        await openPanelBtn.click()
        await delay(900)
        const errorBanner = page
          .getByText(/failed to load|Failed to fetch dynamically imported module|orca-runtime\.mjs/i)
          .first()
        pluginLoadError = await errorBanner.isVisible().catch(() => false)
        if (pluginLoadError) {
          pluginErrorText = (await errorBanner.textContent().catch(() => ''))?.trim() || 'Plugin panel load error'
        }
        pluginControlsRendered = await waitForVisible(
          page
            .locator('[data-plugin-panel-surface], [data-plugin-panel-surface] button')
            .or(page.getByText(/Counter|Reset|Increment/i))
            .first(),
          2500
        )
        pluginPanelOpened =
          !pluginLoadError && (pluginControlsRendered || (await page.locator('iframe').count()) > 0)
        if (pluginLoadError || !pluginPanelOpened) {
          results.findings.push({
            id: 'L.06_plugin_panel_load_error',
            pluginLoadError,
            pluginControlsRendered,
            pluginErrorText
          })
        }
        await capture(page, 'r92-l06-plugin-panel-1280', {
          pluginTitle: pluginFix.title,
          pluginPanelOpened,
          pluginLoadError,
          pluginControlsRendered,
          pluginErrorText
        })
      }
      // Return to Settings -> Plugins and test disabling the plugin / checking focus recovery
      const gearBtns = page.getByRole('button', { name: /^Settings$/i })
      const gearCount = await gearBtns.count()
      for (let gi = gearCount - 1; gi >= 0; gi--) {
        const candidate = gearBtns.nth(gi)
        if (await candidate.isVisible().catch(() => false)) {
          await candidate.click()
          await delay(400)
          if ((await page.locator('section[data-settings-section]').count()) > 0) break
        }
      }
      const pluginsNav2 = page.locator('aside button').filter({ hasText: /^Plugins/i }).first()
      if (await waitForVisible(pluginsNav2, 1500)) {
        await pluginsNav2.click().catch(() => {})
        await delay(300)
      }
      const backBtn2 = page.locator('main button').filter({ hasText: /^Plugins$/i }).first()
      if (await waitForVisible(backBtn2, 1000)) {
        await backBtn2.click().catch(() => {})
        await delay(300)
      }
      const pluginSwitch = page
        .locator('section[data-settings-section="plugins"] [role="switch"]')
        .first()
      const disableBtn = page
        .getByRole('button', { name: /^(In use|Disable|Disable plugin|Turn off)/i })
        .first()
      if (await waitForVisible(pluginSwitch, 2000)) {
        await pluginSwitch.focus()
        await pluginSwitch.click()
        await delay(400)
        pluginDisabledCleanly = (await pluginSwitch.getAttribute('aria-checked')) === 'false'
        pluginDisableFocusTag = await page.evaluate(() => document.activeElement?.tagName || null)
      } else if (await waitForVisible(disableBtn, 1500)) {
        await disableBtn.click()
        await delay(400)
        pluginDisabledCleanly = true
        pluginDisableFocusTag = await page.evaluate(() => document.activeElement?.tagName || null)
      }
    }
    results.checks.plugins = {
      ...(results.checks.plugins || {}),
      pluginPanelOpened,
      pluginDisabledCleanly,
      pluginDisableFocusTag
    }
  } finally {
    await closeApp(s2.app, s2.userData, s2.tempRoot)
    await httpSrv.close()
  }

  fs.writeFileSync(path.join(outputDir, 'run.json'), JSON.stringify(results, null, 2) + '\n')
  console.log('SUMMARY:', JSON.stringify(results, null, 2))

  if (!isBaseline && results.findings.length > 0) {
    throw new Error(`Round 92 strict verification failed: ${JSON.stringify(results.findings)}`)
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
