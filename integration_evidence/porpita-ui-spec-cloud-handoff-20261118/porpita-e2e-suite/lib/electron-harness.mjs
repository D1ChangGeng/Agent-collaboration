import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync
} from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { loadPorpitaDeps, waitForPorpitaBuildReady } from './porpita-deps.mjs'

const ACTIVE_INSTANCES = new Set()
const PENDING_CLEANUP_DIRS = new Set()

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
  mkdirSync(appDataRoaming, { recursive: true })
  mkdirSync(appDataLocal, { recursive: true })
  const gitConfigGlobal = path.join(homeDir, 'gitconfig')
  if (!existsSync(gitConfigGlobal)) {
    writeFileSync(
      gitConfigGlobal,
      '[user]\n\tname = Porpita E2E\n\temail = e2e@porpita.invalid\n[init]\n\tdefaultBranch = main\n',
      'utf8'
    )
  }
  return { tempRoot, userDataDir, homeDir, appDataRoaming, appDataLocal, gitConfigGlobal }
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
  for (let attempt = 0; attempt < 3; attempt++) {
    await withTimeout(
      win.evaluate((w, [cw, ch]) => w.setContentSize(cw, ch), [width, height]),
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
        path.resolve(isolation.home).toLowerCase(),
        path.resolve(dirs.homeDir).toLowerCase(),
        `Electron home path leaked: ${isolation.home} !== ${dirs.homeDir}`
      )
      assert.equal(
        path.resolve(isolation.userData).toLowerCase(),
        path.resolve(dirs.userDataDir).toLowerCase(),
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
  if (process.platform !== 'win32' || !targetDir) return
  const baseName = path.basename(targetDir)
  if (!baseName || baseName.length < 8) return
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
    if (await browseBtn.isVisible({ timeout: 2500 }).catch(() => false)) {
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
    if (await confirmBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
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

export async function openSettingsPage(page) {
  const settingsBtn = page.getByRole('button', { name: /^(Settings|设置)$/i }).first()
  await settingsBtn.waitFor({ state: 'visible', timeout: 10000 })
  await settingsBtn.click()
  const section = page.locator('section[data-settings-section]').first()
  if (!(await section.isVisible({ timeout: 3000 }).catch(() => false))) {
    if (await settingsBtn.isVisible().catch(() => false)) {
      await settingsBtn.click().catch(() => {})
    }
  }
  await section.waitFor({ state: 'visible', timeout: 15000 })
}

export async function returnFromSettings(page) {
  const backBtn = page.getByRole('button', { name: /^(Back to app|返回应用)$/i }).first()
  if (await backBtn.isVisible().catch(() => false)) {
    await backBtn.click()
    await sleep(200)
  }
}

export async function openCollaborationDialog(page) {
  const collabBtn = page.getByRole('button', { name: /^(Collaboration|协作消息|Collaboration messages)$/i }).first()
  await collabBtn.waitFor({ state: 'visible', timeout: 10000 })
  await collabBtn.click()
  const dialog = page.getByRole('dialog').filter({ hasText: /^(Collaboration|协作消息)/i }).first()
  await dialog.waitFor({ state: 'visible', timeout: 10000 })
  return dialog
}
