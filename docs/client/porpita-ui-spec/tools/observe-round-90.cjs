const { createRequire } = require('node:module')
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')

const source = process.env.PORPITA_SPEC_SOURCE || 'D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03'
const entry = process.env.PORPITA_SPEC_ENTRY || path.join(source, 'out/main/index.js')
const load = createRequire(path.join(source, 'package.json'))
const { _electron } = load('playwright')
const executablePath = process.env.PORPITA_SPEC_EXE || load('electron')
const outputDir =
  process.argv[2] ||
  'D:/Chatgpt/Agent-collaboration/docs/client/porpita-ui-spec/evidence/iteration-90-windows'

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

function redactPairing(text) {
  return String(text)
    .replace(/orca:\/\/pair#[^\s"']+/g, 'orca://pair#<redacted>')
    .replace(/[A-Za-z0-9+/]{32,}={0,2}/g, (m) => (m.length > 48 ? '<redacted-b64>' : m))
}

async function launchIsolated(seedData, extraArgs = []) {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'porpita-r90-'))
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
    const modal = document.querySelector('[data-onboarding-modal]')
    const tourPanel = document.querySelector('[data-contextual-tour-panel]')
    const landingScroll = document.querySelector('.overflow-y-auto')
    const modalFooter = modal?.querySelector('footer')
    return {
      size: [window.innerWidth, window.innerHeight],
      dpr: window.devicePixelRatio,
      lang: document.documentElement.lang,
      theme: document.documentElement.classList.contains('dark') ? 'dark' : 'light',
      focusTag: active?.tagName ?? null,
      focusLabel:
        active?.getAttribute('aria-label') || active?.textContent?.trim().slice(0, 100) || null,
      focusInsideModal: modal ? modal.contains(active) : null,
      modalOverflow: modal
        ? {
            scrollWidth: modal.scrollWidth,
            clientWidth: modal.clientWidth,
            rect: modal.getBoundingClientRect().toJSON(),
            footerRect: modalFooter ? modalFooter.getBoundingClientRect().toJSON() : null
          }
        : null,
      tourPanelRect: tourPanel
        ? {
            rect: tourPanel.getBoundingClientRect().toJSON(),
            scrollWidth: tourPanel.scrollWidth,
            clientWidth: tourPanel.clientWidth,
            scrollHeight: tourPanel.scrollHeight,
            clientHeight: tourPanel.clientHeight
          }
        : null,
      landingScroll: landingScroll
        ? {
            scrollHeight: landingScroll.scrollHeight,
            clientHeight: landingScroll.clientHeight,
            scrollTop: landingScroll.scrollTop
          }
        : null,
      text: document.body.innerText.slice(0, 8000),
      dialogs: [...document.querySelectorAll('[role=dialog]')]
        .filter((x) => x.getClientRects().length)
        .map((x) => x.innerText.slice(0, 2200)),
      buttons: [...document.querySelectorAll('button,[role=tab],[role=menuitem]')]
        .filter((b) => b.getClientRects().length)
        .map((b) => ({
          text: b.innerText.trim(),
          label: b.getAttribute('aria-label'),
          ariaPressed: b.getAttribute('aria-pressed'),
          disabled: b.hasAttribute('disabled')
        }))
        .slice(0, 120)
    }
  })

  const imageFile = `${id}.png`
  await page.screenshot({ path: path.join(outputDir, imageFile), scale: 'css', timeout: 8000 })
  const payload = JSON.parse(
    redactPairing(
      JSON.stringify({
        ...facts,
        extra,
        imageFile,
        imageMethod: 'CDP screenshot'
      })
    )
  )
  fs.writeFileSync(path.join(outputDir, `${id}.json`), JSON.stringify(payload, null, 2) + '\n')
  console.log(`Captured ${id}: ${facts.size.join('x')} lang=${facts.lang} focus=${facts.focusLabel}`)
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

const OPEN_ONBOARDING = {
  flowVersion: 4,
  closedAt: null,
  outcome: null,
  lastCompletedStep: -1,
  checklist: {
    addedRepo: false,
    choseAgent: false,
    ranFirstAgent: false,
    ranSecondAgentOnSameTask: false,
    triedCmdJ: false,
    shapedSidebar: false,
    reviewedDiff: false,
    openedPr: false,
    addedFolder: false,
    openedFile: false,
    ranAgentOnFile: false,
    dismissed: false
  }
}

