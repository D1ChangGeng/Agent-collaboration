import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync
} from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { loadPorpitaDeps, waitForPorpitaBuildReady } from './porpita-deps.mjs'

const ACTIVE_INSTANCES = new Set()
const PENDING_CLEANUP_DIRS = new Set()

function normalizeRealPath(targetPath) {
  let resolved = path.resolve(targetPath)
  try {
    if (existsSync(resolved)) resolved = realpathSync(resolved)
  } catch {
    // Keep resolved path
  }
  return process.platform === 'win32' ? resolved.toLowerCase() : resolved
}

function withTimeout(promise, ms, label) {
  let timer = null
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms)
    })
  ]).finally(() => {
    if (timer) clearTimeout(timer)
  })
}

const SCRUB_EXACT = new Set([
  'HOME',
  'USERPROFILE',
  'HOMEDRIVE',
  'HOMEPATH',
  'APPDATA',
  'LOCALAPPDATA',
  'XDG_CONFIG_HOME',
  'XDG_DATA_HOME',
  'XDG_CACHE_HOME',
  'XDG_STATE_HOME',
  'CLAUDE_CONFIG_DIR',
  'CODEX_HOME',
  'ORCA_CODEX_HOME',
  'ELECTRON_RUN_AS_NODE',
  'VITE_PORPITA_WORKSPACE_PREVIEW',
  'VITE_EXPOSE_STORE'
])

const SCRUB_PREFIXES = [
  'ORCA_',
  'PORPITA_',
  'ACS_',
  'CODEX_',
  'OPENAI_',
  'ANTHROPIC_',
  'GH_',
  'GITHUB_',
  'GITLAB_',
  'AWS_',
  'AZURE_'
]

const FEATURE_TIP_IDS = [
  'chat-ui-here',
  'voice-dictation',
  'porpita-cli',
  'cmd-j-palette',
  'agent-session-search'
]

const FEATURE_INTERACTION_IDS = [
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

const CONTEXTUAL_TOUR_IDS = [
  'workspace-board',
  'browser',
  'tasks',
  'automations',
  'workspace-creation'
]

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export function buildCompletedProfileData({
  locale = 'en',
  theme = 'light',
  reducedMotion = false,
  settings = {},
  ui = {},
  extra = {}
} = {}) {
  const seenTimestamp = Date.parse('2026-01-01T00:00:00.000Z')
  return {
    settings: {
      uiLanguage: locale,
      theme,
      reducedMotion,
      telemetry: {
        optedIn: true,
        installId: '00000000-0000-4000-8000-000000000000',
        existedBeforeTelemetryRelease: false
      },
      ...settings
    },
    onboarding: {
      flowVersion: 4,
      closedAt: 1,
      outcome: 'completed',
      lastCompletedStep: 5
    },
    ui: {
      featureTipsSeenIds: [...FEATURE_TIP_IDS],
      featureInteractions: Object.fromEntries(
        FEATURE_INTERACTION_IDS.map((id) => [id, { firstInteractedAt: seenTimestamp }])
      ),
      contextualToursSeenIds: [...CONTEXTUAL_TOUR_IDS],
      contextualToursAutoEligible: false,
      projectOrderManualDefaultNoticeDismissed: true,
      browserImportHintHidden: true,
      usagePercentageDisplayChangeNoticeDismissed: true,
      statusBarCompactChangeNoticeDismissed: true,
      codexTerminalServerIsolationNoticeSeen: true,
      ...ui
    },
    ...extra
  }
}

export function createIsolatedProfileDirs(existingTempRoot = null) {
  const tempRoot =
    existingTempRoot || path.join(os.tmpdir(), `porpita-e2e-${randomUUID().slice(0, 12)}`)
  const userDataDir = path.join(tempRoot, 'profile')
  const homeDir = path.join(userDataDir, 'home')
  const appDataRoaming = path.join(homeDir, 'AppData', 'Roaming')
  const appDataLocal = path.join(homeDir, 'AppData', 'Local')
  const xdgConfigHome = path.join(homeDir, '.config')
  const xdgDataHome = path.join(homeDir, '.local', 'share')
  const xdgCacheHome = path.join(homeDir, '.cache')
  const xdgStateHome = path.join(homeDir, '.local', 'state')
  for (const dir of [
    appDataRoaming,
    appDataLocal,
    xdgConfigHome,
    xdgDataHome,
    xdgCacheHome,
    xdgStateHome
  ]) {
    mkdirSync(dir, { recursive: true })
  }
  const gitConfigGlobal = path.join(homeDir, 'gitconfig')
  if (!existsSync(gitConfigGlobal)) {
    writeFileSync(
      gitConfigGlobal,
      '[user]\n\tname = Porpita E2E\n\temail = e2e@porpita.invalid\n[init]\n\tdefaultBranch = main\n',
      'utf8'
    )
  }
  return {
    tempRoot,
    userDataDir,
    homeDir,
    appDataRoaming,
    appDataLocal,
    xdgConfigHome,
    xdgDataHome,
    xdgCacheHome,
    xdgStateHome,
    gitConfigGlobal
  }
}

export function seedPorpitaProfile(userDataDir, options = {}) {
  mkdirSync(userDataDir, { recursive: true })
  const dataPath = path.join(userDataDir, 'orca-data.json')
  const payload = buildCompletedProfileData(options)
  writeFileSync(dataPath, JSON.stringify(payload, null, 2) + '\n', 'utf8')
  return dataPath
}

export function scrubElectronEnv({
  userDataDir,
  homeDir,
  appDataRoaming,
  appDataLocal,
  xdgConfigHome,
  xdgDataHome,
  xdgCacheHome,
  xdgStateHome,
  gitConfigGlobal,
  extraEnv = {}
}) {
  const env = {}
  for (const [key, value] of Object.entries(process.env)) {
    if (value === undefined) continue
    const upper = key.toUpperCase()
    if (SCRUB_EXACT.has(upper)) continue
    if (SCRUB_PREFIXES.some((prefix) => upper.startsWith(prefix))) continue
    env[key] = value
  }
  env.HOME = homeDir
  env.USERPROFILE = homeDir
  env.APPDATA = appDataRoaming
  env.LOCALAPPDATA = appDataLocal
  env.XDG_CONFIG_HOME = xdgConfigHome
  env.XDG_DATA_HOME = xdgDataHome
  env.XDG_CACHE_HOME = xdgCacheHome
  env.XDG_STATE_HOME = xdgStateHome
  env.ORCA_BACKGROUND_LAUNCH = '1'
  env.ORCA_E2E_HEADLESS = '1'
  env.ORCA_E2E_USER_DATA_DIR = userDataDir
  env.ORCA_E2E_HOME_DIR = homeDir
  env.GIT_CONFIG_NOSYSTEM = '1'
  env.GIT_CONFIG_GLOBAL = gitConfigGlobal
  env.LANG = 'en_US.UTF-8'
  for (const [k, v] of Object.entries(extraEnv)) {
    if (v === undefined || v === null) delete env[k]
    else env[k] = String(v)
  }
  return env
}

export async function assertAllWindowsHidden(app) {
  const state = await withTimeout(
    app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows().map((w) => ({
        id: w.id,
        visible: w.isVisible(),
        focused: w.isFocused(),
        title: w.getTitle()
      }))
    ),
    15000,
    'assertAllWindowsHidden'
  )
  for (const w of state) {
    assert.equal(w.visible, false, `Window ${w.id} (${w.title}) unexpectedly visible`)
    assert.equal(w.focused, false, `Window ${w.id} (${w.title}) unexpectedly focused`)
  }
  return state
}

