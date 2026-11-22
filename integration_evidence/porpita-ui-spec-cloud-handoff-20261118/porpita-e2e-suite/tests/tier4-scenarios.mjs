import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import {
  activateWorkspaceTab,
  addLocalFolderProject,
  addSessionToActiveWorkspace,
  assertAllWindowsHidden,
  assertNotificationStackNonBlocking,
  closeCollaborationDialogWithFocusCheck,
  closeElectronApp,
  connectCollaborationViaSettings,
  createIsolatedProfileDirs,
  disablePluginAndVerify,
  disconnectCollaborationViaSettings,
  dismissNotificationCards,
  ensureDualPaneWorkspace,
  hasIntegratedWorkspaceShell,
  installAndEnableFolderPlugin,
  isCollaborationConnectedText,
  launchElectronApp,
  M3_SELECTOR_CONTRACT,
  openAndVerifyPluginPanel,
  openCodexChatViaVault,
  openCollaborationDialog,
  openMarkdownPreviewAndVerify,
  openSettingsPage,
  primaryModifierKey,
  quitElectronGracefully,
  reconnectCollaborationViaSettings,
  returnFromSettings,
  selectCollaborationContact,
  selectWorktreeById,
  setViewportSize,
  sleep,
  stubOpenDialog,
  waitForVisible
} from '../lib/electron-harness.mjs'
import { startLoopbackAcsCore } from '../lib/acs-core-harness.mjs'
import {
  createCodexHistoryFixture,
  createSyntheticPluginFixture,
  createSyntheticSkillFixture,
  createTempGitRepo,
  createTempPlainFolder,
  startLoopbackHttpServer,
  verifyGitBaselines
} from '../lib/fixtures.mjs'
import {
  checkApiScopeParity,
  checkEnvBoundedHonesty,
  checkMarkdownLinks,
  checkOrcaFirstCrosswalk,
  checkReferenceCrosswalk,
  runDesignEvidenceCheck,
  runStagedBuildCoverage
} from '../lib/spec-audit-harness.mjs'
import { ENV_BOUNDED_ITEMS, pendingIfSmoke } from '../lib/test-context.mjs'