async function runEnOnboardingSuite() {
  const results = {}
  const { app, page, tempRoot, isolation } = await launchIsolated({
    settings: {
      telemetry: { optedIn: false, onboardingLanguageCohort: 'treatment' },
      uiLanguage: 'en',
      theme: 'light'
    },
    onboarding: OPEN_ONBOARDING,
    ui: {
      contextualToursAutoEligible: false,
      browserImportHintHidden: true,
      codexTerminalServerIsolationNoticeSeen: true
    }
  })

  try {
    await page.locator('[data-onboarding-modal]').waitFor({ timeout: 20000 })
    await delay(800)

    const tabChecks = []
    for (let i = 0; i < 10; i++) {
      await page.keyboard.press('Tab')
      const inside = await page.evaluate(() => {
        const modal = document.querySelector('[data-onboarding-modal]')
        return Boolean(modal && modal.contains(document.activeElement))
      })
      tabChecks.push(inside)
    }
    results.enOnboarding = await capture(page, 'i90-en-onboarding-agent-surface-1280', {
      tabChecksAllInsideModal: tabChecks.every(Boolean)
    })

    // Verify main-process English Help menu items resolve to Porpita (not Orca)
    results.enHelpMenuLabels = await app.evaluate(({ Menu }) => {
      const menu = Menu.getApplicationMenu()
      const help = menu?.items.find((item) => item.label === 'Help')
      return help?.submenu?.items.map((item) => item.label).filter(Boolean) ?? []
    })

    // Verify OnboardingSkipConfirmationDialog cancel restores focus inside [data-onboarding-modal]
    const continueBtn = page.getByRole('button', { name: 'Continue' })
    await continueBtn.focus()
    await page.keyboard.press('Escape')
    const skipDialog = page.getByRole('dialog', { name: 'Skip onboarding?' })
    await skipDialog.waitFor({ timeout: 5000 })
    await delay(200)
    await page.getByRole('button', { name: 'No, keep going' }).click()
    await skipDialog.waitFor({ state: 'detached', timeout: 5000 })
    await delay(350)
    results.enOnboardingSkipCancelFocus = await page.evaluate(() => {
      const modal = document.querySelector('[data-onboarding-modal]')
      const active = document.activeElement
      return {
        insideModal: Boolean(modal && modal.contains(active)),
        isBody: active === document.body,
        focusTag: active?.tagName ?? null,
        focusLabel: active?.getAttribute('aria-label') || active?.textContent?.trim().slice(0, 80) || null
      }
    })
    if (!results.enOnboardingSkipCancelFocus.insideModal || results.enOnboardingSkipCancelFocus.isBody) {
      throw new Error(
        `Onboarding skip cancel lost focus: ${JSON.stringify(results.enOnboardingSkipCancelFocus)}`
      )
    }

    await continueBtn.click()
    await delay(500)
    results.enOnboardingAgent = await capture(page, 'i90-en-onboarding-agent-1280')

    results.isolation = isolation
  } finally {
    await closeApp(app)
    try {
      fs.rmSync(tempRoot, { recursive: true, force: true })
    } catch {}
  }
  return results
}

async function runZhOnboardingSuite() {
  const results = {}
  const { app, page, win, tempRoot, isolation } = await launchIsolated({
    settings: {
      telemetry: { optedIn: false, onboardingLanguageCohort: 'treatment' },
      uiLanguage: 'zh',
      theme: 'light'
    },
    onboarding: OPEN_ONBOARDING,
    ui: {
      contextualToursAutoEligible: false,
      browserImportHintHidden: true,
      codexTerminalServerIsolationNoticeSeen: true
    }
  })

  try {
    await page.locator('[data-onboarding-modal]').waitFor({ timeout: 20000 })
    await delay(800)
    results.zhOnboardingSurface = await capture(page, 'i90-zh-onboarding-agent-surface-1280')

    await page.getByRole('button', { name: /继续/ }).click()
    await delay(600)
    results.zhOnboardingAgent = await capture(page, 'i90-zh-onboarding-agent-1280')

    await page.getByRole('button', { name: /继续/ }).click()
    await delay(600)
    results.zhOnboardingTheme = await capture(page, 'i90-zh-onboarding-theme-1280')

    await win.evaluate((w) => w.setContentSize(600, 400))
    await delay(500)
    results.zhOnboardingNarrow = await capture(page, 'i90-zh-onboarding-narrow-600')

    await page.getByRole('button', { name: /稍后设置/ }).click()
    await page.locator('[data-onboarding-modal]').waitFor({ state: 'detached', timeout: 10000 })
    await delay(400)
    results.isolation = isolation
  } finally {
    await closeApp(app)
    try {
      fs.rmSync(tempRoot, { recursive: true, force: true })
    } catch {}
  }
  return results
}