export async function setViewportSize(app, page, width, height) {
  const win = await withTimeout(app.browserWindow(page), 15000, 'browserWindow')
  const winId = await withTimeout(win.evaluate((w) => w.id), 10000, 'browserWindowId').catch(() => null)
  for (let attempt = 0; attempt < 3; attempt++) {
    await withTimeout(
      winId !== null
        ? app.evaluate(
            ({ BrowserWindow }, [id, cw, ch]) => {
              const target = BrowserWindow.fromId(id)
              if (target && !target.isDestroyed()) {
                target.setContentSize(cw, ch)
              }
            },
            [winId, width, height]
          )
        : win.evaluate((w, [cw, ch]) => w.setContentSize(cw, ch), [width, height]),
      10000,
      'setContentSize'
    )
    try {
      await page.waitForFunction(
        ([cw, ch]) => window.innerWidth === cw && window.innerHeight === ch,
        [width, height],
        { timeout: 8000 }
      )
      return
    } catch (err) {
      const measured = await withTimeout(
        page.evaluate(() => `${window.innerWidth}x${window.innerHeight}`),
        5000,
        'measureViewport'
      ).catch(() => 'unknown')
      if (measured === `${width}x${height}`) {
        return
      }
      if (attempt === 2) {
        throw new Error(`Viewport ${width}x${height} did not settle (got ${measured})`, {
          cause: err
        })
      }
      await sleep(200)
    }
  }
}

export async function stubOpenDialog(app, filePaths) {
  const paths = Array.isArray(filePaths) ? filePaths : [filePaths]
  await withTimeout(
    app.evaluate(({ dialog }, selected) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: selected })
    }, paths),
    10000,
    'stubOpenDialog'
  )
}

function isTransientLaunchError(err) {
  const msg = String(err?.message || err || '')
  return /ENOENT|Cannot find module|firstWindow|waitForLoadState|Timeout.*exceeded|Target page, context or browser has been closed|Renderer root did not mount|out[\\/]/i.test(
    msg
  )
}

export async function launchElectronApp({
  porpitaRoot,
  tempRoot = null,
  seedCompletedOnboarding = true,
  profileOptions = {},
  width = 1280,
  height = 800,
  scaleFactor = 1,
  extraEnv = {},
  timeout = 120000
}) {
  let lastErr = null
  for (let attempt = 0; attempt < 2; attempt++) {
    await waitForPorpitaBuildReady(porpitaRoot, 45000)
    const deps = loadPorpitaDeps(porpitaRoot)
    const dirs = createIsolatedProfileDirs(tempRoot)
    if (seedCompletedOnboarding) {
      seedPorpitaProfile(dirs.userDataDir, profileOptions)
    }
    const env = scrubElectronEnv({ ...dirs, extraEnv })

    let app = null
    let instance = null
    try {
      app = await deps._electron.launch({
        executablePath: deps.electronExe,
        env,
        cwd: dirs.tempRoot,
        args: [`--force-device-scale-factor=${scaleFactor}`, deps.porpitaRoot],
        timeout: Math.max(timeout, 120000)
      })

      instance = {
        app,
        page: null,
        win: null,
        cdpSessions: [],
        deps,
        ...dirs
      }
      ACTIVE_INSTANCES.add(instance)

      const page = await app.firstWindow({ timeout: Math.max(timeout, 120000) })
      await page.waitForLoadState('domcontentloaded', { timeout: 90000 })
      const win = await withTimeout(app.browserWindow(page), 15000, 'browserWindow')
      instance.page = page
      instance.win = win

      const isolation = await withTimeout(
        app.evaluate(({ app: electronApp, BrowserWindow }) => ({
          home: electronApp.getPath('home'),
          userData: electronApp.getPath('userData'),
          windows: BrowserWindow.getAllWindows().map((w) => ({
            id: w.id,
            visible: w.isVisible(),
            focused: w.isFocused()
          }))
        })),
        15000,
        'verifyElectronIsolation'
      )

      assert.equal(
        normalizeRealPath(isolation.home),
        normalizeRealPath(dirs.homeDir),
        `Electron home path leaked: ${isolation.home} !== ${dirs.homeDir}`
      )
      assert.equal(
        normalizeRealPath(isolation.userData),
        normalizeRealPath(dirs.userDataDir),
        `Electron userData path leaked: ${isolation.userData} !== ${dirs.userDataDir}`
      )
      for (const w of isolation.windows) {
        assert.equal(w.visible, false, `Launched window ${w.id} is visible`)
        assert.equal(w.focused, false, `Launched window ${w.id} is focused`)
      }

      await setViewportSize(app, page, width, height)
      page.setDefaultTimeout(8000)

      // Wait for initial React mount
      await page.locator('body').waitFor({ state: 'attached', timeout: 20000 })
      try {
        await page.waitForFunction(
          () => document.querySelector('#root')?.childElementCount > 0 || document.body.innerText.trim().length > 0,
          null,
          { timeout: 60000 }
        )
      } catch (mountErr) {
        throw new Error(`Renderer root did not mount within 60000ms: ${mountErr?.message || mountErr}`)
      }

      return instance
    } catch (err) {
      lastErr = err
      if (instance) {
        await closeElectronApp(instance, { removeTempDir: !tempRoot }).catch(() => {})
      } else if (!tempRoot) {
        await removeDirWithRetries(dirs.tempRoot).catch(() => {})
      }
      if (attempt === 0 && isTransientLaunchError(err)) {
        await sleep(500)
        continue
      }
      throw err
    }
  }
  throw lastErr
}

