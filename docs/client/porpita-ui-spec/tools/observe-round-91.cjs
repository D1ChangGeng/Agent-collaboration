const { createRequire } = require('node:module')
const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')

function isPorpitaCheckout(dir) {
  if (!dir) return false
  const resolved = path.resolve(dir)
  return (
    fs.existsSync(path.join(resolved, 'package.json')) &&
    fs.existsSync(path.join(resolved, 'src/renderer/src/App.tsx'))
  )
}

function getDefaultOutputDir() {
  const osTag =
    process.platform === 'win32'
      ? 'windows'
      : process.platform === 'darwin'
        ? 'macos'
        : process.platform
  return path.resolve(__dirname, `../evidence/iteration-91-${osTag}`)
}

function resolveCliOptions(argv) {
  let sourceFlag = null
  let outputFlag = null
  const positional = []

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]
    if (arg === '--source' && argv[i + 1]) {
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
  const outputDir = path.resolve(outputFlag || remainingPositional[0] || getDefaultOutputDir())
  return { source: resolvedSource, outputDir }
}

const { source, outputDir } = resolveCliOptions(process.argv.slice(2))
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

async function launchIsolated(seedData, extraArgs = []) {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'porpita-r91-'))
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
    args: ['--force-device-scale-factor=1', ...extraArgs, entry],
    timeout: 30000
  })
  const page = await app.firstWindow({ timeout: 30000 })
  page.setDefaultTimeout(5000)
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
  return { app, page, win, tempRoot, userData, isolation }
}

async function capture(page, id, extra = {}) {
  await page.evaluate(async () => {
    await document.fonts.ready
  })
  await delay(350)
  const facts = await page.evaluate(() => {
    const active = document.activeElement
    const settingsShell = document.querySelector('.settings-view-shell')
    const mainEls = [...document.querySelectorAll('main')]
    const navEls = [...document.querySelectorAll('nav')]
    const dialogEl = document.querySelector("[data-slot='dialog-content']")
    return {
      size: [window.innerWidth, window.innerHeight],
      dpr: window.devicePixelRatio,
      lang: document.documentElement.lang,
      theme: document.documentElement.classList.contains('dark') ? 'dark' : 'light',
      reducedMotion: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
      forcedColors: window.matchMedia('(forced-colors: active)').matches,
      prefersContrastMore: window.matchMedia('(prefers-contrast: more)').matches,
      zoomFactor: getComputedStyle(document.documentElement).getPropertyValue('--ui-zoom-factor').trim(),
      fontFamily: getComputedStyle(document.body).fontFamily,
      overflowX: document.documentElement.scrollWidth > window.innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
      mainCount: mainEls.length,
      nestedMainCount: document.querySelectorAll('main main').length,
      navCount: navEls.length,
      settingsShellAnimation: settingsShell ? getComputedStyle(settingsShell).animationName : null,
      dialogAnimation: dialogEl ? getComputedStyle(dialogEl).animationName : null,
      focusTag: active?.tagName ?? null,
      focusLabel:
        active?.getAttribute('aria-label') || active?.textContent?.trim().slice(0, 100) || null,
      focusOutline: active ? getComputedStyle(active).outlineStyle : null,
      focusOutlineColor: active ? getComputedStyle(active).outlineColor : null,
      focusBoxShadow: active ? getComputedStyle(active).boxShadow : null,
      text: document.body.innerText.slice(0, 8000)
    }
  })

  const imageFile = `${id}.png`
  const imagePath = path.join(outputDir, imageFile)
  if (facts.dpr !== 1) {
    // Playwright's page.screenshot crops to CSS layout dimensions when webFrame zoom changes dpr;
    // unclipped CDP Page.captureScreenshot captures the full BrowserWindow surface (e.g. 1280x800).
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
  console.log(
    `Captured ${id}: ${facts.size.join('x')} lang=${facts.lang} theme=${facts.theme} rm=${facts.reducedMotion} fc=${facts.forcedColors}`
  )
  return payload
}

function closeApp(app, userData) {
  const child = app.process()
  return Promise.race([
    app.evaluate(({ app: electronApp }) => electronApp.exit(0)).catch(() => {}),
    delay(3000)
  ]).finally(() => {
    if (child && !child.killed && child.exitCode === null && child.signalCode === null) {
      if (child.pid) {
        killPidTree(child.pid)
      }
      try {
        child.kill('SIGKILL')
      } catch {}
    }
    if (userData) {
      killDaemonPids(userData)
    }
  })
}

async function measureSettingsRowsGeometry(page) {
  return page.evaluate(() => {
    const vw = window.innerWidth
    const main = document.querySelector('main')
    const mainRect = main ? main.getBoundingClientRect() : null
    const issues = []
    for (const row of document.querySelectorAll('[data-settings-row]')) {
      const r = row.getBoundingClientRect()
      if (r.width === 0 || r.height === 0) continue
      // Only inspect rows currently overlapping the vertical viewport
      if (r.bottom < 0 || r.top > window.innerHeight) continue
      const children = [...row.children]
      if (children.length < 2) continue
      const textEl = children[0]
      const ctrlEl = children[1]
      const tr = textEl.getBoundingClientRect()
      const cr = ctrlEl.getBoundingClientRect()
      // Check text actual content width (p/label) vs text container or control
      let textVisualRight = tr.right
      for (const node of textEl.querySelectorAll('label, p, span')) {
        const nr = node.getBoundingClientRect()
        if (nr.width > 0 && nr.height > 0) {
          textVisualRight = Math.max(textVisualRight, nr.right)
        }
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
          clippedRight,
          textRight: Math.round(textVisualRight),
          ctrlLeft: Math.round(cr.left),
          ctrlRight: Math.round(cr.right),
          viewportWidth: vw
        })
      }
    }
    return { ok: issues.length === 0, issues }
  })
}