export const TIER4_TESTS = [
  {
    id: 'T4-01',
    tier: 4,
    featureArea: 'E2E-F01+E2E-F02+E2E-F04',
    refs: ['J01', 'J02', 'J13', 'UX01*', 'UX18', 'UX19'],
    timeoutMs: 360_000,
    async run(ctx) {
      const plain = createTempPlainFolder({ name: 't4-01-plain' })
      const repo = createTempGitRepo({ name: 't4-01-repo' })
      let inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        seedCompletedOnboarding: false,
        extraEnv: { LANG: 'zh_CN.UTF-8' }
      })
      const tempRoot = inst.tempRoot
      try {
        const { page } = inst
        const modal = page.locator('[role="dialog"][data-onboarding-modal]').first()
        await modal.waitFor({ state: 'visible', timeout: 15000 })
        const zhBtn = modal.getByRole('button', { name: /简体中文|中文/i }).first()
        if (await zhBtn.isVisible().catch(() => false)) await zhBtn.click()
        const onboardingText = await modal.innerText()

        // Skip / finish onboarding
        await modal.getByRole('button', { name: /Set up later|稍后设置/i }).first().click()
        const confirmSkip = page.getByRole('dialog').getByRole('button', { name: /^(Skip|跳过)$/i }).first()
        if (await waitForVisible(confirmSkip, 3000)) {
          await confirmSkip.click()
        }
        await modal.waitFor({ state: 'hidden', timeout: 10000 })

        // Relaunch same profile -> onboarding must NOT repeat
        await quitElectronGracefully(inst)
        inst = await launchElectronApp({
          porpitaRoot: ctx.porpitaRoot,
          tempRoot,
          seedCompletedOnboarding: false,
          profileOptions: { locale: 'zh', settings: { showArtifactsButton: true } }
        })
        await sleep(800)
        assert.equal(
          await inst.page.locator('[role="dialog"][data-onboarding-modal]:visible').count(),
          0,
          'Onboarding repeated after restart'
        )

        // Add plain non-Git folder + Git repo
        await addLocalFolderProject(inst.app, inst.page, plain.folderPath)
        await addLocalFolderProject(inst.app, inst.page, repo.repoPath)

        // Check mobile naming, narrow 600x400 usability, and non-blocking notice/setup cards
        const navLoc = inst.page.locator('[data-contextual-tour-target="sidebar-navigation"]').first()
        const sidebarText = (await waitForVisible(navLoc, 2000))
          ? await navLoc.innerText()
          : await inst.page.locator('body').innerText()
        await setViewportSize(inst.app, inst.page, 600, 400)
        const narrowOverflow = await inst.page.evaluate(
          () => document.documentElement.scrollWidth > window.innerWidth + 2
        )
        assert.equal(narrowOverflow, false, 'Narrow 600x400 horizontal overflow detected')
        const attachedStackProbe = await assertNotificationStackNonBlocking(inst.page, {
          requireActiveCard: false,
          contextLabel: 'T4-01 attached 600x400'
        })

        // O.01.01 non-vacuous probe: launch isolated profile with active NotificationCardStack card at 600x400
        await closeElectronApp(inst, { removeTempDir: true })
        inst = null
        const stackInst = await launchElectronApp({
          porpitaRoot: ctx.porpitaRoot,
          width: 600,
          height: 400,
          profileOptions: {
            settings: { agentDefaultSurface: 'terminal' },
            ui: {
              featureTipsSeenIds: [],
              featureInteractions: {},
              contextualToursAutoEligible: false,
              browserImportHintHidden: true,
              codexTerminalServerIsolationNoticeSeen: true
            },
            extra: {
              chatUiLaunchTipAudience: { version: 1, membership: 'eligible', basis: 'chat-ui-off' }
            }
          }
        })
        try {
          const stackCard = stackInst.page.locator('[data-notification-card-stack] > *').first()
          await stackCard.waitFor({ state: 'visible', timeout: 8000 })
          const activeCardProbe = await assertNotificationStackNonBlocking(stackInst.page, {
            requireActiveCard: true,
            contextLabel: 'T4-01 O.01.01 active card 600x400'
          })
          // Click Add project directly without dismissing the card stack -> AddRepoDialog must open cleanly
          const addProjectBtn = stackInst.page
            .getByRole('button', { name: /^(Add project|添加项目)$/i })
            .last()
          await addProjectBtn.waitFor({ state: 'visible', timeout: 8000 })
          await addProjectBtn.click()
          await stackInst.page
            .getByRole('button', { name: /Browse folder|浏览文件夹/i })
            .first()
            .waitFor({ state: 'visible', timeout: 8000 })
          await stackInst.page.keyboard.press('Escape')

          if (/How do you want to work with agents\?/i.test(onboardingText)) {
            pendingIfSmoke(
              ctx.mode,
              'M1',
              'zh onboarding translated & sidebar uses "Porpita Mobile"',
              `Mixed English onboarding observed; sidebarHasOrcaMobile=${/Orca Mobile/i.test(sidebarText)}`
            )
          }
          if (/Orca Mobile/i.test(sidebarText)) {
            pendingIfSmoke(ctx.mode, 'M1', 'Sidebar uses "Porpita Mobile"', sidebarText)
          }
          return {
            onboardingNonRepeat: true,
            narrowOverflow,
            attachedCardsCount: attachedStackProbe.activeCardsCount,
            o01ActiveCardsCount: activeCardProbe.activeCardsCount
          }
        } finally {
          await closeElectronApp(stackInst, { removeTempDir: true })
        }
      } finally {
        if (inst) await closeElectronApp(inst, { removeTempDir: true })
        plain.cleanup()
        repo.cleanup()
      }
    }
  },
  {
    id: 'T4-02',
    tier: 4,
    featureArea: 'E2E-F01+E2E-F03',
    refs: ['J03', 'J04', 'J06', 'J07', 'UI_SPEC_BRIEF:E', 'UX02', 'UX15'],
    async run(ctx) {
      const repoA = createTempGitRepo({
        name: 't4-02-repo-a',
        files: { 'repo-a-only.txt': 'Repo A unique file\n', 'shared.md': '# Repo A\n' }
      })
      const repoB = createTempGitRepo({
        name: 't4-02-repo-b',
        files: { 'repo-b-only.txt': 'Repo B unique file\n', 'shared.md': '# Repo B\n' }
      })
      const dirs = createIsolatedProfileDirs()
      createCodexHistoryFixture({
        homeDir: dirs.homeDir,
        repoPath: repoA.repoPath,
        id: '019f1000-1111-7222-8333-4444444444a1',
        prompt: 'Session Alpha checklist',
        reply: 'Alpha session transcript ready.',
        clock: '06'
      })
      createCodexHistoryFixture({
        homeDir: dirs.homeDir,
        repoPath: repoB.repoPath,
        id: '019f1000-1111-7222-8333-4444444444b2',
        prompt: 'Session Beta build',
        reply: 'Beta session transcript ready.',
        clock: '07'
      })
      let inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot, tempRoot: dirs.tempRoot })
      const tempRoot = inst.tempRoot
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repoA.repoPath)
        const repoAId = await page.evaluate(
          () => document.querySelector('[data-worktree-sidebar-layout] [role="option"][data-worktree-id][aria-current="page"]')?.getAttribute('data-worktree-id') || null
        )
        assert.ok(repoAId, 'Failed to resolve active worktree ID for repoA')
        await addLocalFolderProject(app, page, repoB.repoPath)
        const repoBId = await page.evaluate(
          () => document.querySelector('[data-worktree-sidebar-layout] [role="option"][data-worktree-id][aria-current="page"]')?.getAttribute('data-worktree-id') || null
        )
        assert.ok(repoBId && repoBId !== repoAId, 'Failed to resolve distinct active worktree ID for repoB')
        if (!(await hasIntegratedWorkspaceShell(page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'UI_SPEC_BRIEF §E 10-step Multi-Session Cross-Repo Workspace & SidePanel Continuity in default build',
            'Integrated Workspace Tab Groups, Session Index, Split Panes & Pinned SidePanel pending M3'
          )
        }

        // Open real Session A (repoA) and Session B (repoB) via Vault -> combine in Dual-Pane Workspace 1
        const closeRightInit = page.locator('[data-workspace-sidebar-toggle="right"][aria-expanded="true"]').first()
        if (await waitForVisible(closeRightInit, 800)) {
          await closeRightInit.click()
        }
        await selectWorktreeById(page, repoAId)
        await openCodexChatViaVault(page, { searchQuery: 'Session Alpha', expectedReply: 'Alpha session transcript ready.' })
        await selectWorktreeById(page, repoBId)
        await openCodexChatViaVault(page, { searchQuery: 'Session Beta', expectBackgroundTabText: 'Session Beta' })
        const closeRightAfterVault = page.locator('[data-workspace-sidebar-toggle="right"][aria-expanded="true"]').first()
        if (await waitForVisible(closeRightAfterVault, 800)) {
          await closeRightAfterVault.click()
        }

        await activateWorkspaceTab(page, 0)
        const panes = page.locator('[data-workspace-preview-session]')
        if ((await panes.count()) < 2) {
          await addSessionToActiveWorkspace(page, { pickExistingText: 'Session Beta' })
        }
        await page.waitForFunction(
          () =>
            document.querySelector('[data-workspace-preview-chat-layout]')?.getAttribute('data-preview-split') === 'side-by-side' &&
            document.querySelectorAll('[data-workspace-preview-session]').length === 2,
          null,
          { timeout: 10000 }
        )

        const paneA = panes.nth(0)
        const paneB = panes.nth(1)
        await paneA.getByText('Alpha session transcript ready.', { exact: false }).first().waitFor({ state: 'visible', timeout: 10000 })
        await paneB.getByText('Beta session transcript ready.', { exact: false }).first().waitFor({ state: 'visible', timeout: 10000 })
        await dismissNotificationCards(page)
        const compA = paneA.locator('[data-native-chat-composer-scope] [contenteditable="true"]').first()
        const compB = paneB.locator('[data-native-chat-composer-scope] [contenteditable="true"]').first()
        await compA.click()
        await page.keyboard.type('Scenario E Draft A')
        await compB.click()
        await page.keyboard.type('Scenario E Draft B')

        // Keyboard split resize 50 -> 55, narrow collapse + Switch pane, wide restore
        const sep = page.getByRole('separator').first()
        await sep.focus()
        await page.keyboard.press('ArrowRight')
        await page.waitForFunction(
          () => document.querySelector('[role="separator"]')?.getAttribute('aria-valuenow') === '55',
          null,
          { timeout: 5000 }
        )
        const leftToggle = page.locator('[data-workspace-sidebar-toggle="left"]').first()
        const leftWasOpen = (await waitForVisible(leftToggle, 1000)) && (await leftToggle.getAttribute('aria-expanded')) === 'true'
        if (leftWasOpen) await leftToggle.click()
        await setViewportSize(app, page, 630, 560)
        await page.waitForFunction(
          () => document.querySelector('[data-workspace-preview-chat-layout]')?.getAttribute('data-preview-split') === 'focused',
          null,
          { timeout: 6000 }
        )
        await setViewportSize(app, page, 1280, 800)
        await page.waitForFunction(
          () => document.querySelector('[data-workspace-preview-chat-layout]')?.getAttribute('data-preview-split') === 'side-by-side',
          null,
          { timeout: 6000 }
        )
        if (leftWasOpen) await leftToggle.click()

        // Create second Tab Group + Workspace 2, then return to General Workspace 1
        const groupBtn = page.locator(M3_SELECTOR_CONTRACT.groupSelector).first()
        await groupBtn.click()
        await page.getByRole('menuitem', { name: /New tab group|新建标签组/i }).first().click()
        await page.getByRole('dialog').locator('input').first().fill('Group Two')
        await page
          .getByRole('dialog')
          .getByRole('button', { name: /^(Create group|Create|创建分组|创建|确认)$/i })
          .first()
          .click()
        await page.getByRole('button', { name: /^(New work object|新建工作对象)$/i }).first().click()
        await page.getByRole('menuitem', { name: /^(New workspace|新建工作空间)$/i }).first().click()
        await groupBtn.click()
        await page.getByRole('menuitemradio', { name: /^(General|常规|通用)$/i }).first().click()
        await activateWorkspaceTab(page, 0)

        // Open Standalone Explorer pinned to repoA -> embed in Workspace 1 -> focus Session B -> detach -> open shared.md
        await page.getByRole('button', { name: /^(New work object|新建工作对象)$/i }).first().click()
        await page.getByRole('menuitem', { name: /^(Open Explorer|打开资源管理器)$/i }).first().click()
        const folderPicker = page.getByRole('dialog').filter({ hasText: /Choose a folder for Explorer|选择资源管理器的目录/i }).first()
        await folderPicker.waitFor({ state: 'visible', timeout: 6000 })
        await folderPicker.getByRole('option').filter({ hasText: path.basename(repoA.repoPath) }).first().click()

        const standaloneExplorer = page.locator(`${M3_SELECTOR_CONTRACT.explorer}[data-presentation="standalone"]`).first()
        await standaloneExplorer.waitFor({ state: 'visible', timeout: 8000 })
        await standaloneExplorer.getByText('repo-a-only.txt', { exact: false }).first().waitFor({ state: 'visible', timeout: 8000 })
        const pinnedScope = (await standaloneExplorer.locator(M3_SELECTOR_CONTRACT.explorerScope).first().innerText()).trim()

        await standaloneExplorer.getByRole('button', { name: /Explorer placement|资源管理器位置/i }).first().click()
        await page.getByRole('menuitem', { name: /^(Move to |移至 |移动到)/i }).first().click()
        const embedded = page.locator(`${M3_SELECTOR_CONTRACT.explorer}[data-presentation="embedded"]`).first()
        await embedded.waitFor({ state: 'visible', timeout: 8000 })
        assert.equal((await embedded.locator(M3_SELECTOR_CONTRACT.explorerScope).first().innerText()).trim(), pinnedScope)

        await compB.click()
        assert.equal(await embedded.getByText('repo-a-only.txt').count() > 0, true)
        assert.equal(await embedded.getByText('repo-b-only.txt').count(), 0)

        await embedded.getByRole('button', { name: /Explorer placement|资源管理器位置/i }).first().click()
        await page.getByRole('menuitem', { name: /Open as a tab|作为标签打开/i }).first().click()
        await standaloneExplorer.waitFor({ state: 'visible', timeout: 8000 })
        await standaloneExplorer.getByRole('option', { name: 'shared.md' }).first().dblclick()
        const editorView = page.locator('.tiptap, .ProseMirror, .monaco-editor .view-lines').first()
        await editorView.waitFor({ state: 'visible', timeout: 10000 })
        await editorView.getByText('Repo A', { exact: true }).first().waitFor({ state: 'visible', timeout: 10000 })
        assert.equal(await editorView.getByText('Repo B').count(), 0)

        // Return to Workspace 1 -> Clean quit -> Verify v3 persistence & cold relaunch
        await activateWorkspaceTab(page, 0)
        const tabCountBefore = await page.locator(M3_SELECTOR_CONTRACT.workspaceTab).count()
        const exitCode = await quitElectronGracefully(inst)
        assert.equal(exitCode, 0)

        const layoutPath = path.join(inst.userDataDir, 'porpita-workspaces.json')
        const savedLayout = JSON.parse(readFileSync(layoutPath, 'utf8'))
        assert.equal(savedLayout.version, 3, `Expected strict version 3 layout, got ${savedLayout.version}`)

        inst = await launchElectronApp({
          porpitaRoot: ctx.porpitaRoot,
          tempRoot,
          seedCompletedOnboarding: false
        })
        await inst.page.locator(M3_SELECTOR_CONTRACT.workspaceTab).first().waitFor({ state: 'visible', timeout: 15000 })
        await activateWorkspaceTab(inst.page, 0)
        await inst.page.waitForFunction(
          () => document.querySelector('[role="separator"]')?.getAttribute('aria-valuenow') === '55',
          null,
          { timeout: 10000 }
        )
        const tabCountAfter = await inst.page.locator(M3_SELECTOR_CONTRACT.workspaceTab).count()
        assert.ok(tabCountAfter >= tabCountBefore, `Expected >=${tabCountBefore} tabs after relaunch, got ${tabCountAfter}`)
        return { pinnedScope, tabCountBefore, tabCountAfter, splitRatioRestored: 55 }
      } finally {
        await closeElectronApp(inst, { removeTempDir: true })
        repoA.cleanup()
        repoB.cleanup()
      }
    }
  },
  {
    id: 'T4-03',
    tier: 4,
    featureArea: 'E2E-F03+E2E-F04',
    refs: ['J05*', 'J08', 'J10', 'J11', 'UX02', 'UX19'],
    async run(ctx) {
      const httpSrv = await startLoopbackHttpServer()
      const repo = createTempGitRepo({
        name: 't4-03-dev',
        dirtyFiles: { 'notes.md': '# Edited Release Notes\n\nModified for Source Control Diff.\n' }
      })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      const pluginFix = createSyntheticPluginFixture(ctx.porpitaRoot)
      try {
        const { app, page, homeDir } = inst
        createCodexHistoryFixture({ homeDir, repoPath: repo.repoPath })
        createSyntheticSkillFixture(homeDir, 't4-03-skill')
        await addLocalFolderProject(app, page, repo.repoPath)

        // 1. Open sample.csv, sample.svg, and notes.md Preview -> assert real viewers + no script execution
        const csvItem = page.getByText('sample.csv', { exact: true }).first()
        await csvItem.waitFor({ state: 'visible', timeout: 8000 })
        await csvItem.dblclick()
        await page.locator('[data-testid="csv-grid"]').first().waitFor({ state: 'visible', timeout: 10000 })

        const svgItem = page.getByText('sample.svg', { exact: true }).first()
        await svgItem.waitFor({ state: 'visible', timeout: 8000 })
        await svgItem.dblclick()
        const svgImg = page.locator('img[alt="sample.svg"]').first()
        await svgImg.waitFor({ state: 'visible', timeout: 10000 })
        assert.equal(
          await svgImg.evaluate((el) => el.complete && el.naturalWidth > 0),
          true,
          'sample.svg did not render cleanly'
        )

        const notesItem = page.getByText('notes.md', { exact: true }).first()
        await notesItem.waitFor({ state: 'visible', timeout: 8000 })
        await notesItem.dblclick()
        await openMarkdownPreviewAndVerify(page, 'Edited Release Notes')

        // 2. Source Control -> Diff
        const scBtn = page.getByRole('button', { name: /^(Source Control|源代码管理|源代码控制)/i }).first()
        await scBtn.click()
        await page.getByText('notes.md', { exact: true }).last().click()
        await page.locator('.monaco-diff-editor').first().waitFor({ state: 'visible', timeout: 10000 })

        // 3. Loopback HTTP Browser
        await page.getByRole('button', { name: /^(New tab|新标签页)$/i }).first().click()
        await page.getByRole('menuitem', { name: /Browser|浏览器/i }).first().click()
        const addrBar = page.locator('[data-orca-browser-address-bar="true"]').first()
        await addrBar.waitFor({ state: 'visible', timeout: 10000 })
        await addrBar.fill(`${httpSrv.baseUrl}/page2`)
        await addrBar.press('Enter')
        const guestDeadline = Date.now() + 8000
        let hasGuest = false
        while (Date.now() < guestDeadline) {
          hasGuest = await app.evaluate(({ webContents }, url) =>
            webContents.getAllWebContents().some((wc) => wc.getURL().startsWith(url)),
            httpSrv.baseUrl
          )
          if (hasGuest) break
          await sleep(200)
        }
        assert.equal(hasGuest, true, 'Loopback HTTP Browser failed to load /page2')

        // 4. Synthetic Plugin install, approve, RightSidebar panel load, and disable lifecycle
        await openSettingsPage(page)
        await page.locator('aside button').filter({ hasText: /^(Plugins|插件)/i }).first().click()
        await installAndEnableFolderPlugin(app, page, pluginFix)
        const panelState = await openAndVerifyPluginPanel(page, pluginFix.title)
        const disabledState = await disablePluginAndVerify(page, pluginFix.title)

        return {
          diffVerified: true,
          browserVerified: true,
          pluginPanelLoaded: Boolean(panelState.present),
          ...disabledState,
          gitHead: repo.getHead()
        }
      } finally {
        await closeElectronApp(inst)
        await httpSrv.close()
        pluginFix.cleanup()
        repo.cleanup()
      }
    }
  },
  {
    id: 'T4-04',
    tier: 4,
    featureArea: 'E2E-F05',
    refs: ['J09*', 'J12', 'T01-T07*', 'UX06', 'UX09-UX17'],
    async run(ctx) {
      const core = await startLoopbackAcsCore({ mode: 'full', agentCollabRoot: ctx.agentCollabRoot })
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        profileOptions: { locale: 'zh' }
      })
      try {
        const pid = core.info.project_id
        // 1. Connect Electron Settings -> Collaboration to loopback Core, verify zh copy & Disconnect/Reconnect sync
        const { app, page } = inst
        const dlgInitial = await openCollaborationDialog(page)
        const initialSelectText = (await dlgInitial.locator('select').first().innerText()).trim()
        assert.equal(/尚未连接工作区/.test(initialSelectText), false, `Found stale 尚未连接工作区 in zh dropdown: ${initialSelectText}`)
        assert.match(initialSelectText, /尚未连接协作项目/, `Expected 尚未连接协作项目, got: ${initialSelectText}`)
        await closeCollaborationDialogWithFocusCheck(page, dlgInitial)

        await connectCollaborationViaSettings(page, core)
        await returnFromSettings(page)

        const dlg = await openCollaborationDialog(page)
        const titleStatus = (await dlg.locator('[role="status"]').first().innerText()).trim()
        assert.equal(
          isCollaborationConnectedText(titleStatus),
          true,
          `Settings <-> Titlebar must sync immediately in T4-04, got: ${titleStatus}`
        )
        await closeCollaborationDialogWithFocusCheck(page, dlg)

        await disconnectCollaborationViaSettings(page)
        await reconnectCollaborationViaSettings(page)
        await returnFromSettings(page)
        const dlgReconnected = await openCollaborationDialog(page)
        const reconnectedStatus = (await dlgReconnected.locator('[role="status"]').first().innerText()).trim()
        assert.equal(isCollaborationConnectedText(reconnectedStatus), true, `Reconnect did not sync Titlebar: ${reconnectedStatus}`)
        await closeCollaborationDialogWithFocusCheck(page, dlgReconnected)

        // 2. Full /api/communication/v1 protocol episode:
        // Draft rev0->rev1, 2 out-of-order questions + replies (T01), Attachment SHA-256,
        // NativeLink + include_native_source=true, post-commit drop + retry (T05), revoke (T07)
        const conv = await core.request(
          'GET',
          `/projects/${pid}/conversations/resolve?with=${encodeURIComponent(core.addresses.peer_b)}`,
          { token: core.tokens.client }
        )
        const cid = conv.json.conversation_id
        const d0 = await core.request('GET', `/projects/${pid}/conversations/${cid}/draft`, {
          token: core.tokens.client
        })
        assert.equal(d0.json.revision, 0)
        assert.equal(d0.json.updated_at, null)

        const d1 = await core.request('PUT', `/projects/${pid}/conversations/${cid}/draft`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 't4-04-draft-1', 'If-Match': '"0"' },
          body: { content: 'T4-04 scenario draft', attachment_refs: [] }
        })
        assert.equal(d1.json.revision, 1)

        // Upload & send attachment
        const attBytes = Buffer.from('T4-04 attachment bytes\n', 'utf8')
        const attSha = createHash('sha256').update(attBytes).digest('hex')
        const resv = await core.request('POST', `/projects/${pid}/attachments`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 't4-04-att-resv' },
          body: { name: 'episode.txt', media_type: 'text/plain', bytes: attBytes.length, sha256: attSha }
        })
        const attId = resv.json.attachment_id
        await core.request('PUT', `/projects/${pid}/attachments/${attId}/content`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 't4-04-att-put', 'Content-Type': 'application/octet-stream' },
          rawBody: attBytes
        })
        const fin = await core.request('POST', `/projects/${pid}/attachments/${attId}/finalize`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 't4-04-att-fin' },
          body: { sha256: attSha, bytes: attBytes.length }
        })
        assert.equal(fin.status, 200, fin.text)

        // Two questions + out-of-order reply_to (T01)
        const q1 = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 't4-04-q1' },
          body: { to: core.addresses.peer_b, content: 'Question 1', activation: 'invoke' }
        })
        assert.equal(q1.status, 201, q1.text)
        const q2 = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 't4-04-q2' },
          body: { to: core.addresses.peer_b, content: 'Question 2', activation: 'message_only', attachment_refs: [attId] }
        })
        assert.equal(q2.status, 201, q2.text)
        await core.dispatchPending()
        await core.peerSend({
          actor: 'peer_b',
          to: core.addresses.client,
          content: 'Answer to Q2 first',
          reply_to: [q2.json.message.message_handle]
        })
        await core.peerSend({
          actor: 'peer_b',
          to: core.addresses.client,
          content: 'Answer to Q1 second',
          reply_to: [q1.json.message.message_handle]
        })

        // NativeLink + include_native_source=true on q1
        await core.request('PUT', `/projects/${pid}/native-links/t4-04-link`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 't4-04-nlink' },
          body: core.nativeLinkFixture
        })
        const q1Read = await core.request(
          'GET',
          `/projects/${pid}/messages/${encodeURIComponent(q1.json.message.message_handle)}?include_native_source=true`,
          { token: core.tokens.client }
        )
        assert.equal(q1Read.json.native_source.available, true)

        // Fault inject post-commit drop & retry (T05)
        await core.setFault({ drop_next_send_response: true })
        const dropped = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 't4-04-drop' },
          body: { to: core.addresses.peer_b, content: 'Fault recovery message' }
        })
        assert.equal(dropped.status, 503)
        await core.restartServer({ reusePort: true })
        const recovered = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 't4-04-drop' },
          body: { to: core.addresses.peer_b, content: 'Fault recovery message' }
        })
        assert.ok(recovered.status === 200 || recovered.status === 201)

        // Verify full UI rendering (messages, out-of-order reply links, attachment, 600x400 fit) post Core restart
        const dlgLive = await openCollaborationDialog(page)
        await selectCollaborationContact(dlgLive, 'slot-b')
        await dlgLive.getByText('Answer to Q2 first', { exact: false }).first().waitFor({ state: 'visible', timeout: 10000 })
        await dlgLive.getByText('Answer to Q1 second', { exact: false }).first().waitFor({ state: 'visible', timeout: 8000 })
        await dlgLive.getByRole('button', { name: /episode\.txt/i }).first().waitFor({ state: 'visible', timeout: 8000 })

        await setViewportSize(app, page, 600, 400)
        const dialog600 = await dlgLive.evaluate((el) => {
          const r = el.getBoundingClientRect()
          return {
            left: Math.round(r.left),
            right: Math.round(r.right),
            vw: window.innerWidth,
            overflowX: document.documentElement.scrollWidth > window.innerWidth + 2
          }
        })
        assert.ok(
          dialog600.left >= -1 && dialog600.right <= dialog600.vw + 1 && !dialog600.overflowX,
          `T4-04 Collaboration dialog overflowed 600x400: ${JSON.stringify(dialog600)}`
        )
        await setViewportSize(app, page, 1280, 800)

        // Token revocation (T07): verify 403 authorization_denied & UI search error alert
        await core.revokeToken('client')
        const denied = await core.request('GET', `/projects/${pid}/messages`, {
          token: core.tokens.client
        })
        assert.equal(denied.status, 403, denied.text)
        assert.equal(denied.json?.error?.code, 'authorization_denied', denied.text)

        const searchInput = dlgLive.locator('main form input').first()
        await searchInput.fill('Question')
        await searchInput.press('Enter')
        await dlgLive.locator('[role="alert"]').first().waitFor({ state: 'visible', timeout: 8000 })
        await closeCollaborationDialogWithFocusCheck(page, dlgLive)

        return {
          titleStatus,
          reconnectedStatus,
          nativeSourceAvailable: true,
          recoveredStatus: recovered.status,
          revokedStatus: denied.status,
          dialog600
        }
      } finally {
        await closeElectronApp(inst)
        await core.cleanup()
      }
    }
  },
  {
    id: 'T4-05',
    tier: 4,
    featureArea: 'E2E-F01+E2E-F03+E2E-F04',
    refs: ['J07', 'J08', 'J11', 'J12', 'M.02.01-M.02.24'],
    async run(ctx) {
      const repo = createTempGitRepo({
        name: 't4-05-space',
        worktrees: [
          { branch: 'wt-clean' },
          { branch: 'wt-unique', uniqueCommitFile: 'unique.txt', uniqueCommitContent: 'keep\n' }
        ]
      })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        const existing = new Set(app.windows())
        await page.getByRole('button', { name: /^(Resource Manager|资源管理器)/i }).first().click()
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
        const spaceText = await spacePage.locator('body').innerText()
        assert.ok(spaceText.length > 0, 'Space window empty')
        await spacePage.close()
        return { spaceWorkloadVerified: true, branchList: repo.getBranches() }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T4-06',
    tier: 4,
    featureArea: 'E2E-F06',
    refs: ['T08', 'UX22', 'ORIGINAL_REQUEST:R1-R3'],
    timeoutMs: 360_000,
    async run(ctx) {
      const links = checkMarkdownLinks({
        specRoot: ctx.specRoot,
        orcaFirstPath: path.join(path.dirname(ctx.specRoot), 'ORCA-FIRST.zh-CN.md')
      })
      assert.equal(links.brokenCount, 0, `Broken links: ${JSON.stringify(links.broken)}`)

      const apiParity = checkApiScopeParity({ clientDocsDir: path.dirname(ctx.specRoot) })
      assert.equal(apiParity.totalOps, 35)
      assert.deepEqual(apiParity.missingInFull, [])
      assert.deepEqual(apiParity.missingInP1, [])

      const gitCheck = verifyGitBaselines({
        agentCollabRoot: ctx.agentCollabRoot,
        historyRoot: ctx.historyRoot
      })
      assert.equal(gitCheck.ok, true, `Git baseline drift: ${gitCheck.issues.join(' | ')}`)

      const staged = runStagedBuildCoverage({
        specRoot: ctx.specRoot,
        porpitaRoot: ctx.porpitaRoot,
        historyRoot: ctx.historyRoot,
        agentCollabRoot: ctx.agentCollabRoot
      })
      assert.equal(staged.sourceIndexExitCode, 0, staged.sourceIndexStderr)

      const designEv = runDesignEvidenceCheck({
        agentCollabRoot: ctx.agentCollabRoot,
        porpitaRoot: ctx.porpitaRoot
      })
      if (designEv.applicable) {
        assert.equal(designEv.exitCode, 0, designEv.stderr)
      }

      const orcaCw = checkOrcaFirstCrosswalk({
        orcaFirstPath: path.join(path.dirname(ctx.specRoot), 'ORCA-FIRST.zh-CN.md'),
        specRoot: ctx.specRoot
      })
      const refCw = checkReferenceCrosswalk({
        refRoot: ctx.refRoot,
        specRoot: ctx.specRoot
      })

      if (
        staged.buildCoverageExitCode !== 0 ||
        !orcaCw.referencedOrcaFirst ||
        orcaCw.untracedTs.length > 0 ||
        !refCw.hasExplicitOpenCrosswalk
      ) {
        pendingIfSmoke(
          ctx.mode,
          'M4',
          'Full M4 UI SPEC structural parity + ORCA-FIRST (T01-T12) + Reference #1-#12 crosswalks',
          `buildCoverageExit=${staged.buildCoverageExitCode}, orcaReferenced=${orcaCw.referencedOrcaFirst}, untracedTs=${orcaCw.untracedTs.join(',')}, openCrosswalk=${refCw.hasExplicitOpenCrosswalk}`
        )
      }
      return {
        linksChecked: links.checkedFilesCount,
        apiOps: apiParity.totalOps,
        gitBaselinesOk: gitCheck.ok,
        domains: staged.stdoutJson?.domains,
        rows: staged.stdoutJson?.rows
      }
    }
  },
  {
    id: 'T4-07',
    tier: 4,
    featureArea: 'E2E-F06',
    refs: ['R3', 'COVERAGE_CLOSURE.md', 'UX22'],
    async run(ctx) {
      const honesty = checkEnvBoundedHonesty({ specRoot: ctx.specRoot })
      assert.deepEqual(honesty.uncoveredCategories, [])
      assert.deepEqual(honesty.dishonestFindings, [])
      return {
        envBoundedRegistryCount: ENV_BOUNDED_ITEMS.length,
        items: ENV_BOUNDED_ITEMS.map((item) => ({
          id: item.id,
          category: item.category,
          refs: item.refs,
          condition: item.condition,
          status: 'ENV_BOUNDED_VERIFIED_HONEST'
        })),
        ...honesty
      }
    }
  }
]