function collectPosixDescendants(pid, seen = new Set()) {
  if (seen.has(pid)) return []
  seen.add(pid)
  let children = []
  try {
    const out = execFileSync('pgrep', ['-P', String(pid)], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
      timeout: 3000
    })
    children = out
      .split(/\r?\n/)
      .map((s) => Number.parseInt(s.trim(), 10))
      .filter((n) => Number.isInteger(n) && n > 0)
  } catch {
    children = []
  }
  const all = []
  for (const childPid of children) {
    all.push(...collectPosixDescendants(childPid, seen))
    all.push(childPid)
  }
  return all
}

function killPidTree(pid) {
  if (!pid || !Number.isInteger(pid) || pid <= 0) return
  if (process.platform === 'win32') {
    try {
      execFileSync('taskkill', ['/pid', String(pid), '/T', '/F'], {
        stdio: 'ignore',
        timeout: 5000
      })
      return
    } catch {
      // Fall through to process.kill
    }
    try {
      process.kill(pid, 'SIGKILL')
    } catch {
      // Already exited
    }
    return
  }

  const descendants = collectPosixDescendants(pid)
  try {
    execFileSync('pkill', ['-KILL', '-P', String(pid)], {
      stdio: 'ignore',
      timeout: 3000
    })
  } catch {
    // Ignore when no children or pkill unavailable
  }
  for (const childPid of descendants) {
    try {
      process.kill(childPid, 'SIGKILL')
    } catch {
      // Already exited
    }
  }
  try {
    process.kill(-pid, 'SIGKILL')
  } catch {
    // Ignore if pid is not a process group leader
  }
  try {
    process.kill(pid, 'SIGKILL')
  } catch {
    // Already exited
  }
}

function killDaemonPids(userDataDir) {
  const daemonDir = path.join(userDataDir, 'daemon')
  if (!existsSync(daemonDir)) return false
  let killed = false
  for (const entry of readdirSync(daemonDir)) {
    if (!entry.endsWith('.pid')) continue
    try {
      const raw = readFileSync(path.join(daemonDir, entry), 'utf8').trim()
      const pid = Number.parseInt(raw, 10)
      if (Number.isInteger(pid) && pid > 0) {
        killPidTree(pid)
        killed = true
      }
    } catch {
      // Ignore unreadable pid file
    }
  }
  return killed
}

function killProcessesReferencingDir(targetDir) {
  if (!targetDir) return
  const baseName = path.basename(targetDir)
  if (!baseName || baseName.length < 8) return
  if (process.platform === 'win32') {
    try {
      execFileSync(
        'powershell',
        [
          '-NoProfile',
          '-NonInteractive',
          '-Command',
          `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*${baseName.replace(/'/g, "''")}*' -and $_.Name -ne 'powershell.exe' -and $_.Name -ne 'pwsh.exe' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }`
        ],
        { stdio: 'ignore', timeout: 8000, windowsHide: true }
      )
    } catch {
      // Best-effort process cleanup
    }
    return
  }
  try {
    const out = execFileSync('pgrep', ['-f', baseName], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
      timeout: 5000
    })
    for (const line of out.split(/\r?\n/)) {
      const pid = Number.parseInt(line.trim(), 10)
      if (Number.isInteger(pid) && pid > 0 && pid !== process.pid && pid !== process.ppid) {
        killPidTree(pid)
      }
    }
  } catch {
    // Best-effort process cleanup
  }
}

async function removeDirWithRetries(targetDir, attempts = 16, delayMs = 300) {
  if (!targetDir || !existsSync(targetDir)) {
    PENDING_CLEANUP_DIRS.delete(targetDir)
    return true
  }
  for (let i = 0; i < attempts; i++) {
    try {
      rmSync(targetDir, { recursive: true, force: true })
      if (!existsSync(targetDir)) {
        PENDING_CLEANUP_DIRS.delete(targetDir)
        return true
      }
    } catch {
      if (i === 2 || i === 6) {
        killProcessesReferencingDir(targetDir)
      }
    }
    if (i < attempts - 1) {
      await sleep(delayMs)
    }
  }
  if (existsSync(targetDir)) {
    PENDING_CLEANUP_DIRS.add(targetDir)
    return false
  }
  PENDING_CLEANUP_DIRS.delete(targetDir)
  return true
}

export async function closeElectronApp(instance, { removeTempDir = true } = {}) {
  if (!instance) return
  ACTIVE_INSTANCES.delete(instance)
  const { app, cdpSessions = [], userDataDir, tempRoot } = instance

  for (const cdp of cdpSessions) {
    await withTimeout(cdp.send('Page.stopScreencast').catch(() => {}), 2000, 'stopScreencast').catch(() => {})
    await withTimeout(cdp.detach().catch(() => {}), 2000, 'cdpDetach').catch(() => {})
  }

  let mainPid = null
  let child = null
  try {
    child = app?.process() ?? null
    mainPid = child?.pid ?? null
  } catch {
    mainPid = null
  }

  let metricPids = []
  if (app && child && child.exitCode === null) {
    metricPids = await withTimeout(
      app.evaluate(({ app: electronApp }) => electronApp.getAppMetrics().map((m) => m.pid)),
      2000,
      'getAppMetrics'
    ).catch(() => [])
  }

  let killedAny = false
  if (app) {
    const closed = Promise.race([
      app.close().catch(() => {}),
      sleep(5000).then(() => 'timeout')
    ])
    const res = await closed
    if (res === 'timeout' || (child && child.exitCode === null)) {
      if (mainPid) {
        killPidTree(mainPid)
        killedAny = true
      }
    }
    for (const pid of metricPids) {
      if (Number.isInteger(pid) && pid > 0 && pid !== mainPid) {
        try {
          process.kill(pid, 0)
          killPidTree(pid)
          killedAny = true
        } catch {
          // Already exited
        }
      }
    }
    try {
      child?.stdout?.destroy()
      child?.stderr?.destroy()
      child?.stdin?.destroy()
    } catch {
      // Ignore pipe cleanup errors
    }
  }

  if (userDataDir) {
    if (killDaemonPids(userDataDir)) {
      killedAny = true
    }
  }

  if (killedAny) {
    await sleep(300)
  }

  if (removeTempDir && tempRoot) {
    await removeDirWithRetries(tempRoot, 12, 250)
  }
  for (const staleDir of [...PENDING_CLEANUP_DIRS]) {
    if (staleDir !== tempRoot) {
      await removeDirWithRetries(staleDir, 4, 200)
    }
  }
}