async function waitForVisible(locator, timeout = 1000) {
  return locator.waitFor({ state: 'visible', timeout }).then(
    () => true,
    () => false
  )
}

async function main() {
  const { app, page, win, tempRoot, userData, isolation } = await launchIsolated({
    settings: {
      telemetry: { optedIn: false },
      uiLanguage: 'en',
      theme: 'light',
      agentDefaultSurface: 'chat',
      showArtifactsButton: true,
      showMobileButton: true,
      showAutomationsButton: true
    },
    onboarding: { flowVersion: 4, closedAt: 1, outcome: 'completed', lastCompletedStep: 5 },
    ui: {
      contextualToursAutoEligible: false,
      browserImportHintHidden: true,
      codexTerminalServerIsolationNoticeSeen: true
    }
  })

  const results = { isolation, checks: {} }

  try {
    await page.getByRole('heading', { name: 'Porpita' }).waitFor({ timeout: 20000 })
    await delay(600)

    // Dismiss Chat UI corner card if present
    const dismissTip = page
      .locator(
        '[role="complementary"] button[aria-label="Dismiss"], [role="complementary"] button[aria-label="关闭"]'
      )
      .first()
    if (await waitForVisible(dismissTip, 800)) {
      await dismissTip.click().catch(() => {})
      await delay(250)
    }

    // 1. Landing landmark & reduced motion dialog trap/escape check (Suite C + Landmarks)
    const landingMainCount = await page.locator('main').count()
    if (landingMainCount !== 1) {
      throw new Error(`Expected 1 <main> on Landing, got ${landingMainCount}`)
    }
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await delay(200)
    const addProjectBtn = page.locator('main').getByRole('button', { name: 'Add project' })
    await addProjectBtn.focus()
    await addProjectBtn.click()
    const dialog = page.locator("[data-slot='dialog-content']")
    await dialog.waitFor({ timeout: 5000 })
    await delay(200)
    const tabInsideDialog = []
    for (let i = 0; i < 4; i++) {
      await page.keyboard.press('Tab')
      const inside = await page.evaluate(() => {
        const d = document.querySelector("[data-slot='dialog-content']")
        return Boolean(d && d.contains(document.activeElement))
      })
      tabInsideDialog.push(inside)
    }
    results.dialogReducedMotion = await capture(page, 'i91-en-dialog-reduced-motion-1280', {
      tabInsideDialogAllTrue: tabInsideDialog.every(Boolean)
    })
    await page.keyboard.press('Escape')
    await dialog.waitFor({ state: 'detached', timeout: 5000 })
    await delay(250)
    const dialogEscapeFocus = await page.evaluate(() => {
      const active = document.activeElement
      const text = active?.textContent?.trim() ?? ''
      const restored = Boolean(
        active &&
          active !== document.body &&
          active.tagName === 'BUTTON' &&
          active.closest('main') &&
          text.includes('Add project')
      )
      return {
        restored,
        isBody: active === document.body,
        inMain: Boolean(active?.closest?.('main')),
        tag: active?.tagName ?? null,
        label: active?.getAttribute('aria-label') || text.slice(0, 100) || null
      }
    })
    results.checks.dialogEscapeFocusRestored = dialogEscapeFocus.restored
    results.checks.dialogEscapeFocusDetail = dialogEscapeFocus
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await delay(200)

    // 2. Open Settings -> Appearance (Suite A: Theme, Contrast, Forced Colors, Landmarks, Aria-Labels)
    await page.getByRole('button', { name: 'Settings', exact: true }).first().click()
    const settingsNav = page.getByRole('navigation', { name: 'Settings' })
    await settingsNav.waitFor({ timeout: 10000 })
    await settingsNav.getByRole('button', { name: /^Appearance/ }).first().click()
    await delay(400)

    // Verify accessibility controls exist
    await page.getByRole('textbox', { name: 'Search settings' }).waitFor({ timeout: 5000 })
    await page.getByRole('button', { name: 'Zoom out' }).waitFor({ timeout: 5000 })
    await page.getByRole('button', { name: 'Zoom in' }).waitFor({ timeout: 5000 })
    results.enAppearanceLight = await capture(page, 'i91-en-settings-appearance-light-1280')
    if (results.enAppearanceLight.mainCount !== 1 || results.enAppearanceLight.nestedMainCount !== 0) {
      throw new Error(
        `Invalid main landmark count in Settings: ${JSON.stringify(results.enAppearanceLight)}`
      )
    }

    // Scroll Settings main slightly and verify ArrowLeft on Theme radiogroup switches Light -> Dark while preserving scroll
    await page.evaluate(() => {
      const m = document.querySelector('main')
      if (m) m.scrollTop = 120
    })
    const scrollBeforeThemeSwitch = await page.evaluate(
      () => document.querySelector('main')?.scrollTop ?? 0
    )
    const themeGroup = page.getByRole('radiogroup', { name: 'Theme', exact: true })
    const lightRadio = themeGroup.getByRole('radio', { name: 'Light', exact: true })
    await lightRadio.focus()
    await page.keyboard.press('ArrowLeft') // Light -> Dark
    await delay(300)
    const darkClassAfterArrow = await page.evaluate(() =>
      document.documentElement.classList.contains('dark')
    )
    const scrollAfterThemeSwitch = await page.evaluate(
      () => document.querySelector('main')?.scrollTop ?? 0
    )
    results.checks.themeArrowSwitchPreservesScroll = {
      darkClassAfterArrow,
      scrollBeforeThemeSwitch,
      scrollAfterThemeSwitch
    }
    results.enAppearanceDark = await capture(page, 'i91-en-settings-appearance-dark-1280')

    // Test System theme live OS colorScheme toggle (trigger Blink paint in show:false window so MediaQueryList change fires)
    await themeGroup.getByRole('radio', { name: 'System', exact: true }).click()
    await page.emulateMedia({ colorScheme: 'light' })
    await page.screenshot({ scale: 'css', timeout: 8000 }).catch(() => {})
    await delay(200)
    const systemLightOk = await page.evaluate(
      () => !document.documentElement.classList.contains('dark')
    )
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.screenshot({ scale: 'css', timeout: 8000 }).catch(() => {})
    await delay(200)
    const systemDarkOk = await page.evaluate(() =>
      document.documentElement.classList.contains('dark')
    )
    results.checks.systemColorSchemeLiveFlip = { systemLightOk, systemDarkOk }
    // Keep dark for forced-colors & zh checks
    await themeGroup.getByRole('radio', { name: 'Dark', exact: true }).click()
    await delay(200)

    // Test forced-colors: active + prefers-contrast: more (use Tab so Chromium activates :focus-visible)
    await page.emulateMedia({ forcedColors: 'active', contrast: 'more' })
    await page.getByRole('button', { name: 'Zoom out' }).focus()
    await page.keyboard.press('Tab')
    await delay(250)
    results.enForcedColors = await capture(page, 'i91-en-settings-forced-colors-1280')
    await page.emulateMedia({ forcedColors: 'none', contrast: 'no-preference' })
    await delay(200)

    // 3. Suite B: UI Zoom >= 150% (UI_ZOOM_BASE = 1.2 steps 110..144..158%) + Narrow 820x580 + 600x400
    const zoomInBtn = page.getByRole('button', { name: 'Zoom in' })
    const zoomContainer = zoomInBtn.locator('..')
    let capturedZoomPct = null
    for (let i = 0; i < 10; i++) {
      const txt = await zoomContainer
        .locator('span')
        .first()
        .textContent()
        .catch(() => '')
      const pct = Number.parseInt((txt || '').replace(/[^0-9]/g, ''), 10)
      if (Number.isFinite(pct)) {
        capturedZoomPct = pct
        if (pct >= 150) break
      }
      if (await zoomInBtn.isEnabled()) {
        await zoomInBtn.click()
        await delay(100)
      } else {
        break
      }
    }
    await delay(250)
    const zoom150Rows = await measureSettingsRowsGeometry(page)
    results.checks.zoom150SettingsRowsOk = zoom150Rows.ok
    results.enZoom150 = await capture(page, 'i91-en-settings-zoom-150-1280', {
      zoomPercent: capturedZoomPct,
      settingsRowsGeometry: zoom150Rows
    })
    const resetZoomBtn = zoomContainer.getByRole('button', { name: 'Reset', exact: true })
    if (await resetZoomBtn.isEnabled()) {
      await resetZoomBtn.click()
      await delay(200)
    }

    await win.evaluate((w) => w.setContentSize(820, 580))
    await delay(400)
    const narrow820Rows = await measureSettingsRowsGeometry(page)
    results.checks.narrow820SettingsRowsOk = narrow820Rows.ok
    results.enNarrow820 = await capture(page, 'i91-en-settings-narrow-820', {
      settingsRowsGeometry: narrow820Rows
    })

    await win.evaluate((w) => w.setContentSize(600, 400))
    await delay(400)
    const narrow600Rows = await measureSettingsRowsGeometry(page)
    results.checks.narrow600SettingsRowsOk = narrow600Rows.ok
    results.enNarrow600 = await capture(page, 'i91-en-settings-narrow-600', {
      settingsRowsGeometry: narrow600Rows
    })

    await win.evaluate((w) => w.setContentSize(1280, 800))
    await delay(400)

    // 4. Suite C (Settings Reduced Motion check)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await delay(200)
    const sectionChevronTransition = await page.evaluate(() => {
      const btn = [...document.querySelectorAll('button[aria-expanded]')].find((b) =>
        b.textContent?.includes('Window & Sidebar')
      )
      const svg = btn?.querySelector('svg')
      return svg ? getComputedStyle(svg).transitionDuration : null
    })
    results.checks.settingsReducedMotion = { sectionChevronTransition }
    await page.emulateMedia({ reducedMotion: 'no-preference' })

    // 5. Suite D: Live Locale Switching en -> zh -> ja (P.13 & F03.3)
    await page.evaluate(() => {
      const m = document.querySelector('main')
      if (m) m.scrollTop = 0
    })
    const langTrigger = page.getByRole('combobox').filter({ hasText: /English|System/ }).first()
    await langTrigger.click()
    await page.getByRole('option', { name: '中文（简体）', exact: true }).click()
    await delay(700)
    results.zhAppearance = await capture(page, 'i91-zh-settings-appearance-dark-1280')
    if (results.zhAppearance.lang !== 'zh') {
      throw new Error(`Expected lang='zh', got '${results.zhAppearance.lang}'`)
    }
    const zhAppearanceText = results.zhAppearance.text
    for (const forbidden of [
      'Editor theme',
      'Light editor theme',
      'Dark editor theme',
      'Same as app theme',
      'Reduce Visual Effects',
      'Window Material',
      'Browse themes',
      'Import from Kitty',
      'Orca'
    ]) {
      if (zhAppearanceText.includes(forbidden)) {
        throw new Error(`Forbidden untranslated/Orca text in zh Appearance: ${forbidden}`)
      }
    }

    // Switch to Japanese (ja) live without restart
    const langTriggerZh = page.getByRole('combobox').filter({ hasText: /中文（简体）/ }).first()
    await langTriggerZh.click()
    await page.getByRole('option', { name: '日本語', exact: true }).click()
    await delay(700)
    results.jaAppearance = await capture(page, 'i91-ja-settings-appearance-1280')
    if (results.jaAppearance.lang !== 'ja') {
      throw new Error(`Expected lang='ja', got '${results.jaAppearance.lang}'`)
    }
    const jaAppearanceText = results.jaAppearance.text
    for (const forbidden of [
      'Editor theme',
      'Light editor theme',
      'Dark editor theme',
      'Same as app theme',
      'Reduce Visual Effects',
      'Window Material',
      'Browse themes',
      'Import from Kitty',
      'Orca'
    ]) {
      if (jaAppearanceText.includes(forbidden)) {
        throw new Error(`Forbidden untranslated/Orca text in ja Appearance: ${forbidden}`)
      }
    }

    results.checks.localesLangFlow = {
      initial: results.enAppearanceLight.lang,
      zh: results.zhAppearance.lang,
      ja: results.jaAppearance.lang
    }
  } finally {
    await closeApp(app, userData)
    try {
      fs.rmSync(tempRoot, { recursive: true, force: true })
    } catch {}
  }

  const summary = {
    version: isolation.version,
    electronVersion: isolation.electronVersion,
    windowIsolation: isolation.windows,
    checks: results.checks,
    captures: {
      dialogReducedMotion: results.dialogReducedMotion.imageFile,
      enAppearanceLight: results.enAppearanceLight.imageFile,
      enAppearanceDark: results.enAppearanceDark.imageFile,
      enForcedColors: results.enForcedColors.imageFile,
      enZoom150: results.enZoom150.imageFile,
      enNarrow820: results.enNarrow820.imageFile,
      enNarrow600: results.enNarrow600.imageFile,
      zhAppearance: results.zhAppearance.imageFile,
      jaAppearance: results.jaAppearance.imageFile
    }
  }
  fs.writeFileSync(path.join(outputDir, 'run.json'), JSON.stringify(summary, null, 2) + '\n')
  console.log('SUMMARY:', JSON.stringify(summary, null, 2))

  const failures = []
  if (results.checks.dialogEscapeFocusRestored !== true) {
    failures.push(
      `dialogEscapeFocusRestored=${JSON.stringify(results.checks.dialogEscapeFocusDetail ?? results.checks.dialogEscapeFocusRestored)}`
    )
  }
  const langFlow = results.checks.localesLangFlow
  if (!langFlow || langFlow.initial !== 'en' || langFlow.zh !== 'zh' || langFlow.ja !== 'ja') {
    failures.push(`localesLangFlow=${JSON.stringify(langFlow)}`)
  }
  if (results.dialogReducedMotion?.extra?.tabInsideDialogAllTrue !== true) {
    failures.push('tabInsideDialogAllTrue !== true')
  }
  if (failures.length > 0) {
    throw new Error(`Round 91 checks failed: ${failures.join('; ')}`)
  }
  process.exit(0)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
