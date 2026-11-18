const { createRequire } = require('node:module')
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')

const source =
  process.env.PORPITA_SPEC_SOURCE || 'D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03'
const entry = process.env.PORPITA_SPEC_ENTRY || path.join(source, 'out/main/index.js')
const load = createRequire(path.join(source, 'package.json'))
const { _electron } = load('playwright')
const executablePath = process.env.PORPITA_SPEC_EXE || load('electron')
const outputDir =
  process.argv[2] ||
  'D:/Chatgpt/Agent-collaboration/docs/client/porpita-ui-spec/evidence/iteration-91-windows'

fs.mkdirSync(outputDir, { recursive: true })

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function buildIsolatedEnv(userData, home, lang = 'en_US.UTF-8') {
  const env = Object.fromEntries(
    Object.entries(process.env).filter(
      ([key, value]) =>
        value !== undefined &&
        !/^(HOME|USERPROFILE|HOMEDRIVE|HOMEPATH|APPDATA|LOCALAPPDATA|CLAUDE_CONFIG_DIR|ELECTRON_RUN_AS_NODE|ORCA_.*|PORPITA_.*|ACS_.*|CODEX_.*|OPENAI_.*|ANTHROPIC_.*|GH_.*|GITHUB_.*|GITLAB_.*|AWS_.*|AZURE_.*)$/i.test(
          key
        )
    )
  )
  return Object.assign(env, {
    HOME: home,
    USERPROFILE: home,
    APPDATA: path.join(home, 'AppData/Roaming'),
    LOCALAPPDATA: path.join(home, 'AppData/Local'),
    ORCA_BACKGROUND_LAUNCH: '1',
    ORCA_E2E_HEADLESS: '1',
    ORCA_E2E_USER_DATA_DIR: userData,
    ORCA_E2E_HOME_DIR: home,
    GIT_CONFIG_NOSYSTEM: '1',
    GIT_CONFIG_GLOBAL: path.join(home, 'gitconfig'),
    LANG: lang
  })
}

async function launchIsolated(seedData, extraArgs = []) {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'porpita-r91-'))
  const userData = path.join(tempRoot, 'profile')
  const home = path.join(userData, 'home')
  fs.mkdirSync(path.join(home, 'AppData/Local'), { recursive: true })
  fs.mkdirSync(path.join(home, 'AppData/Roaming'), { recursive: true })
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
    path.resolve(isolation.home).toLowerCase() !== path.resolve(home).toLowerCase() ||
    path.resolve(isolation.profile).toLowerCase() !== path.resolve(userData).toLowerCase() ||
    !isolation.windows.length ||
    isolation.windows.some((w) => w.visible || w.focused)
  ) {
    throw new Error(`Window/profile isolation violated: ${JSON.stringify(isolation)}`)
  }
  await page.locator('body').waitFor({ timeout: 15000 })
  return { app, page, win, tempRoot, isolation }
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
      text: document.body.innerText.slice(0, 8000)
    }
  })

  const imageFile = `${id}.png`
  await page.screenshot({ path: path.join(outputDir, imageFile), scale: 'css', timeout: 8000 })
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

function closeApp(app) {
  const child = app.process()
  return Promise.race([
    app.evaluate(({ app: electronApp }) => electronApp.exit(0)).catch(() => {}),
    delay(3000)
  ]).finally(() => {
    if (child && !child.killed && child.exitCode === null) {
      try {
        child.kill('SIGKILL')
      } catch {}
    }
  })
}