export async function quitElectronGracefully(instance, timeoutMs = 35000) {
  const { app } = instance
  const child = app.process()
  const exitPromise = new Promise((resolve) => {
    if (child.exitCode !== null) resolve(child.exitCode)
    else child.once('exit', (code) => resolve(code))
  })
  await withTimeout(
    app.evaluate(({ app: electronApp }) => setTimeout(() => electronApp.quit(), 40)),
    5000,
    'quitElectronGracefully'
  ).catch(() => {})
  const result = await Promise.race([
    exitPromise,
    sleep(timeoutMs).then(() => 'timeout')
  ])
  if (result === 'timeout') {
    await closeElectronApp(instance, { removeTempDir: false })
    throw new Error('Electron graceful quit timed out')
  }
  ACTIVE_INSTANCES.delete(instance)
  if (instance.userDataDir) killDaemonPids(instance.userDataDir)
  return result
}

export async function cleanupAllElectronApps() {
  for (const inst of [...ACTIVE_INSTANCES]) {
    await closeElectronApp(inst, { removeTempDir: true }).catch(() => {})
  }
  for (const staleDir of [...PENDING_CLEANUP_DIRS]) {
    await removeDirWithRetries(staleDir, 45, 500).catch(() => {})
  }
}

// Opaque-box UI interaction helpers (NO window.__store usage)
export async function dismissStartupDialogs(page) {
  const dialogDismissPattern =
    /^(Got it|知道了|Close|关闭|Dismiss setup scripts|关闭安装脚本|Not now|稍后|Skip tour|Close tour|跳过导览|关闭导览|Dismiss|忽略|Maybe later|以后再说)$/i
  // NEVER include generic "Close"/"关闭" on page-level lookup (matches window titlebar close button!)
  const pageTipPattern =
    /^(Got it|知道了|Dismiss setup scripts|关闭安装脚本|Not now|稍后|Skip tour|Close tour|跳过导览|关闭导览|Maybe later|以后再说)$/i
  for (let i = 0; i < 6; i++) {
    const blockingDialog = page
      .locator('[role="dialog"]:not([data-onboarding-modal]):visible, [role="alertdialog"]:visible')
      .last()
    if (await blockingDialog.isVisible().catch(() => false)) {
      const dialogCloseBtn = blockingDialog
        .getByRole('button', { name: dialogDismissPattern })
        .last()
      if (await dialogCloseBtn.isVisible().catch(() => false)) {
        await dialogCloseBtn.click().catch(() => {})
        await sleep(200)
        continue
      }
      await page.keyboard.press('Escape').catch(() => {})
      await sleep(200)
      continue
    }
    const pageTipBtn = page.getByRole('button', { name: pageTipPattern }).first()
    if (await pageTipBtn.isVisible().catch(() => false)) {
      await pageTipBtn.click().catch(() => {})
      await sleep(200)
      continue
    }
    break
  }
}

export async function addLocalFolderProject(app, page, folderPath) {
  await stubOpenDialog(app, folderPath)
  await dismissStartupDialogs(page)
  const skipSetupBtn = page.getByRole('button', { name: /^(Skip setup|跳过设置)$/i }).first()
  const addBtns = page.getByRole('button', { name: /^(Add project|添加项目)$/i })
  const deadline = Date.now() + 30000
  while (Date.now() < deadline) {
    if (await skipSetupBtn.isVisible().catch(() => false)) {
      await skipSetupBtn.click().catch(() => {})
      await sleep(300)
      continue
    }
    if (await addBtns.first().isVisible().catch(() => false)) {
      break
    }
    await dismissStartupDialogs(page)
    await sleep(250)
  }

  const browseBtn = page.getByRole('button', { name: /Browse folder|浏览文件夹/i }).first()
  let browseVisible = false
  for (let attempt = 0; attempt < 3; attempt++) {
    await dismissStartupDialogs(page)
    await addBtns.first().waitFor({ state: 'visible', timeout: 15000 })
    const count = await addBtns.count()
    // Prefer Landing button (.last()) if multiple are present, falling back to sidebar button (.first())
    try {
      await addBtns.nth(count > 1 ? count - 1 : 0).click({ timeout: 4000 })
    } catch {
      await dismissStartupDialogs(page)
      await addBtns.first().click({ timeout: 4000 }).catch(() => {})
    }
    if (await waitForVisible(browseBtn, 2500)) {
      browseVisible = true
      break
    }
    await sleep(250)
  }
  if (!browseVisible) {
    await browseBtn.waitFor({ state: 'visible', timeout: 6000 })
  }
  await browseBtn.click()
  await sleep(600)
  // Handle Trust dialog or Non-Git "Open as Folder" confirmation dialog
  for (let i = 0; i < 3; i++) {
    const confirmBtn = page
      .getByRole('button', {
        name: /^(Open as Folder|作为文件夹打开|Trust repository|信任仓库|Trust folder|信任文件夹|Allow|允许)$/i
      })
      .first()
    if (await waitForVisible(confirmBtn, 2000)) {
      await confirmBtn.click()
      await sleep(400)
      continue
    }
    break
  }
  await dismissStartupDialogs(page)
  const folderName = path.basename(folderPath)
  await page.getByText(folderName, { exact: false }).first().waitFor({ state: 'visible', timeout: 12000 })
  // Activate the newest worktree row if no active worktree is selected yet so Explorer/SourceControl/Tabs populate
  const worktrees = page.locator('[data-worktree-id]')
  const wtCount = await worktrees.count()
  if (wtCount > 0) {
    const activeCount = await page.locator('[data-worktree-card-active="true"]').count()
    if (activeCount === 0 || wtCount > 1) {
      await worktrees.last().click().catch(() => {})
      await sleep(300)
      await dismissStartupDialogs(page)
    }
  }
}

export async function waitForVisible(locator, timeoutMs = 3000) {
  return await locator.waitFor({ state: 'visible', timeout: timeoutMs }).then(
    () => true,
    () => false
  )
}

/**
 * Selector contract expected once M3 Workspace shell integrates WorkspacePreview + SidebarSessionIndex.
 */
export const M3_SELECTOR_CONTRACT = {
  workspaceShell:
    '[data-workspace-preview], [data-workspace-tab-strip], [data-workspace-group-selector], [data-session-index]',
  tabStrip: '[data-workspace-tab-strip], .terminal-tab-strip',
  workspaceTab: 'button[data-workspace-preview-tab], button[data-workspace-tab]',
  groupSelector: '[data-workspace-preview-group], [data-workspace-group-selector]',
  sessionIndex: '[data-session-index]',
  sessionIndexRow: '[data-session-index-row]',
  sessionIndexHistory: '[data-session-index-history]',
  splitLayout: '[data-workspace-preview-chat-layout], [data-workspace-split-layout]',
  explorer: '[data-workspace-preview-explorer], [data-workspace-explorer]',
  explorerScope: '[data-workspace-preview-scope], [data-workspace-explorer-scope]'
}