async function runLocaleCompletedSuite(locale) {
  const results = {}
  const { app, page, win, tempRoot, isolation } = await launchIsolated({
    settings: {
      telemetry: { optedIn: false },
      uiLanguage: locale,
      theme: locale === 'zh' ? 'dark' : 'light',
      agentDefaultSurface: 'chat',
      showArtifactsButton: true,
      showMobileButton: true,
      showAutomationsButton: true
    },
    onboarding: { flowVersion: 4, closedAt: 1, outcome: 'completed', lastCompletedStep: 5 },
    ui: {
      contextualToursAutoEligible: true,
      browserImportHintHidden: true,
      codexTerminalServerIsolationNoticeSeen: true
    }
  })

  try {
    await page.getByRole('heading', { name: 'Porpita' }).waitFor({ timeout: 20000 })
    await delay(800)
    // Dismiss Chat UI corner card if present so Landing/Artifacts/Mobile at narrow/wide are unobstructed
    const dismissTip = page
      .locator('[role="complementary"] button[aria-label="Dismiss"], [role="complementary"] button[aria-label="关闭"]')
      .first()
    if (await dismissTip.isVisible().catch(() => false)) {
      await dismissTip.click().catch(() => {})
      await delay(300)
    }

    // 1. Landing at 1280x800 and 600x400 (en & zh)
    results.landingWide = await capture(page, `i90-${locale}-landing-1280`)
    await win.evaluate((w) => w.setContentSize(600, 400))
    await delay(600)
    const scrollInfo = await page.evaluate(() => {
      const h1 = [...document.querySelectorAll('h1')].find((el) => el.textContent?.trim() === 'Porpita')
      const host = h1?.closest('.overflow-y-auto')
      if (!host) return null
      const initialTop = host.scrollTop
      host.scrollTop = host.scrollHeight
      const maxTop = host.scrollTop
      host.scrollTop = 0
      return {
        scrollHeight: host.scrollHeight,
        clientHeight: host.clientHeight,
        initialTop,
        maxTop,
        canScroll: host.scrollHeight > host.clientHeight ? maxTop > 0 : true
      }
    })
    results.landingNarrow = await capture(page, `i90-${locale}-landing-narrow-600`, { scrollInfo })
    await win.evaluate((w) => w.setContentSize(1280, 800))
    await delay(500)

    // 2. Artifacts Empty / Unavailable State (L.04) directly from Landing so Back returns to Landing
    const artifactsBtnName = locale === 'zh' ? '工件' : 'Artifacts'
    const artifactsBtn = page.getByRole('button', { name: artifactsBtnName, exact: true }).first()
    await artifactsBtn.click()
    await delay(600)
    results.artifactsUnavailable = await capture(page, `i90-${locale}-artifacts-unavailable-1280`)

    const backBtnName = locale === 'zh' ? '返回工作区' : 'Back to workspace'
    await page.getByRole('button', { name: backBtnName }).click()
    await delay(500)
    results.afterBackHeading = await page
      .getByRole('heading', { name: 'Porpita' })
      .isVisible()
      .catch(() => false)

    // 3. Contextual Tour (Automations) + narrow window + focus restoration on Skip
    const autoBtnName = locale === 'zh' ? '自动化' : 'Automations'
    const autoBtn = page.getByRole('button', { name: autoBtnName, exact: true }).first()
    await autoBtn.focus()
    await autoBtn.click()
    const tourPanel = page.locator('[data-contextual-tour-panel="automations"]')
    await tourPanel.waitFor({ timeout: 10000 })
    await delay(600)
    results.tourWide = await capture(page, `i90-${locale}-tour-1280`)

    await win.evaluate((w) => w.setContentSize(600, 400))
    await delay(750)
    results.tourNarrow = await capture(page, `i90-${locale}-tour-narrow-600`)

    // Dismiss tour via skip button and verify focus is restored (not BODY)
    const skipBtn = tourPanel.locator('[data-contextual-tour-dismiss]')
    await skipBtn.click()
    await delay(400)
    const afterTourFocus = await page.evaluate(() => ({
      tag: document.activeElement?.tagName ?? null,
      text: document.activeElement?.textContent?.trim().slice(0, 80) || null,
      label: document.activeElement?.getAttribute('aria-label') || null,
      isBody: document.activeElement === document.body
    }))
    results.afterTourFocus = afterTourFocus
    await win.evaluate((w) => w.setContentSize(1280, 800))
    await delay(500)

    // 4. Mobile Entry (M.01)
    const mobileBtn = page.getByRole('button', { name: /^Porpita (Mobile|手机端)/ }).first()
    await mobileBtn.waitFor({ timeout: 5000 })
    await mobileBtn.click()
    await delay(700)
    results.mobileIntro = await capture(page, `i90-${locale}-mobile-intro-1280`)
    if (locale === 'zh') {
      await page
        .locator('.mp-screen-slide:nth-child(3).is-active')
        .waitFor({ timeout: 13000 })
        .catch(() => {})
      await delay(500)
      results.mobileTerminalSlide = await capture(page, 'i90-zh-mobile-terminal-slide-1280')
    }

    const getCodeName = locale === 'zh' ? '获取配对码' : 'Get a pairing code'
    await page.getByRole('button', { name: getCodeName }).click()
    await page.locator('img[src^="data:image/"]').first().waitFor({ timeout: 8000 }).catch(() => {})
    await delay(500)
    results.mobilePairing = await capture(page, `i90-${locale}-mobile-pairing-1280`)

    // 5. Settings -> Artifacts & Porpita Account in zh
    if (locale === 'zh') {
      await page.getByRole('button', { name: '设置', exact: true }).first().click()
      const settingsAside = page.locator('aside').filter({ hasText: '返回应用' })
      await settingsAside.waitFor({ timeout: 10000 })
      await delay(400)
      await settingsAside.getByRole('button', { name: /^工件/ }).first().click()
      await delay(500)
      results.zhSettingsArtifacts = await capture(page, 'i90-zh-settings-artifacts-1280')

      await settingsAside.getByRole('button', { name: /^Porpita 账户/ }).first().click()
      await delay(500)
      results.zhSettingsAccount = await capture(page, 'i90-zh-settings-account-1280')
    }
    results.isolation = isolation
  } finally {
    await closeApp(app)
    try {
      fs.rmSync(tempRoot, { recursive: true, force: true })
    } catch {}
  }
  return results
}

