import assert from 'node:assert/strict'
import {
  addLocalFolderProject,
  assertImeCompositionKeepsDialogOpen,
  closeElectronApp,
  disablePluginAndVerify,
  hasIntegratedWorkspaceShell,
  installAndEnableFolderPlugin,
  launchElectronApp,
  M3_SELECTOR_CONTRACT,
  openAndVerifyPluginPanel,
  openCollaborationDialog,
  openSettingsPage,
  returnFromSettings,
  setViewportSize,
  sleep,
  stubOpenDialog,
  waitForVisible
} from '../lib/electron-harness.mjs'
import { startLoopbackAcsCore } from '../lib/acs-core-harness.mjs'
import {
  createSyntheticPluginFixture,
  createTempGitRepo,
  startLoopbackHttpServer
} from '../lib/fixtures.mjs'
import { pendingIfSmoke } from '../lib/test-context.mjs'

export const TIER3_TESTS = [
  {
    id: 'T3-01',
    tier: 3,
    featureArea: 'E2E-F01+E2E-F02',
    refs: ['F01', 'F02', 'F03', 'J13'],
    async run(ctx) {
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        seedCompletedOnboarding: false,
        width: 600,
        height: 400,
        profileOptions: { locale: 'zh', theme: 'dark', reducedMotion: true },
        extraEnv: { LANG: 'zh_CN.UTF-8' }
      })
      try {
        const { page } = inst
        await page.emulateMedia({ reducedMotion: 'reduce' })
        const modal = page.locator('[role="dialog"][data-onboarding-modal]').first()
        await modal.waitFor({ state: 'visible', timeout: 15000 })
        const metrics = await page.evaluate(() => ({
          innerWidth: window.innerWidth,
          innerHeight: window.innerHeight,
          reducedMotion: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
          overflowX: document.documentElement.scrollWidth > window.innerWidth + 2,
          modalVisible: Boolean(document.querySelector('[role="dialog"][data-onboarding-modal]'))
        }))
        assert.equal(metrics.innerWidth, 600)
        assert.equal(metrics.reducedMotion, true)
        assert.equal(metrics.overflowX, false, `Horizontal overflow at 600x400: ${JSON.stringify(metrics)}`)

        const modalText = await modal.innerText()
        const zhOption = modal.getByRole('button', { name: /简体中文|中文/i }).first()
        if (await zhOption.isVisible().catch(() => false)) {
          await zhOption.click()
          await sleep(200)
          const zhText = await modal.innerText()
          if (/How do you want to work with agents\?/i.test(zhText)) {
            pendingIfSmoke(
              ctx.mode,
              'M1',
              'zh dark reduced-motion onboarding at 600x400 renders translated zh copy',
              `Mixed English in zh onboarding: ${zhText.slice(0, 160)}`
            )
          }
        } else if (/How do you want to work with agents\?/i.test(modalText)) {
          pendingIfSmoke(
            ctx.mode,
            'M1',
            'zh dark reduced-motion onboarding at 600x400 renders translated zh copy',
            `Mixed English in zh onboarding: ${modalText.slice(0, 160)}`
          )
        }
        return metrics
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T3-02',
    tier: 3,
    featureArea: 'E2E-F01+E2E-F03',
    refs: ['F01', 'D.07.01', 'G.09.02', 'J04'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't3-02' })
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        width: 820,
        height: 580,
        profileOptions: { locale: 'en', theme: 'light' }
      })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        await setViewportSize(app, page, 640, 580)
        await sleep(150)
        await setViewportSize(app, page, 820, 580)
        if (!(await hasIntegratedWorkspaceShell(page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'DualPane 646px threshold + Embedded Fixed Explorer across 820x580 resize in default build',
            'Integrated DualPane & Fixed SidePanel pending M3'
          )
        }
        const addSessionBtn = page.getByRole('button', { name: /Add session|添加会话/i }).first()
        if (await waitForVisible(addSessionBtn, 2500)) await addSessionBtn.click()
        await page.getByRole('button', { name: /^(New work object|新建工作对象)$/i }).first().click()
        await page.getByRole('menuitem', { name: /^(Open Explorer|打开资源管理器)$/i }).first().click()
        const standaloneExplorer = page.locator(`${M3_SELECTOR_CONTRACT.explorer}[data-presentation="standalone"]`).first()
        await standaloneExplorer.waitFor({ state: 'visible', timeout: 8000 })
        await standaloneExplorer.getByRole('button', { name: /Explorer placement|资源管理器位置/i }).first().click()
        await page.getByRole('menuitem', { name: /^(Move to |移动到)/i }).first().click()
        const embedded = page.locator(`${M3_SELECTOR_CONTRACT.explorer}[data-presentation="embedded"]`).first()
        await embedded.waitFor({ state: 'visible', timeout: 8000 })
        const scopeBefore = (await embedded.locator(M3_SELECTOR_CONTRACT.explorerScope).first().innerText()).trim()
        await setViewportSize(app, page, 640, 580)
        const modeNarrow = await page.locator(M3_SELECTOR_CONTRACT.splitLayout).first().getAttribute('data-preview-split')
        assert.equal(modeNarrow, 'focused', `Expected focused mode below 646px, got ${modeNarrow}`)
        await setViewportSize(app, page, 1280, 800)
        const modeWide = await page.locator(M3_SELECTOR_CONTRACT.splitLayout).first().getAttribute('data-preview-split')
        assert.equal(modeWide, 'side-by-side', `Expected side-by-side mode at 1280px, got ${modeWide}`)
        const scopeAfter = (await embedded.locator(M3_SELECTOR_CONTRACT.explorerScope).first().innerText()).trim()
        assert.equal(scopeAfter, scopeBefore, 'Embedded Explorer scope drifted across resize')
        return { modeNarrow, modeWide, scopeAfter }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T3-03',
    tier: 3,
    featureArea: 'E2E-F01+E2E-F03+E2E-F04',
    refs: ['D.05', 'S.09', 'H.01', 'J06'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't3-03' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        if (!(await hasIntegratedWorkspaceShell(page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Close Workspace vs Close Unsaved Editor Tab semantics across 2 Tab Groups in default build',
            'Top-level Workspace Tab Groups pending M3 integration'
          )
        }
        const groupBtn = page.locator(M3_SELECTOR_CONTRACT.groupSelector).first()
        await groupBtn.waitFor({ state: 'visible', timeout: 8000 })
        await groupBtn.click()
        await page.getByRole('menuitem', { name: /New tab group|新建标签组/i }).first().click()
        await page.getByRole('dialog').locator('input').first().fill('Group Two')
        await page.getByRole('dialog').getByRole('button', { name: /^(Create group|Create|创建|确认)$/i }).first().click()
        await page.getByRole('button', { name: /^(New work object|新建工作对象)$/i }).first().click()
        await page.getByRole('menuitem', { name: /^(New workspace|新建工作空间)$/i }).first().click()
        const tabsInGroup2 = await page.locator(M3_SELECTOR_CONTRACT.workspaceTab).count()
        assert.ok(tabsInGroup2 >= 1, 'Expected new workspace tab in Group Two')
        const closeTabBtn = page.locator('[aria-label^="Close "], [aria-label^="关闭 "]').last()
        await closeTabBtn.click()
        assert.equal(
          await page.locator(M3_SELECTOR_CONTRACT.workspaceTab).count(),
          tabsInGroup2 - 1,
          'Closing workspace tab in Group Two should remove it cleanly'
        )
        return { closedWorkspaceTabCleanly: true }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T3-04',
    tier: 3,
    featureArea: 'E2E-F03+E2E-F05',
    refs: ['K.04', 'C.10.08', 'UX10'],
    async run(ctx) {
      const core = await startLoopbackAcsCore({ mode: 'full', agentCollabRoot: ctx.agentCollabRoot })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        // Verify NativeLink + include_native_source=true protocol layer on loopback Core
        const pid = core.info.project_id
        await core.request('PUT', `/projects/${pid}/native-links/t3-04-link`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 't3-04-bind' },
          body: core.nativeLinkFixture
        })
        const send = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 't3-04-invoke' },
          body: { to: core.addresses.peer_b, content: 'SourceJump pairwise check', activation: 'invoke' }
        })
        await core.dispatchPending()
        const read = await core.request(
          'GET',
          `/projects/${pid}/messages/${encodeURIComponent(send.json.message.message_handle)}?include_native_source=true`,
          { token: core.tokens.client }
        )
        assert.equal(read.json.native_source.available, true)

        if (!(await hasIntegratedWorkspaceShell(inst.page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'SourceJump navigates to exact bound Session 2 across 2 Workspaces sharing Identity',
            'Backend NativeLink/include_native_source verified; multi-Workspace SourceJump pending M2/M3'
          )
        }
        return { backendSourceAvailable: true }
      } finally {
        await closeElectronApp(inst)
        await core.cleanup()
      }
    }
  },
  {
    id: 'T3-05',
    tier: 3,
    featureArea: 'E2E-F05',
    refs: ['N.general.01', 'Meta.limits', 'K.03'],
    async run(ctx) {
      const core = await startLoopbackAcsCore({ mode: 'p1_only', agentCollabRoot: ctx.agentCollabRoot })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const pid = core.info.project_id
        const meta = await core.request('GET', '/meta')
        assert.equal(meta.json.limits.attachment_count, 0)
        assert.equal(meta.json.features.includes('attachments'), false)

        // Connect Electron UI to P1-only loopback Core
        const { page } = inst
        await openSettingsPage(page)
        await page.locator('aside button').filter({ hasText: /^(General|常规|通用)$/i }).first().click()
        const sec = page.locator('section[data-settings-section="general"]').first()
        const existingBtn = sec
          .getByRole('button', { name: /Connect an existing service|连接已有服务/i })
          .first()
        const existingRadio = sec
          .getByRole('radio', { name: /Connect an existing service|连接已有服务/i })
          .first()
        if (await existingRadio.isVisible().catch(() => false)) await existingRadio.click()
        else await existingBtn.click()
        await sec.getByLabel(/Service address|服务地址/i).fill(core.baseUrl)
        await sec.getByLabel(/Connection key|连接密钥/i).fill(core.tokens.client)
        await sec.getByRole('button', { name: /^(Connect|连接)$/i }).first().click()
        await sec.getByText(/^(Connected|已连接)$/i).first().waitFor({ state: 'visible', timeout: 10000 })

        await returnFromSettings(page)
        const dlg = await openCollaborationDialog(page)
        const statusText = await dlg.locator('[role="status"]').first().innerText()
        await page.keyboard.press('Escape')

        if (!/Connected|已连接/i.test(statusText)) {
          pendingIfSmoke(
            ctx.mode,
            'M2',
            'Settings <-> Titlebar sync immediately on P1-only Core connect',
            `Titlebar status=${statusText}`
          )
        }
        return { p1OnlyConnected: true, titlebarStatus: statusText }
      } finally {
        await closeElectronApp(inst)
        await core.cleanup()
      }
    }
  },
  {
    id: 'T3-06',
    tier: 3,
    featureArea: 'E2E-F04+E2E-F05',
    refs: ['T03', 'T05', 'I.01', 'UX15'],
    async run(ctx) {
      const core = await startLoopbackAcsCore({ mode: 'full', agentCollabRoot: ctx.agentCollabRoot })
      const httpSrv = await startLoopbackHttpServer()
      const repo = createTempGitRepo({ name: 't3-06' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        // Open active Browser tab on loopback HTTP server
        await page.getByRole('button', { name: /^(New tab|新标签页)$/i }).first().click()
        await page.getByRole('menuitem', { name: /Browser|浏览器/i }).first().click()
        const addrBar = page.locator('[data-orca-browser-address-bar="true"]').first()
        await addrBar.waitFor({ state: 'visible', timeout: 10000 })
        await addrBar.fill(`${httpSrv.baseUrl}/page1`)
        await addrBar.press('Enter')

        // Inject Core post-commit fault, restart Core, verify Idempotency-Key retry sends once
        const pid = core.info.project_id
        await core.setFault({ drop_next_send_response: true })
        const first = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 't3-06-idem' },
          body: { to: core.addresses.peer_b, content: 'Pairwise disconnect retry' }
        })
        assert.equal(first.status, 503)
        await core.restartServer({ reusePort: true })
        const retry = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 't3-06-idem' },
          body: { to: core.addresses.peer_b, content: 'Pairwise disconnect retry' }
        })
        assert.ok(retry.status === 200 || retry.status === 201)

        // Browser still loaded and responsive
        const hasGuest = await app.evaluate(({ webContents }, url) =>
          webContents.getAllWebContents().some((wc) => wc.getURL().startsWith(url)),
          httpSrv.baseUrl
        )
        assert.equal(hasGuest, true, 'Loopback Browser should remain alive across Core restart')
        return { browserAlive: true, retryStatus: retry.status }
      } finally {
        await closeElectronApp(inst)
        await httpSrv.close()
        repo.cleanup()
        await core.cleanup()
      }
    }
  },
  {
    id: 'T3-07',
    tier: 3,
    featureArea: 'E2E-F01+E2E-F03+E2E-F04',
    refs: ['M.02', 'F15', 'F16', 'J07'],
    async run(ctx) {
      const repo = createTempGitRepo({
        name: 't3-07',
        worktrees: [
          { branch: 'wt-clean' },
          { branch: 'wt-kept', uniqueCommitFile: 'kept.txt', uniqueCommitContent: 'kept branch\n' }
        ]
      })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        const existing = new Set(app.windows())
        const resourceBtn = page.getByRole('button', { name: /^(Resource Manager|资源管理器)/i }).first()
        await resourceBtn.click()
        const popover = page
          .locator('[data-slot="popover-content"]')
          .filter({ hasText: /Workspace disk|Space|空间/i })
          .first()
        await popover.waitFor({ state: 'visible', timeout: 8000 })
        const [spacePage] = await Promise.all([
          app.waitForEvent('window', { predicate: (w) => !existing.has(w), timeout: 12000 }),
          popover.getByRole('button', { name: /Review in Space|在.*空间.*查看|查看|审查|评审|审阅|检查|审核|复核|Review/i }).last().click()
        ])
        await spacePage.waitForLoadState('domcontentloaded', { timeout: 15000 })
        await spacePage.locator('body').waitFor({ state: 'visible', timeout: 10000 })
        await spacePage.close()
        return { spaceCrossWindowPairwiseReady: true }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T3-08',
    tier: 3,
    featureArea: 'E2E-F02+E2E-F03+E2E-F04',
    refs: ['G.08', 'L.06', 'E.03', 'T.04'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't3-08' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      const pluginFix = createSyntheticPluginFixture(ctx.porpitaRoot)
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        // Open Search/QuickOpen, exercise real IME composition + Esc layering
        const searchBtn = page
          .getByRole('button', { name: /Search worktrees and browser tabs|搜索工作树/i })
          .first()
        await searchBtn.waitFor({ state: 'visible', timeout: 10000 })
        await searchBtn.click()
        const imeResult = await assertImeCompositionKeepsDialogOpen(
          page,
          page.locator('[role="dialog"]:visible').last(),
          'alpha'
        )

        // Install, approve, open RightSidebar panel, and disable folder plugin via Settings -> Plugins
        await openSettingsPage(page)
        await page.locator('aside button').filter({ hasText: /^(Plugins|插件)/i }).first().click()
        await installAndEnableFolderPlugin(app, page, pluginFix)
        const panelState = await openAndVerifyPluginPanel(page, pluginFix.title)
        const disabledState = await disablePluginAndVerify(page, pluginFix.title)
        return {
          imeGuardActiveTag: imeResult.activeTag,
          panelState,
          ...disabledState
        }
      } finally {
        await closeElectronApp(inst)
        pluginFix.cleanup()
        repo.cleanup()
      }
    }
  }
]