export async function detectWorkspaceShell(page) {
  return await page.evaluate(() => {
    const previewToggle = [...document.querySelectorAll('button')].some((b) =>
      /Workspaces \(preview\)|工作空间（预览）/i.test(b.textContent || '')
    )
    const hasWorkspaceTabs =
      Boolean(document.querySelector('[data-workspace-preview]')) ||
      Boolean(document.querySelector('[data-workspace-tab-strip]')) ||
      Boolean(document.querySelector('[data-workspace-group-selector]')) ||
      Boolean(document.querySelector('[data-session-index]')) ||
      [...document.querySelectorAll('button')].some((b) =>
        /New workspace|新建工作空间|New work object|新建工作对象/i.test(b.textContent || '')
      )
    return {
      previewToggle,
      hasWorkspaceTabs,
      integrated: !previewToggle && hasWorkspaceTabs
    }
  })
}

export async function hasIntegratedWorkspaceShell(page) {
  const ws = await detectWorkspaceShell(page)
  return ws.integrated
}

export async function openSettingsPage(page) {
  const section = page.locator('section[data-settings-section]').first()
  if (await waitForVisible(section, 250)) {
    return
  }
  const settingsBtn = page.getByRole('button', { name: /^(Settings|设置)$/i }).first()
  await settingsBtn.waitFor({ state: 'visible', timeout: 10000 })
  await settingsBtn.click()
  if (!(await waitForVisible(section, 3000))) {
    if (await settingsBtn.isVisible().catch(() => false)) {
      await settingsBtn.click({ timeout: 2000 }).catch(() => {})
    }
  }
  await section.waitFor({ state: 'visible', timeout: 15000 })
}

export async function returnFromSettings(page) {
  const backBtn = page.getByRole('button', { name: /^(Back to app|返回应用)$/i }).first()
  if (await backBtn.isVisible().catch(() => false)) {
    const settingsSection = page.locator('section[data-settings-section]').first()
    await backBtn.click()
    const hid = await settingsSection.waitFor({ state: 'hidden', timeout: 1500 }).then(
      () => true,
      () => false
    )
    if (!hid && (await backBtn.isVisible().catch(() => false))) {
      await backBtn.click({ timeout: 2000 }).catch(() => {})
      await settingsSection.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {})
    }
  }
}

/**
 * Returns true strictly for a connected Collaboration status label (never false-matching "Not connected").
 */
export function isCollaborationConnectedText(text) {
  const trimmed = (text || '').trim()
  return (
    /^(Connected|已连接)$/i.test(trimmed) ||
    (/^(Connected|已连接)\b/i.test(trimmed) && !/Not connected|未连接|Attention|需要|Checking|正在检查/i.test(trimmed))
  )
}

/**
 * Returns the Titlebar Collaboration trigger button locator.
 */
export function getCollaborationTrigger(page) {
  return page.getByRole('button', { name: /^(Collaboration|协作消息|协作|Collaboration messages)$/i }).first()
}

export async function openCollaborationDialog(page) {
  const collabBtn = getCollaborationTrigger(page)
  await collabBtn.waitFor({ state: 'visible', timeout: 10000 })
  await collabBtn.click()
  const dialog = page.getByRole('dialog').filter({ hasText: /^(Collaboration|协作消息|协作)/i }).first()
  await dialog.waitFor({ state: 'visible', timeout: 10000 })
  return dialog
}

/**
 * Closes an open Collaboration dialog with Escape and asserts focus returns to a connected element.
 */
export async function closeCollaborationDialogWithFocusCheck(page, dialog) {
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'hidden', timeout: 5000 })
  const focus = await page.evaluate(() => ({
    tag: document.activeElement?.tagName ?? null,
    ariaLabel: document.activeElement?.getAttribute?.('aria-label') ?? null,
    connected: Boolean(document.activeElement?.isConnected)
  }))
  assert.equal(focus.connected, true, `Collaboration dialog Escape left focus disconnected: ${JSON.stringify(focus)}`)
  return focus
}

/**
 * Connects Porpita Settings -> General -> Collaboration to an existing loopback ACS Core service.
 */
export async function connectCollaborationViaSettings(page, core) {
  await openSettingsPage(page)
  const generalNav = page.locator('aside button').filter({ hasText: /^(General|常规|通用)$/i }).first()
  await generalNav.click()
  const generalSec = page.locator('section[data-settings-section="general"]').first()
  await generalSec.waitFor({ state: 'visible', timeout: 8000 })

  const existingRadio = generalSec
    .getByRole('radio', { name: /Connect an existing service|连接已有服务/i })
    .first()
  const existingBtn = generalSec
    .getByRole('button', { name: /Connect an existing service|连接已有服务/i })
    .first()
  if (await waitForVisible(existingRadio, 600)) {
    await existingRadio.click()
  } else {
    await existingBtn.click()
  }

  await generalSec.getByLabel(/Service address|服务地址/i).fill(core.baseUrl)
  await generalSec.getByLabel(/Connection key|连接密钥/i).fill(core.tokens.client)
  await generalSec.getByRole('button', { name: /^(Connect|连接)$/i }).first().click()
  await generalSec.getByText(/^(Connected|已连接)$/i).first().waitFor({ state: 'visible', timeout: 10000 })
  return generalSec
}

/**
 * Disconnects the active Collaboration service from Settings -> General and verifies Reconnect control appears.
 */
export async function disconnectCollaborationViaSettings(page) {
  await openSettingsPage(page)
  const generalNav = page.locator('aside button').filter({ hasText: /^(General|常规|通用)$/i }).first()
  await generalNav.click()
  const generalSec = page.locator('section[data-settings-section="general"]').first()
  await generalSec.waitFor({ state: 'visible', timeout: 8000 })
  const disconnectBtn = generalSec.getByRole('button', { name: /^(Disconnect|断开连接|断开)$/i }).first()
  await disconnectBtn.waitFor({ state: 'visible', timeout: 8000 })
  await disconnectBtn.click()
  await generalSec.getByText(/^(Not connected|未连接)$/i).first().waitFor({ state: 'visible', timeout: 10000 })
  const reconnectBtn = generalSec.getByRole('button', { name: /^(Reconnect|重新连接|重连)$/i }).first()
  await reconnectBtn.waitFor({ state: 'visible', timeout: 8000 })
  return generalSec
}

/**
 * Reconnects the previously configured Collaboration service via secondary Reconnect button in Settings -> General.
 */