async function main() {
  const enOnboardingResults = await runEnOnboardingSuite()
  const zhOnboardingResults = await runZhOnboardingSuite()
  const enResults = await runLocaleCompletedSuite('en')
  const zhResults = await runLocaleCompletedSuite('zh')
  const summary = {
    version: enResults.isolation.version,
    electronVersion: enResults.isolation.electronVersion,
    windowIsolation: {
      enOnboarding: enOnboardingResults.isolation.windows,
      zhOnboarding: zhOnboardingResults.isolation.windows,
      en: enResults.isolation.windows,
      zh: zhResults.isolation.windows
    },
    checks: {
      enOnboardingTabChecksAllInsideModal:
        enOnboardingResults.enOnboarding.extra.tabChecksAllInsideModal,
      enOnboardingSkipCancelFocus: enOnboardingResults.enOnboardingSkipCancelFocus,
      enHelpMenuLabels: enOnboardingResults.enHelpMenuLabels,
      zhLandingScroll: zhResults.landingNarrow.extra.scrollInfo,
      enLandingScroll: enResults.landingNarrow.extra.scrollInfo,
      enAfterTourFocus: enResults.afterTourFocus,
      zhAfterTourFocus: zhResults.afterTourFocus,
      enArtifactsBackToWorkspace: enResults.afterBackHeading,
      zhArtifactsBackToWorkspace: zhResults.afterBackHeading
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