async function main() {
  const { app, page, win, tempRoot, isolation } = await launchIsolated({
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
      .locator('[role="complementary"] button[aria-label="Dismiss"], [role="complementary"] button[aria-label="关闭"]')
      .first()
    if (await dismissTip.isVisible().catch(() => false)) {
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
    const addProjectBtn = page.getByRole('button', { name: 'Add project' })
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
    await delay(200)
    const restoredToTrigger = await page.evaluate(() => {
      const active = document.activeElement
      return active?.textContent?.includes('Add project') ?? false
    })
    results.checks.dialogEscapeFocusRestored = restoredToTrigger
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
      throw new Error(`Invalid main landmark count in Settings: ${JSON.stringify(results.enAppearanceLight)}`)
    }

    // Scroll Settings main slightly and verify ArrowRight on Theme radiogroup switches Light -> Dark while preserving scroll
    await page.evaluate(() => {
      const m = document.querySelector('main')
      if (m) m.scrollTop = 120
    })
    const scrollBeforeThemeSwitch = await page.evaluate(() => document.querySelector('main')?.scrollTop ?? 0)
    const themeGroup = page.getByRole('radiogroup', { name: 'Theme' })
    const lightRadio = themeGroup.getByRole('radio', { name: 'Light' })
    await lightRadio.focus()
    await page.keyboard.press('ArrowLeft') // Light -> Dark
    await delay(300)
    const darkClassAfterArrow = await page.evaluate(() => document.documentElement.classList.contains('dark'))
    const scrollAfterThemeSwitch = await page.evaluate(() => document.querySelector('main')?.scrollTop ?? 0)
    results.checks.themeArrowSwitchPreservesScroll = {
      darkClassAfterArrow,
      scrollBeforeThemeSwitch,
      scrollAfterThemeSwitch
    }
    results.enAppearanceDark = await capture(page, 'i91-en-settings-appearance-dark-1280')

    // Test System theme live OS colorScheme toggle
    await themeGroup.getByRole('radio', { name: 'System' }).click()
    await page.emulateMedia({ colorScheme: 'light' })
    await delay(200)
    const systemLightOk = await page.evaluate(() => !document.documentElement.classList.contains('dark'))
    await page.emulateMedia({ colorScheme: 'dark' })
    await delay(200)
    const systemDarkOk = await page.evaluate(() => document.documentElement.classList.contains('dark'))
    results.checks.systemColorSchemeLiveFlip = { systemLightOk, systemDarkOk }
    // Keep dark for forced-colors & zh checks
    await themeGroup.getByRole('radio', { name: 'Dark' }).click()
    await delay(200)

    // Test forced-colors: active + prefers-contrast: more
    await page.emulateMedia({ forcedColors: 'active', contrast: 'more' })
    await page.getByRole('button', { name: 'Zoom in' }).focus()
    await delay(250)
    results.enForcedColors = await capture(page, 'i91-en-settings-forced-colors-1280')
    await page.emulateMedia({ forcedColors: 'none', contrast: 'no-preference' })
    await delay(200)

    // 3. Suite B: UI Zoom 150% + Narrow 820x580 + 600x400
    const zoomInBtn = page.getByRole('button', { name: 'Zoom in' })
    for (let i = 0; i < 6; i++) {
      const txt = await page.locator('text=/\\d+%/').first().textContent().catch(() => '')
      if (txt && txt.includes('150%')) break
      if (await zoomInBtn.isEnabled()) {
        await zoomInBtn.click()
        await delay(100)
      }
    }
    await delay(250)
    results.enZoom150 = await capture(page, 'i91-en-settings-zoom-150-1280')
    const resetZoomBtn = page.getByRole('button', { name: 'Reset' }).first()
    if (await resetZoomBtn.isEnabled()) {
      await resetZoomBtn.click()
      await delay(200)
    }

    await win.evaluate((w) => w.setContentSize(820, 580))
    await delay(400)
    results.enNarrow820 = await capture(page, 'i91-en-settings-narrow-820')

    await win.evaluate((w) => w.setContentSize(600, 400))
    await delay(400)
    results.enNarrow600 = await capture(page, 'i91-en-settings-narrow-600')

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
    await page.getByRole('option', { name: '中文（简体）' }).click()
    await delay(700)
    results.zhAppearance = await capture(page, 'i91-zh-settings-appearance-dark-1280')
    if (results.zhAppearance.lang !== 'zh') {
      throw new Error(`Expected lang='zh', got '${results.zhAppearance.lang}'`)
    }
    const zhAppearanceText = results.zhAppearance.text
    for (const forbidden of ['Editor theme', 'Reduce Visual Effects', 'Window Material', 'Browse themes', 'Orca']) {
      if (zhAppearanceText.includes(forbidden)) {
        throw new Error(`Forbidden untranslated/Orca text in zh Appearance: ${forbidden}`)
      }
    }

    // Switch to Japanese (ja) live without restart
    const langTriggerZh = page.getByRole('combobox').filter({ hasText: /中文（简体）/ }).first()
    await langTriggerZh.click()
    await page.getByRole('option', { name: '日本語' }).click()
    await delay(700)
    results.jaAppearance = await capture(page, 'i91-ja-settings-appearance-1280')
    if (results.jaAppearance.lang !== 'ja') {
      throw new Error(`Expected lang='ja', got '${results.jaAppearance.lang}'`)
    }

    results.checks.localesLangFlow = {
      initial: results.enAppearanceLight.lang,
      zh: results.zhAppearance.lang,
      ja: results.jaAppearance.lang
    }
  } finally {
    await closeApp(app)
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
  process.exit(0)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