export async function reconnectCollaborationViaSettings(page) {
  await openSettingsPage(page)
  const generalNav = page.locator('aside button').filter({ hasText: /^(General|常规|通用)$/i }).first()
  await generalNav.click()
  const generalSec = page.locator('section[data-settings-section="general"]').first()
  await generalSec.waitFor({ state: 'visible', timeout: 8000 })
  const reconnectBtn = generalSec.getByRole('button', { name: /^(Reconnect|重新连接|重连)$/i }).first()
  await reconnectBtn.waitFor({ state: 'visible', timeout: 8000 })
  await reconnectBtn.click()
  await generalSec.getByText(/^(Connected|已连接)$/i).first().waitFor({ state: 'visible', timeout: 10000 })
  await generalSec.getByRole('button', { name: /^(Disconnect|断开连接|断开)$/i }).first().waitFor({ state: 'visible', timeout: 8000 })
  return generalSec
}

/**
 * Selects a collaborator in the Collaboration dialog aside and waits for the composer textarea.
 */
export async function selectCollaborationContact(dialog, contactName = 'slot-b') {
  await dialog
    .evaluate((el) => Promise.all(el.getAnimations().map((anim) => anim.finished.catch(() => {}))))
    .catch(() => {})
  const contactBtn = dialog
    .locator('aside')
    .getByRole('button', { name: new RegExp(`^${contactName}$`, 'i') })
    .first()
  await contactBtn.waitFor({ state: 'visible', timeout: 10000 })
  await contactBtn.click()
  const composer = dialog.locator('textarea').first()
  try {
    await composer.waitFor({ state: 'visible', timeout: 10000 })
  } catch (err) {
    const diag = await dialog
      .evaluate((el) => ({
        mainText: el.querySelector('main')?.innerText ?? null,
        statuses: [...el.querySelectorAll('[role="status"]')].map((s) => s.textContent),
        alerts: [...el.querySelectorAll('[role="alert"]')].map((a) => a.textContent),
        aside: [...el.querySelectorAll('aside button')].map((b) => b.getAttribute('aria-label') || b.textContent)
      }))
      .catch(() => null)
    throw new Error(`${err.message}\n[selectCollaborationContact(${contactName}) diag] ${JSON.stringify(diag)}`)
  }
  return composer
}

/**
 * Returns the platform primary shortcut modifier for Playwright key chords.
 */
export function primaryModifierKey() {
  return process.platform === 'darwin' ? 'Meta' : 'Control'
}

/**
 * Verifies a toolbar/surface has no horizontal overflow, clipped controls, or sibling button overlaps.
 */
export async function assertHorizontalToolbarLayout(
  page,
  containerSelector = 'main',
  contextLabel = 'layout'
) {
  const geo = await page.evaluate((sel) => {
    const vw = window.innerWidth
    const vh = window.innerHeight
    const root = document.querySelector(sel) || document.querySelector('main')
    if (!root) {
      return { found: false, docOverflowX: document.documentElement.scrollWidth > vw + 2 }
    }
    const rr = root.getBoundingClientRect()
    const rawItems = [...root.querySelectorAll('button, input, [role="combobox"], a, [data-slot="button"]')]
      .map((el) => {
        const r = el.getBoundingClientRect()
        return {
          el,
          label:
            el.getAttribute('aria-label') ||
            el.getAttribute('placeholder') ||
            el.textContent?.trim().slice(0, 50) ||
            el.tagName,
          left: r.left,
          top: r.top,
          right: r.right,
          bottom: r.bottom,
          width: r.width,
          height: r.height
        }
      })
      .filter((r) => r.width > 0 && r.height > 0 && r.top < vh && r.bottom > 0)

    const clipped = rawItems
      .filter((r) => r.right > vw + 1 || r.right > rr.right + 2 || r.left < -1)
      .map((r) => ({
        label: r.label,
        left: Math.round(r.left),
        right: Math.round(r.right),
        containerRight: Math.round(rr.right),
        vw
      }))

    const overlaps = []
    for (let i = 0; i < rawItems.length; i++) {
      for (let j = i + 1; j < rawItems.length; j++) {
        const a = rawItems[i]
        const b = rawItems[j]
        if (a.el.contains(b.el) || b.el.contains(a.el)) continue
        const ix = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left))
        const iy = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top))
        if (ix > 2 && iy > 2) {
          overlaps.push({ a: a.label, b: b.label, ix: Math.round(ix), iy: Math.round(iy) })
        }
      }
    }

    return {
      found: true,
      itemCount: rawItems.length,
      scrollWidth: Math.round(root.scrollWidth),
      clientWidth: Math.round(root.clientWidth),
      rootOverflowX: root.scrollWidth > root.clientWidth + 2,
      docOverflowX: document.documentElement.scrollWidth > vw + 2,
      clipped,
      overlaps
    }
  }, containerSelector)

  assert.equal(geo.found, true, `${contextLabel}: container ${containerSelector} not found`)
  assert.ok(geo.itemCount >= 1, `${contextLabel}: expected >=1 visible interactive control`)
  assert.equal(
    geo.docOverflowX,
    false,
    `${contextLabel}: document horizontal overflow detected (${JSON.stringify(geo)})`
  )
  assert.equal(
    geo.rootOverflowX,
    false,
    `${contextLabel}: container overflowX (${geo.scrollWidth} > ${geo.clientWidth})`
  )
  assert.deepEqual(geo.clipped, [], `${contextLabel}: clipped controls: ${JSON.stringify(geo.clipped)}`)
  assert.deepEqual(geo.overlaps, [], `${contextLabel}: overlapping controls: ${JSON.stringify(geo.overlaps)}`)
  return geo
}

/**
 * Verifies [data-notification-card-stack] cards stay inside the viewport and do not block primary controls.
 */
export async function assertNotificationStackNonBlocking(
  page,
  { requireActiveCard = false, contextLabel = 'notification-stack' } = {}
) {
  const probe = await page.evaluate(() => {
    const vw = window.innerWidth
    const vh = window.innerHeight
    const stack = document.querySelector('[data-notification-card-stack]')
    const setupLayer = document.querySelector('[data-setup-script-prompt-layer]')
    const cards = [...document.querySelectorAll('[data-notification-card-stack] > *')]
      .map((el) => {
        const r = el.getBoundingClientRect()
        return {
          text: (el.textContent || '').trim().slice(0, 80),
          left: Math.round(r.left),
          top: Math.round(r.top),
          right: Math.round(r.right),
          bottom: Math.round(r.bottom),
          width: Math.round(r.width),
          height: Math.round(r.height)
        }
      })
      .filter((r) => r.width > 0 && r.height > 0)

    const clippedCards = cards.filter(
      (c) => c.top < -1 || c.bottom > vh + 1 || c.left < -1 || c.right > vw + 1
    )

    const primaryTargets = [
      ...document.querySelectorAll('main button, aside button, [data-worktree-card-surface="true"]')
    ].filter((el) => {
      if (setupLayer && setupLayer.contains(el)) return false
      if (stack && stack.contains(el)) return false
      const r = el.getBoundingClientRect()
      return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < vh
    })

    const blockedControls = []
    for (const target of primaryTargets) {
      const tr = target.getBoundingClientRect()
      const cx = Math.round((tr.left + tr.right) / 2)
      const cy = Math.round((tr.top + tr.bottom) / 2)
      const topEl = document.elementFromPoint(cx, cy)
      const occludedByStack = Boolean(stack && topEl && stack.contains(topEl))
      const occludedBySetup = Boolean(setupLayer && topEl && setupLayer.contains(topEl))
      if (occludedByStack || occludedBySetup) {
        blockedControls.push({
          label:
            target.getAttribute('aria-label') ||
            target.textContent?.trim().slice(0, 50) ||
            target.tagName,
          blocker: occludedByStack ? 'notification-card-stack' : 'setup-script-prompt',
          rect: { left: Math.round(tr.left), top: Math.round(tr.top), right: Math.round(tr.right), bottom: Math.round(tr.bottom) }
        })
      }
    }

    return {
      vw,
      vh,
      stackPresent: Boolean(stack),
      activeCardsCount: cards.length,
      cards,
      clippedCards,
      blockedControls
    }
  })

  if (requireActiveCard) {
    assert.ok(
      probe.activeCardsCount >= 1,
      `${contextLabel}: expected at least 1 active card in [data-notification-card-stack]`
    )
  }
  assert.deepEqual(
    probe.clippedCards,
    [],
    `${contextLabel}: notification card clipped outside viewport: ${JSON.stringify(probe)}`
  )
  assert.deepEqual(
    probe.blockedControls,
    [],
    `${contextLabel}: notification card stack overlapped/blocked controls: ${JSON.stringify(probe)}`
  )
  return probe
}

/**
 * Installs, trusts, and approves a local folder plugin through Settings -> Plugins without silent skips.
 */
export async function installAndEnableFolderPlugin(app, page, pluginFix) {
  const sec = page.locator('section[data-settings-section="plugins"]').first()
  await sec.waitFor({ state: 'visible', timeout: 10000 })

  const turnOnBtn = page.getByRole('button', { name: /Turn on plugins|开启插件/i }).first()
  if (await waitForVisible(turnOnBtn, 1200)) {
    await turnOnBtn.click()
  }

  const addMenuBtn = page.getByRole('button', { name: /^(Add plugin|添加插件)/i }).first()
  await addMenuBtn.waitFor({ state: 'visible', timeout: 8000 })
  await stubOpenDialog(app, [pluginFix.pluginDir])
  await addMenuBtn.click()

  const fromFolderItem = page.getByRole('menuitem', { name: /From a folder|从文件夹/i }).first()
  await fromFolderItem.waitFor({ state: 'visible', timeout: 5000 })
  await fromFolderItem.click()

  const installDialog = page.locator('[role="dialog"]:visible').last()
  await installDialog.waitFor({ state: 'visible', timeout: 5000 })
  const folderInput = installDialog.locator('input#plugin-local-path, input').first()
  await folderInput.waitFor({ state: 'visible', timeout: 5000 })
  await folderInput.fill(pluginFix.pluginDir)

  const modalInstallBtn = installDialog.getByRole('button', { name: /^(Install|安装|Add|添加)$/i }).first()
  await modalInstallBtn.waitFor({ state: 'visible', timeout: 5000 })
  await modalInstallBtn.click()

  const trustConfirmBtn = page
    .locator('[role="dialog"]:visible, [role="alertdialog"]:visible')
    .last()
    .getByRole('button', { name: /^(Add folder|添加文件夹|Install|安装|Approve|Allow|Trust|允许|确认)$/i })
    .first()
  if (await waitForVisible(trustConfirmBtn, 5000)) {
    await trustConfirmBtn.click()
  }

  // After install, PluginsSettingsSection opens review/detail OR lists the plugin awaiting review.
  const reviewBtn = sec.getByRole('button', { name: /^(Review|审核|查看)$/i }).first()
  const enableBtn = sec.getByRole('button', { name: /Enable plugin|启用插件/i }).first()
  const pluginEntry = page.getByText(pluginFix.title, { exact: false }).first()
  await pluginEntry.waitFor({ state: 'visible', timeout: 12000 })

  if (await waitForVisible(reviewBtn, 1500)) {
    await reviewBtn.click()
  }
  if (await waitForVisible(enableBtn, 2500)) {
    await enableBtn.click()
  }

  const openPanelBtn = sec.getByRole('button', { name: /Open panel|打开面板/i }).first()
  const enabledSwitch = sec
    .locator('[role="switch"][aria-checked="true"]')
    .first()
  const becameReady =
    (await waitForVisible(openPanelBtn, 6000)) || (await waitForVisible(enabledSwitch, 2000))
  assert.equal(
    becameReady,
    true,
    `Plugin ${pluginFix.title} did not reach enabled state after folder install & review`
  )
  return { installed: true, enabled: true }
}

/**
 * Opens the installed plugin panel in RightSidebar and asserts healthy rendering without load failure.
 */
export async function openAndVerifyPluginPanel(page, pluginTitle) {
  const sec = page.locator('section[data-settings-section="plugins"]').first()
  let openPanelBtn = sec.getByRole('button', { name: /Open panel|打开面板/i }).first()
  if (!(await waitForVisible(openPanelBtn, 1500))) {
    const pluginRow = sec.getByText(pluginTitle, { exact: false }).first()
    await pluginRow.waitFor({ state: 'visible', timeout: 8000 })
    await pluginRow.click()
    openPanelBtn = sec.getByRole('button', { name: /Open panel|打开面板/i }).first()
  }
  await openPanelBtn.waitFor({ state: 'visible', timeout: 8000 })
  await openPanelBtn.click()

  const panelSurface = page.locator('[data-plugin-panel-surface]').first()
  await panelSurface.waitFor({ state: 'visible', timeout: 12000 })

  // Wait briefly for declarative/frame panel hydration to settle before inspecting errors/content.
  await page
    .waitForFunction(() => {
      const el = document.querySelector('[data-plugin-panel-surface]')
      if (!el) return false
      const text = (el.innerText || '').trim()
      return text.length > 0 && !/^(Loading|加载中)/i.test(text)
    }, undefined, { timeout: 10000 })
    .catch(() => {})

  const panelState = await page.evaluate(() => {
    const surface = document.querySelector('[data-plugin-panel-surface]')
    if (!surface) return { present: false }
    const rect = surface.getBoundingClientRect()
    const text = (surface.innerText || '').trim()
    const alerts = [...surface.querySelectorAll('[role="alert"]')].map((a) => (a.innerText || '').trim())
    const hasInteractive =
      surface.querySelectorAll('button, input, [role="switch"], webview, iframe').length > 0
    return {
      present: true,
      tabKey: surface.getAttribute('data-plugin-panel-surface'),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
      text: text.slice(0, 500),
      alerts,
      hasInteractive
    }
  })

  assert.equal(panelState.present, true, 'RightSidebar plugin panel surface did not mount')
  assert.ok(
    panelState.width > 80 && panelState.height > 80,
    `Plugin panel rendered empty/collapsed: ${JSON.stringify(panelState)}`
  )
  assert.equal(
    /failed to load|加载失败/i.test(panelState.text),
    false,
    `Plugin panel showed runtime load error: ${panelState.text}`
  )
  assert.equal(
    panelState.alerts.some((msg) => /failed to load|加载失败/i.test(msg)),
    false,
    `Plugin panel emitted alert error: ${JSON.stringify(panelState.alerts)}`
  )
  assert.ok(
    panelState.hasInteractive || panelState.text.length > 0,
    `Plugin panel rendered no visible content or controls: ${JSON.stringify(panelState)}`
  )
  return panelState
}

/**
 * Disables an active plugin via its Settings switch and verifies cleanup and connected focus.
 */
export async function disablePluginAndVerify(page, pluginTitle) {
  await openSettingsPage(page)
  const pluginsNav = page.locator('aside button').filter({ hasText: /^(Plugins|插件)/i }).first()
  await pluginsNav.waitFor({ state: 'visible', timeout: 8000 })
  await pluginsNav.click()
  const sec = page.locator('section[data-settings-section="plugins"]').first()
  await sec.waitFor({ state: 'visible', timeout: 8000 })

  let disableSwitch = sec
    .getByRole('switch', { name: new RegExp(`Disable.*${pluginTitle}|停用|禁用`, 'i') })
    .first()
  if (!(await waitForVisible(disableSwitch, 1500))) {
    // PluginManager suppresses uncataloged local plugins on "All" while catalog.loading awaits online seed;
    // switching to "Installed" renders visibleInstalled immediately offline.
    const installedTab = sec.locator('button, [role="tab"]').filter({ hasText: /^(Installed|已安装)/i }).first()
    if (await waitForVisible(installedTab, 1500)) {
      await installedTab.click()
    }
  }
  if (!(await waitForVisible(disableSwitch, 2000))) {
    disableSwitch = sec.locator('[role="switch"][aria-checked="true"]').first()
  }
  await disableSwitch.waitFor({ state: 'visible', timeout: 8000 })
  assert.equal(
    await disableSwitch.getAttribute('aria-checked'),
    'true',
    `Expected enabled switch aria-checked="true" for ${pluginTitle}`
  )
  await disableSwitch.click()
  await page.waitForFunction(
    (namePattern) => {
      const secEl = document.querySelector('section[data-settings-section="plugins"]')
      if (!secEl) return false
      const sw = [...secEl.querySelectorAll('[role="switch"]')].find((el) =>
        new RegExp(namePattern, 'i').test(el.getAttribute('aria-label') || '')
      ) || secEl.querySelector('[role="switch"]')
      return Boolean(sw && sw.getAttribute('aria-checked') === 'false')
    },
    pluginTitle,
    { timeout: 8000 }
  )

  const focusConnected = await page.evaluate(() => Boolean(document.activeElement?.isConnected))
  assert.equal(focusConnected, true, 'Document activeElement became disconnected after disabling plugin')

  await returnFromSettings(page)
  assert.equal(
    await page.locator('[data-plugin-panel-surface]:visible').count(),
    0,
    'Disabled plugin panel remained visible after turning off plugin'
  )
  return { disabledCleanly: true, focusConnected }
}

/**
 * Dispatches IME composition events with Enter inside a CommandDialog and verifies it does not close.
 */
export async function assertImeCompositionKeepsDialogOpen(page, dialogLocator, typedText = 'ma') {
  await dialogLocator.waitFor({ state: 'visible', timeout: 8000 })
  const input = dialogLocator.locator('input').first()
  await input.waitFor({ state: 'visible', timeout: 5000 })
  await input.click()
  await input.fill(typedText)

  const stateAfterEnter = await page.evaluate(() => {
    const el = document.activeElement
    if (!el || el.tagName !== 'INPUT') {
      return { activeTag: el?.tagName ?? null, value: null }
    }
    el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true, data: '测' }))
    el.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Enter', keyCode: 229, isComposing: true, bubbles: true })
    )
    el.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '测试' }))
    return { activeTag: el.tagName, value: el.value }
  })

  assert.equal(
    stateAfterEnter.activeTag,
    'INPUT',
    `Expected focused dialog INPUT during IME Enter, got ${stateAfterEnter.activeTag}`
  )
  assert.equal(
    await dialogLocator.isVisible(),
    true,
    'IME Enter (isComposing=true) must NOT prematurely close/submit CommandDialog'
  )
  await page.keyboard.press('Escape')
  await dialogLocator.waitFor({ state: 'hidden', timeout: 5000 })
  return stateAfterEnter
}

/**
 * Opens Markdown Preview from the active editor header path context menu and verifies rendered heading + XSS safety.
 */
export async function openMarkdownPreviewAndVerify(page, headingText = 'Release Notes') {
  const headerRow = page.locator('.editor-header-path-row').first()
  await headerRow.waitFor({ state: 'visible', timeout: 8000 })
  await headerRow.click({ button: 'right' })
  const previewItem = page
    .getByRole('menuitem', { name: /Open Markdown Preview|打开 Markdown 预览/i })
    .first()
  await previewItem.waitFor({ state: 'visible', timeout: 5000 })
  await previewItem.click()
  await page
    .locator('h1')
    .filter({ hasText: new RegExp(`^${headingText}$`, 'i') })
    .first()
    .waitFor({ state: 'visible', timeout: 10000 })
  const xssTriggered = await page.evaluate(() => Boolean(window.__xss))
  assert.equal(xssTriggered, false, 'Markdown <script> tag must NEVER execute in Preview')
  return { previewRendered: true, xssTriggered }
}
