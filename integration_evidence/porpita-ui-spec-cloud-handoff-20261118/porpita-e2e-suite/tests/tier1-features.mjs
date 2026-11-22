import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import {
  activateWorkspaceTab,
  addLocalFolderProject,
  addSessionToActiveWorkspace,
  assertAllWindowsHidden,
  assertHorizontalToolbarLayout,
  closeCollaborationDialogWithFocusCheck,
  closeElectronApp,
  connectCollaborationViaSettings,
  detectWorkspaceShell,
  disconnectCollaborationViaSettings,
  dismissStartupDialogs,
  ensureDualPaneWorkspace,
  getCollaborationTrigger,
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
  startLoopbackHttpServer,
  verifyGitBaselines
} from '../lib/fixtures.mjs'
import { createIsolatedProfileDirs } from '../lib/electron-harness.mjs'
import {
  checkEnvBoundedHonesty,
  checkMarkdownLinks,
  checkOrcaFirstCrosswalk,
  checkReferenceCrosswalk,
  runStagedBuildCoverage
} from '../lib/spec-audit-harness.mjs'
import { pendingIfSmoke } from '../lib/test-context.mjs'

export const TIER1_TESTS = [
  // =========================================================================
  // E2E-F01: Porpita Desktop Shell & Production Integration (6 Tests)
  // =========================================================================
  {
    id: 'T1-F01-01',
    tier: 1,
    featureArea: 'E2E-F01',
    refs: ['PROJECT:F07', 'UX02', 'A'],
    timeoutMs: 360_000,
    async run(ctx) {
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { page, app } = inst
        await page
          .locator('[data-contextual-tour-target="sidebar-navigation"] button')
          .first()
          .waitFor({ state: 'visible', timeout: 15000 })
        await assertAllWindowsHidden(app)

        const shell = await page.evaluate(() => ({
          hasSidebar: Boolean(document.querySelector('[data-contextual-tour-target="sidebar-navigation"]')),
          hasWorkbench: Boolean(document.querySelector('[data-workbench-viewport]')) || Boolean(document.querySelector('main')),
          hasSettingsBtn: Boolean(document.querySelector('button[aria-label="Settings"], button[aria-label="设置"]')),
          hasCollabBtn: Boolean(document.querySelector('button[aria-label="Collaboration"], button[aria-label="协作消息"]')),
          hasGroupSelector: Boolean(document.querySelector('[data-workspace-group-selector], [data-workspace-preview-group]')),
          hasTabStrip: Boolean(document.querySelector('[data-workspace-tab-strip], .terminal-tab-strip')),
          hasSessionIndex: Boolean(document.querySelector('[data-session-index]'))
        }))
        assert.equal(shell.hasSidebar, true, 'Left sidebar missing')
        assert.equal(shell.hasSettingsBtn, true, 'Settings button missing')
        assert.equal(shell.hasCollabBtn, true, 'Titlebar Collaboration button missing')

        const ws = await detectWorkspaceShell(page)
        if (!ws.integrated) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Default production build renders integrated Workspace shell without preview-only toggle',
            `previewToggle=${ws.previewToggle}, hasWorkspaceTabs=${ws.hasWorkspaceTabs}`
          )
        }
        assert.equal(shell.hasWorkbench, true, 'Main workbench viewport missing')
        assert.equal(shell.hasGroupSelector, true, 'Top-level group selector missing')
        assert.equal(shell.hasTabStrip, true, 'Top-level workspace tab strip missing')
        assert.equal(shell.hasSessionIndex, true, 'Sidebar Session Index missing')
        assert.equal(ws.previewToggle, false, 'Preview-only toggle should be retired once integrated')
        return { shell, ws }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T1-F01-02',
    tier: 1,
    featureArea: 'E2E-F01',
    refs: ['D.07', 'D.08', 'A.02'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't1-f01-02' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { page, app } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        const ws = await detectWorkspaceShell(page)
        if (!ws.integrated) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Top-level Workspace creation & default naming in default build',
            'Integrated Workspace tab creation control not yet present in default build'
          )
        }
        const tabs = page.locator(M3_SELECTOR_CONTRACT.workspaceTab)
        await tabs.first().waitFor({ state: 'visible', timeout: 8000 })
        const beforeTabs = await tabs.count()
        await page
          .getByRole('button', { name: /^(New work object|新建工作对象)$/i })
          .first()
          .click()
        await page
          .getByRole('menuitem', { name: /^(New workspace|新建工作空间)$/i })
          .first()
          .click()
        await page.waitForFunction(
          ({ sel, expected }) => document.querySelectorAll(sel).length === expected,
          { sel: M3_SELECTOR_CONTRACT.workspaceTab, expected: beforeTabs + 1 },
          { timeout: 8000 }
        )
        const activeTab = page.locator(`${M3_SELECTOR_CONTRACT.workspaceTab}[aria-current="page"]`).first()
        await activeTab.waitFor({ state: 'visible', timeout: 5000 })
        const createdTabText = (await activeTab.innerText()).trim()
        assert.match(createdTabText, /Workspace|工作空间/i, `Unexpected default title: ${createdTabText}`)
        await page.locator('[data-workspace-preview-object]').first().waitFor({ state: 'visible', timeout: 5000 })
        return { beforeTabs, afterTabs: await tabs.count(), createdTabText }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T1-F01-03',
    tier: 1,
    featureArea: 'E2E-F01',
    refs: ['D.08.01', 'DDU-03'],
    async run(ctx) {
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { page } = inst
        const ws = await detectWorkspaceShell(page)
        if (!ws.integrated) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Top-level Tab Group create/switch/rename/delete in default build',
            'Top-level Tab Group UI not yet integrated into default production build'
          )
        }
        const groupBtn = page.locator(M3_SELECTOR_CONTRACT.groupSelector).first()
        await groupBtn.waitFor({ state: 'visible', timeout: 8000 })

        // 1. Create group
        await groupBtn.click()
        await page.getByRole('menuitem', { name: /New tab group|新建标签组/i }).first().click()
        const nameInput = page.getByRole('dialog').locator('input').first()
        await nameInput.waitFor({ state: 'visible', timeout: 5000 })
        await nameInput.fill('E2E Group')
        await page
          .getByRole('dialog')
          .getByRole('button', { name: /^(Create group|Create|创建分组|创建|确认)$/i })
          .first()
          .click()
        await page.waitForFunction(
          (sel) => /E2E Group/.test(document.querySelector(sel)?.textContent || ''),
          M3_SELECTOR_CONTRACT.groupSelector,
          { timeout: 6000 }
        )

        // 2. Switch to General and back to E2E Group
        await groupBtn.click()
        await page.getByRole('menuitemradio', { name: /^(General|常规|通用)$/i }).first().click()
        await page.waitForFunction(
          (sel) => /General|常规|通用/i.test(document.querySelector(sel)?.textContent || ''),
          M3_SELECTOR_CONTRACT.groupSelector,
          { timeout: 6000 }
        )
        await groupBtn.click()
        await page.getByRole('menuitemradio', { name: 'E2E Group', exact: true }).first().click()
        await page.waitForFunction(
          (sel) => /E2E Group/.test(document.querySelector(sel)?.textContent || ''),
          M3_SELECTOR_CONTRACT.groupSelector,
          { timeout: 6000 }
        )

        // 3. Rename E2E Group -> E2E Renamed
        await groupBtn.click()
        const renameItem = page.locator(M3_SELECTOR_CONTRACT.groupRename).first()
        await renameItem.waitFor({ state: 'visible', timeout: 5000 })
        await renameItem.click()
        const renameInput = page.getByRole('dialog').locator('input').first()
        await renameInput.waitFor({ state: 'visible', timeout: 5000 })
        await renameInput.fill('E2E Renamed')
        await page
          .getByRole('dialog')
          .getByRole('button', { name: /^(Save|保存|Confirm|确认)$/i })
          .first()
          .click()
        await page.waitForFunction(
          (sel) => /E2E Renamed/.test(document.querySelector(sel)?.textContent || ''),
          M3_SELECTOR_CONTRACT.groupSelector,
          { timeout: 6000 }
        )

        // 4. Delete E2E Renamed -> returns to General and removes E2E Renamed
        await groupBtn.click()
        const deleteItem = page.locator(M3_SELECTOR_CONTRACT.groupDelete).first()
        await deleteItem.waitFor({ state: 'visible', timeout: 5000 })
        await deleteItem.click()
        await page.waitForFunction(
          (sel) => /General|常规|通用/i.test(document.querySelector(sel)?.textContent || ''),
          M3_SELECTOR_CONTRACT.groupSelector,
          { timeout: 6000 }
        )
        await groupBtn.click()
        assert.equal(await page.getByRole('menuitemradio', { name: 'E2E Renamed', exact: true }).count(), 0)
        await page.keyboard.press('Escape')
        return { groupCreateSwitchRenameDelete: true }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T1-F01-04',
    tier: 1,
    featureArea: 'E2E-F01',
    refs: ['D.08.02', 'T.03'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't1-f01-04' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        const ws = await detectWorkspaceShell(page)
        if (!ws.integrated) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Top-level Tab drag-to-group-selector & keyboard move',
            'Top-level Tab Group UI not yet integrated into default production build'
          )
        }
        const groupBtn = page.locator(M3_SELECTOR_CONTRACT.groupSelector).first()
        await groupBtn.waitFor({ state: 'visible', timeout: 8000 })

        // Ensure General has 2 tabs, then create destination Target Group
        await page.getByRole('button', { name: /^(New work object|新建工作对象)$/i }).first().click()
        await page.getByRole('menuitem', { name: /^(New workspace|新建工作空间)$/i }).first().click()
        await page.waitForFunction(
          (sel) => document.querySelectorAll(sel).length >= 2,
          M3_SELECTOR_CONTRACT.workspaceTab,
          { timeout: 6000 }
        )

        await groupBtn.click()
        await page.getByRole('menuitem', { name: /New tab group|新建标签组/i }).first().click()
        const nameInput = page.getByRole('dialog').locator('input').first()
        await nameInput.waitFor({ state: 'visible', timeout: 5000 })
        await nameInput.fill('Target Group')
        await page
          .getByRole('dialog')
          .getByRole('button', { name: /^(Create group|Create|创建分组|创建|确认)$/i })
          .first()
          .click()
        await groupBtn.click()
        await page.getByRole('menuitemradio', { name: /^(General|常规|通用)$/i }).first().click()
        await page.waitForFunction(
          (sel) => /General|常规|通用/i.test(document.querySelector(sel)?.textContent || ''),
          M3_SELECTOR_CONTRACT.groupSelector,
          { timeout: 6000 }
        )

        const tabs = page.locator(M3_SELECTOR_CONTRACT.workspaceTab)
        const firstTab = tabs.first()
        await firstTab.waitFor({ state: 'visible', timeout: 8000 })
        const beforeGeneralCount = await tabs.count()
        const movedId =
          (await firstTab.getAttribute('data-workspace-preview-tab')) ||
          (await firstTab.getAttribute('data-workspace-tab'))
        assert.ok(movedId, 'First workspace tab missing tab ID attribute')

        // Real pointer drag of Tab onto Group Selector drop zone + keyboard confirmation
        const tabBox = await firstTab.boundingBox()
        const grpBox = await groupBtn.boundingBox()
        assert.ok(tabBox && grpBox, 'Tab or group selector missing bounding box')
        await page.mouse.move(tabBox.x + tabBox.width / 2, tabBox.y + tabBox.height / 2)
        await page.mouse.down()
        await page.mouse.move(grpBox.x + grpBox.width / 2, grpBox.y + grpBox.height / 2, { steps: 14 })
        await sleep(100)
        await page.mouse.up()

        const moveHeading = page.locator('[data-workspace-preview-move-heading]').first()
        await moveHeading.waitFor({ state: 'visible', timeout: 6000 })
        const targetItem = page.getByRole('menuitemradio', { name: 'Target Group', exact: true }).first()
        await targetItem.waitFor({ state: 'visible', timeout: 5000 })
        await page.keyboard.press('ArrowDown')
        await page.keyboard.press('End')
        await targetItem.waitFor({ state: 'visible', timeout: 3000 })
        await targetItem.hover()
        await page.keyboard.press('Enter')

        await page.waitForFunction(
          ({ sel, expected }) => document.querySelectorAll(sel).length === expected,
          { sel: M3_SELECTOR_CONTRACT.workspaceTab, expected: beforeGeneralCount - 1 },
          { timeout: 6000 }
        )
        const afterGeneralCount = await tabs.count()

        await groupBtn.click()
        await page.getByRole('menuitemradio', { name: 'Target Group', exact: true }).first().click()
        const movedSelector = `button[data-workspace-preview-tab="${movedId}"], button[data-workspace-tab="${movedId}"]`
        await page.locator(movedSelector).first().waitFor({ state: 'visible', timeout: 6000 })
        const targetTabs = await tabs.count()
        assert.ok(targetTabs >= 1, `Moved tab ${movedId} should appear in Target Group`)
        return { movedId, beforeGeneralCount, afterGeneralCount, targetTabs }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T1-F01-05',
    tier: 1,
    featureArea: 'E2E-F01',
    refs: ['A.05', 'D.07.02', 'UX15'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't1-f01-05' })
      let inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      const tempRoot = inst.tempRoot
      try {
        await addLocalFolderProject(inst.app, inst.page, repo.repoPath)
        const ws = await detectWorkspaceShell(inst.page)
        if (!ws.integrated) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'porpita-workspaces.json v3 persisted & restored across clean quit in default build',
            `integrated=${ws.integrated}`
          )
        }
        await activateWorkspaceTab(inst.page, 0)
        await addSessionToActiveWorkspace(inst.page)
        const groupBtn = inst.page.locator(M3_SELECTOR_CONTRACT.groupSelector).first()
        await groupBtn.click()
        await inst.page.getByRole('menuitem', { name: /New tab group|新建标签组/i }).first().click()
        await inst.page.getByRole('dialog').locator('input').first().fill('Persist Group')
        await inst.page
          .getByRole('dialog')
          .getByRole('button', { name: /^(Create group|Create|创建分组|创建|确认)$/i })
          .first()
          .click()
        await inst.page.getByRole('button', { name: /^(New work object|新建工作对象)$/i }).first().click()
        await inst.page.getByRole('menuitem', { name: /^(New workspace|新建工作空间)$/i }).first().click()
        await inst.page.locator(M3_SELECTOR_CONTRACT.workspaceTab).first().waitFor({ state: 'visible', timeout: 6000 })

        const exitCode = await quitElectronGracefully(inst)
        assert.equal(exitCode, 0, `Clean quit returned ${exitCode}`)

        const layoutPath = path.join(inst.userDataDir, 'porpita-workspaces.json')
        const orcaDataPath = path.join(inst.userDataDir, 'orca-data.json')
        assert.equal(existsSync(orcaDataPath), true, 'orca-data.json should exist after clean quit')
        assert.equal(existsSync(layoutPath), true, 'porpita-workspaces.json missing after clean quit')
        const layout = JSON.parse(readFileSync(layoutPath, 'utf8'))
        assert.equal(layout.version, 3, `Expected strict schema version 3, got ${layout.version}`)
        assert.ok(
          Array.isArray(layout.groups) && layout.groups.some((g) => g.name === 'Persist Group'),
          'Custom Tab Group missing from saved v3 layout'
        )
        const savedWithSession = (layout.objects || []).find(
          (o) => o.kind === 'workspace' && Array.isArray(o.sessions) && o.sessions.length > 0
        )
        assert.ok(savedWithSession, 'Expected saved workspace with local session ref')
        assert.equal(savedWithSession.sessions[0].executionHostId, 'local')
        assert.equal(savedWithSession.sessions[0].pairingRevision, null)

        inst = await launchElectronApp({
          porpitaRoot: ctx.porpitaRoot,
          tempRoot,
          seedCompletedOnboarding: false
        })
        await inst.page.getByText(path.basename(repo.repoPath)).first().waitFor({ state: 'visible', timeout: 30000 })
        await inst.page.waitForFunction(
          (sel) => /Persist Group/.test(document.querySelector(sel)?.textContent || ''),
          M3_SELECTOR_CONTRACT.groupSelector,
          { timeout: 10000 }
        )
        await inst.page.locator(M3_SELECTOR_CONTRACT.workspaceTab).first().waitFor({ state: 'visible', timeout: 10000 })
        return { exitCode, layoutVersion: layout.version, restoredGroup: 'Persist Group' }
      } finally {
        await closeElectronApp(inst, { removeTempDir: true })
        repo.cleanup()
      }
    }
  },
  {
    id: 'T1-F01-06',
    tier: 1,
    featureArea: 'E2E-F01',
    refs: ['A.01', 'A.06', 'J11'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't1-f01-06' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)

        // Open Space auxiliary window via Resource Manager -> Space -> Review
        const existing = new Set(app.windows())
        const resourceBtn = page.getByRole('button', { name: /^(Resource Manager|资源管理器)/i }).first()
        await resourceBtn.waitFor({ state: 'visible', timeout: 10000 })
        await resourceBtn.click()
        const popover = page
          .locator('[data-slot="popover-content"]')
          .filter({ hasText: /Workspace disk|Space|空间/i })
          .first()
        await popover.waitFor({ state: 'visible', timeout: 10000 })
        const reviewBtn = popover
          .getByRole('button', { name: /Review in Space|在.*空间.*查看|查看|审查|评审|审阅|检查|审核|复核|Review/i })
          .last()
        const [spacePage] = await Promise.all([
          app.waitForEvent('window', { predicate: (w) => !existing.has(w), timeout: 12000 }),
          reviewBtn.click()
        ])
        await spacePage.waitForLoadState('domcontentloaded', { timeout: 15000 })
        assert.ok(new URL(spacePage.url()).pathname.endsWith('/space.html'), `Expected space.html, got ${spacePage.url()}`)
        await assertAllWindowsHidden(app)

        await spacePage.close()
        await sleep(250)
        // Main window still responsive and repo remains visible
        await page.getByText(path.basename(repo.repoPath)).first().waitFor({ state: 'visible', timeout: 8000 })
        return { spaceOpenedAndClosed: true, mainWindowAlive: true }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },

  // =========================================================================
  // E2E-F02: Onboarding, Localization, Naming & Visual Tokens (6 Tests)
  // =========================================================================
  {
    id: 'T1-F02-01',
    tier: 1,
    featureArea: 'E2E-F02',
    refs: ['F01', 'B.01-B.04', 'J01'],
    async run(ctx) {
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        seedCompletedOnboarding: false,
        extraEnv: { LANG: 'zh_CN.UTF-8' }
      })
      try {
        const { page } = inst
        const modal = page.locator('[role="dialog"][data-onboarding-modal]').first()
        await modal.waitFor({ state: 'visible', timeout: 15000 })
        // Switch UI language to zh if language selector is visible or check step text
        const zhOption = modal.getByRole('button', { name: /简体中文|中文/i }).first()
        if (await zhOption.isVisible().catch(() => false)) {
          await zhOption.click()
          await sleep(200)
        }
        const step0Text = await modal.innerText()
        // Check if zh onboarding still contains untranslated English headings/descriptions
        const hasUntranslatedHeadings =
          /How do you want to work with agents\?|Pick your default agent|Make it feel like home|Set up notifications/i.test(
            step0Text
          )
        // Test Continue / Back / Skip flow
        const skipOrLater = modal.getByRole('button', { name: /稍后设置|Set up later|Skip/i }).first()
        await skipOrLater.waitFor({ state: 'visible', timeout: 8000 })
        if (hasUntranslatedHeadings) {
          pendingIfSmoke(
            ctx.mode,
            'M1',
            'Simplified Chinese onboarding renders translated Chinese titles/instructions',
            `Mixed English found in onboarding modal: ${step0Text.slice(0, 200)}`
          )
        }
        return { step0Preview: step0Text.slice(0, 160) }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T1-F02-02',
    tier: 1,
    featureArea: 'E2E-F02',
    refs: ['F01', 'B.01-B.04', 'J01'],
    async run(ctx) {
      let inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        seedCompletedOnboarding: false
      })
      const tempRoot = inst.tempRoot
      try {
        const { page } = inst
        const modal = page.locator('[role="dialog"][data-onboarding-modal]').first()
        await modal.waitFor({ state: 'visible', timeout: 15000 })
        const skipBtn = modal.getByRole('button', { name: /Set up later|稍后设置/i }).first()
        await skipBtn.click()
        const confirmSkip = page.getByRole('dialog').getByRole('button', { name: /^(Skip|跳过)$/i }).first()
        if (await waitForVisible(confirmSkip, 3000)) {
          await confirmSkip.click()
        }
        await modal.waitFor({ state: 'hidden', timeout: 10000 })

        await quitElectronGracefully(inst)
        inst = await launchElectronApp({
          porpitaRoot: ctx.porpitaRoot,
          tempRoot,
          seedCompletedOnboarding: false
        })
        await sleep(1000)
        const reopenedModalCount = await inst.page
          .locator('[role="dialog"][data-onboarding-modal]:visible')
          .count()
        assert.equal(reopenedModalCount, 0, 'Onboarding must NOT re-open after skip/completion')
        return { reopenedWithoutOnboarding: true }
      } finally {
        await closeElectronApp(inst, { removeTempDir: true })
      }
    }
  },
  {
    id: 'T1-F02-03',
    tier: 1,
    featureArea: 'E2E-F02',
    refs: ['F02', 'M.01', 'UX18'],
    async run(ctx) {
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        profileOptions: { locale: 'en' }
      })
      try {
        const { page } = inst
        await page
          .locator('[data-contextual-tour-target="sidebar-navigation"]')
          .waitFor({ state: 'visible', timeout: 12000 })
        const sidebarText = await page
          .locator('[data-contextual-tour-target="sidebar-navigation"]')
          .innerText()
        if (/Orca Mobile/i.test(sidebarText)) {
          pendingIfSmoke(
            ctx.mode,
            'M1',
            'Sidebar mobile entry named "Porpita Mobile" (zero "Orca Mobile")',
            `Observed "Orca Mobile" in SidebarNav: ${JSON.stringify(sidebarText)}`
          )
        }
        assert.match(sidebarText, /Porpita Mobile|Porpita 手机端/i)
        return { sidebarText }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T1-F02-04',
    tier: 1,
    featureArea: 'E2E-F02',
    refs: ['F03', 'L.04'],
    async run(ctx) {
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        profileOptions: { locale: 'en', settings: { showArtifactsButton: true } }
      })
      try {
        const { page } = inst
        const artifactsBtn = page.getByRole('button', { name: /^(Artifacts|工件)$/i }).first()
        await artifactsBtn.waitFor({ state: 'visible', timeout: 10000 })
        await artifactsBtn.click()
        const main = page.locator('main').first()
        await main.waitFor({ state: 'visible', timeout: 15000 })
        await page.waitForFunction(
          () => {
            const mainEl = document.querySelector('main')
            if (!mainEl) return false
            if (mainEl.querySelector('[role="status"][aria-busy="true"]')) return false
            const hasContent = Boolean(mainEl.querySelector('h2, p'))
            return hasContent && mainEl.innerText.trim().length > 0
          },
          null,
          { timeout: 15000 }
        )
        const bodyText = (await main.innerText()).trim()
        if (/Orca account sign-in is not configured|Orca account/i.test(bodyText)) {
          pendingIfSmoke(
            ctx.mode,
            'M1',
            'ArtifactsPage honest Porpita local-capability empty state without "Orca account" string',
            `Observed: ${bodyText.slice(0, 220)}`
          )
        }
        assert.ok(bodyText.length > 0, 'Artifacts empty state rendered')
        return { excerpt: bodyText.slice(0, 200) }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T1-F02-05',
    tier: 1,
    featureArea: 'E2E-F02',
    refs: ['F01', 'B.05', 'O.local.contextual-tour'],
    async run(ctx) {
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        profileOptions: {
          locale: 'en',
          ui: { contextualToursAutoEligible: true, contextualToursSeenIds: [] }
        }
      })
      try {
        const { page } = inst
        await page
          .locator('[data-contextual-tour-target="sidebar-navigation"]')
          .waitFor({ state: 'visible', timeout: 12000 })
        // Trigger Help -> Onboarding or Contextual Tour skip if active
        const skipTour = page.getByRole('button', { name: /Skip tour|Close tour|跳过导览/i }).first()
        if (await waitForVisible(skipTour, 2500)) {
          await skipTour.click()
          await skipTour.waitFor({ state: 'hidden', timeout: 5000 })
        }
        // Verify workbench buttons remain clickable (no focus/overlay trap)
        await openSettingsPage(page)
        await returnFromSettings(page)
        return { tourHandledAndFocusFree: true }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T1-F02-06',
    tier: 1,
    featureArea: 'E2E-F02',
    refs: ['F03', 'P.*', 'P.13', 'Q.*', 'STYLEGUIDE'],
    async run(ctx) {
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        profileOptions: { locale: 'en', theme: 'dark', reducedMotion: true }
      })
      try {
        const { page } = inst
        await page.emulateMedia({ reducedMotion: 'reduce' })
        await page.waitForFunction(() => document.documentElement.classList.contains('dark'), null, {
          timeout: 8000
        })
        await dismissStartupDialogs(page)

        const tokens = await page.evaluate(() => {
          const style = getComputedStyle(document.documentElement)
          const bodyStyle = getComputedStyle(document.body)
          return {
            initialLang: document.documentElement.lang,
            isDark: document.documentElement.classList.contains('dark'),
            reducedMotionQuery: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
            radius: style.getPropertyValue('--radius').trim(),
            background: style.getPropertyValue('--background').trim(),
            card: style.getPropertyValue('--card').trim(),
            border: style.getPropertyValue('--border').trim(),
            fontFamily: bodyStyle.fontFamily
          }
        })
        assert.equal(tokens.initialLang, 'en', `Expected initial <html lang="en">, got ${tokens.initialLang}`)
        assert.equal(tokens.isDark, true, 'Dark theme class missing')
        assert.equal(tokens.reducedMotionQuery, true, 'Reduced motion media emulation inactive')
        assert.ok(tokens.radius, '--radius token must be defined')
        assert.ok(tokens.background && tokens.card && tokens.border, 'Semantic surface tokens missing')

        // Controlled AddRepoDialog Escape focus restoration check (P.* / F03)
        const addProjectBtn = page.getByRole('button', { name: /^(Add project|添加项目)$/i }).last()
        await addProjectBtn.waitFor({ state: 'visible', timeout: 10000 })
        await addProjectBtn.evaluate((el) => {
          window.__e2eAddRepoTrigger = el
        })
        await addProjectBtn.focus()
        const focusedBeforeOpen = await page.evaluate(
          () => document.activeElement === window.__e2eAddRepoTrigger
        )
        assert.equal(focusedBeforeOpen, true, 'Failed to focus Add project trigger before opening dialog')
        await addProjectBtn.click()
        const dialog = page.locator('[data-slot="dialog-content"]').first()
        await dialog.waitFor({ state: 'visible', timeout: 8000 })
        for (let i = 0; i < 2; i++) {
          await page.keyboard.press('Tab')
          const focusInside = await page.evaluate(() => {
            const dlg = document.querySelector('[data-slot="dialog-content"]')
            return Boolean(dlg && dlg.contains(document.activeElement))
          })
          assert.equal(focusInside, true, 'Tab focus escaped AddRepoDialog')
        }
        await page.keyboard.press('Escape')
        await dialog.waitFor({ state: 'hidden', timeout: 5000 })
        let dialogEscapeFocusRestored = false
        try {
          await page.waitForFunction(
            () => document.activeElement === window.__e2eAddRepoTrigger,
            null,
            { timeout: 3000 }
          )
          dialogEscapeFocusRestored = true
        } catch {
          dialogEscapeFocusRestored = false
        }
        assert.equal(
          dialogEscapeFocusRestored,
          true,
          'Controlled AddRepoDialog Escape must restore focus to trigger button instead of document.body'
        )

        // Live <html lang> switch en -> zh -> ja without restart (P.13)
        await openSettingsPage(page)
        await page
          .locator('aside button')
          .filter({ hasText: /^(Appearance|外观|外観)$/i })
          .first()
          .click()
        const langSelect = page
          .getByRole('combobox', { name: /^(Language|语言|言語)$/i })
          .first()
        await langSelect.waitFor({ state: 'visible', timeout: 8000 })
        await langSelect.click()
        await page.getByRole('option', { name: '中文（简体）' }).click()
        await page.waitForFunction(() => document.documentElement.lang === 'zh', null, {
          timeout: 8000
        })
        const zhLang = await page.evaluate(() => document.documentElement.lang)
        assert.equal(zhLang, 'zh', `Expected <html lang="zh">, got ${zhLang}`)

        await langSelect.click()
        await page.getByRole('option', { name: '日本語' }).click()
        await page.waitForFunction(() => document.documentElement.lang === 'ja', null, {
          timeout: 8000
        })
        const jaLang = await page.evaluate(() => document.documentElement.lang)
        assert.equal(jaLang, 'ja', `Expected <html lang="ja">, got ${jaLang}`)
        await returnFromSettings(page)

        return {
          ...tokens,
          dialogEscapeFocusRestored,
          langFlow: [tokens.initialLang, zhLang, jaLang]
        }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },

  // =========================================================================
  // E2E-F03: Workspace, Session Index & SidePanels (6 Tests)
  // =========================================================================
  {
    id: 'T1-F03-01',
    tier: 1,
    featureArea: 'E2E-F03',
    refs: ['C.10.03', 'C.10.04', 'J03'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't1-f03-01' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        const ws = await detectWorkspaceShell(page)
        if (!ws.integrated) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Integrated Sidebar Session Index filtering & Group By in default build',
            'Session Index not yet integrated into default production build'
          )
        }
        await activateWorkspaceTab(page, 0)
        await addSessionToActiveWorkspace(page)

        const sessionIndex = page.locator(M3_SELECTOR_CONTRACT.sessionIndex).first()
        await sessionIndex.waitFor({ state: 'visible', timeout: 8000 })
        const toggleBtn = sessionIndex.locator(M3_SELECTOR_CONTRACT.sessionIndexToggle).first()
        if ((await waitForVisible(toggleBtn, 1000)) && (await toggleBtn.getAttribute('aria-expanded')) === 'false') {
          await toggleBtn.click()
        }
        const rows = sessionIndex.locator(M3_SELECTOR_CONTRACT.sessionIndexRow)
        await rows.first().waitFor({ state: 'visible', timeout: 8000 })
        const initialRows = await rows.count()

        const searchInput = sessionIndex.locator('input').first()
        await searchInput.waitFor({ state: 'visible', timeout: 5000 })
        await searchInput.fill('__no_matching_session_xyz__')
        await sessionIndex.locator('[role="status"]').first().waitFor({ state: 'visible', timeout: 5000 })
        const clearBtn = sessionIndex.locator(M3_SELECTOR_CONTRACT.sessionIndexClearFilters).first()
        await clearBtn.waitFor({ state: 'visible', timeout: 5000 })
        await clearBtn.click()
        await rows.first().waitFor({ state: 'visible', timeout: 5000 })
        assert.equal(await searchInput.inputValue(), '', 'Clear filters must reset search query')

        const optionsBtn = sessionIndex.locator('[data-session-index-scope]').first()
        await optionsBtn.waitFor({ state: 'visible', timeout: 5000 })
        await optionsBtn.click()
        await page.getByRole('menuitemradio', { name: /^(Project|项目)$/i }).first().click()
        await sessionIndex.locator('[cmdk-group-heading]').first().waitFor({ state: 'visible', timeout: 5000 })
        const groupHeading = (await sessionIndex.locator('[cmdk-group-heading]').first().innerText()).trim()
        assert.ok(groupHeading.length > 0, 'Project grouping heading missing')
        await optionsBtn.click()
        await page.getByRole('menuitemradio', { name: /^(Recent|最近)$/i }).first().click()
        return { initialRows, groupHeading }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T1-F03-02',
    tier: 1,
    featureArea: 'E2E-F03',
    refs: ['C.10.02', 'DDU-02', 'J03'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't1-f03-02' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        const ws = await detectWorkspaceShell(page)
        if (!ws.integrated) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Session Index single/double-click reuse & focus in default build',
            'Session Index not yet integrated into default production build'
          )
        }
        await activateWorkspaceTab(page, 0)
        await addSessionToActiveWorkspace(page)

        const sessionIndex = page.locator(M3_SELECTOR_CONTRACT.sessionIndex).first()
        await sessionIndex.waitFor({ state: 'visible', timeout: 8000 })
        const toggleBtn = sessionIndex.locator(M3_SELECTOR_CONTRACT.sessionIndexToggle).first()
        if ((await waitForVisible(toggleBtn, 1000)) && (await toggleBtn.getAttribute('aria-expanded')) === 'false') {
          await toggleBtn.click()
        }
        const rows = sessionIndex.locator(M3_SELECTOR_CONTRACT.sessionIndexRow)
        await rows.first().waitFor({ state: 'visible', timeout: 8000 })
        const rowText = await rows.first().innerText()
        assert.match(rowText, /Open in|打开/i, `Expected Workspace destination badge on row, got: ${rowText}`)

        const initialTabCount = await page.locator(M3_SELECTOR_CONTRACT.workspaceTab).count()
        await rows.first().click()
        await page.waitForFunction(
          () => Boolean(document.activeElement?.closest('[data-workspace-preview-session] [data-native-chat-composer-scope]')),
          null,
          { timeout: 6000 }
        )
        await rows.first().dblclick()
        const afterTabCount = await page.locator(M3_SELECTOR_CONTRACT.workspaceTab).count()
        assert.equal(
          afterTabCount,
          initialTabCount,
          'Activating an already-open session row must reuse existing tab without duplicating'
        )
        return { initialTabCount, afterTabCount, composerFocused: true }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T1-F03-03',
    tier: 1,
    featureArea: 'E2E-F03',
    refs: ['C.10.05', 'C.10.06', 'G.06'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't1-f03-03' })
      const dirs = createIsolatedProfileDirs()
      createCodexHistoryFixture({
        homeDir: dirs.homeDir,
        repoPath: repo.repoPath,
        prompt: 'Follow up on the release checklist',
        reply: 'The saved release notes are ready for review.'
      })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot, tempRoot: dirs.tempRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        // Verify Vault ("Agents") dock opens and finds the synthetic Codex history
        const agentsBtn = page.getByRole('button', { name: /^(Agents|智能体)(?:\s|$)/i }).first()
        if (!(await waitForVisible(agentsBtn, 1500))) {
          const rightToggle = page.locator('[data-workspace-sidebar-toggle="right"]').first()
          if (await waitForVisible(rightToggle, 3000)) {
            await rightToggle.click()
          }
        }
        await agentsBtn.waitFor({ state: 'visible', timeout: 8000 })
        await agentsBtn.click()
        const searchBox = page.getByRole('textbox', { name: /^(Search sessions|搜索会话)$/i }).first()
        await searchBox.waitFor({ state: 'visible', timeout: 8000 })
        // Wait for initial vault history scan to load before filtering so Refresh isn't disabled by searching&&loading
        const initialRow = page.locator('.ai-vault-session-row').filter({ hasText: /release checklist/i }).first()
        if (!(await waitForVisible(initialRow, 6000))) {
          const refreshBtn = page
            .getByRole('button', { name: /Refresh Session History|刷新会话历史/i })
            .first()
          if ((await waitForVisible(refreshBtn, 1500)) && (await refreshBtn.isEnabled().catch(() => false))) {
            await refreshBtn.click()
          }
          await initialRow.waitFor({ state: 'visible', timeout: 12000 }).catch(() => {})
        }
        await searchBox.fill('release checklist')
        const vaultRow = page.locator('.ai-vault-session-row').filter({ hasText: /release checklist/i }).first()
        if (!(await waitForVisible(vaultRow, 4000))) {
          const refreshBtn = page
            .getByRole('button', { name: /Refresh Session History|刷新会话历史/i })
            .first()
          if ((await waitForVisible(refreshBtn, 1500)) && (await refreshBtn.isEnabled().catch(() => false))) {
            await refreshBtn.click()
          }
        }
        await vaultRow.waitFor({ state: 'visible', timeout: 15000 })

        // Close right sidebar so Session Index history handoff is unambiguously tested
        const closeRightBtn = page.locator('[data-workspace-sidebar-toggle="right"][aria-expanded="true"]').first()
        if (await waitForVisible(closeRightBtn, 1000)) {
          await closeRightBtn.click()
        }

        const ws = await detectWorkspaceShell(page)
        if (!ws.integrated) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Session Index <-> Vault handoff in default build',
            'Vault search verified; Session Index integration pending M3'
          )
        }
        const sessionIndex = page.locator(M3_SELECTOR_CONTRACT.sessionIndex).first()
        await sessionIndex.waitFor({ state: 'visible', timeout: 8000 })
        const query = 'release checklist'
        await sessionIndex.locator('input').first().fill(query)

        // 1. Clicking "Search history" hands off query cleanly into Right-Sidebar Vault
        await sessionIndex.getByRole('button', { name: /Search history|搜索历史/i }).first().click()
        const vaultSearch = page.getByRole('textbox', { name: /^(Search sessions|搜索会话)$/i }).first()
        await vaultSearch.waitFor({ state: 'visible', timeout: 8000 })
        await page.locator('.ai-vault-session-row').filter({ hasText: /release checklist/i }).first().waitFor({ state: 'visible', timeout: 10000 })
        const closeRightAfterHandoff = page.locator('[data-workspace-sidebar-toggle="right"][aria-expanded="true"]').first()
        if (await waitForVisible(closeRightAfterHandoff, 1000)) {
          await closeRightAfterHandoff.click()
        }

        // 2. Switching SessionIndex view to "Unopened history" mounts [data-session-index-history] and resumes Codex session.
        // Clear the filter box first so compact Unopened history lists sessions without triggering the FTS consent banner.
        await sessionIndex.locator('input').first().fill('')
        await sessionIndex.locator('[data-session-index-scope]').first().click()
        await page.getByRole('menuitemradio', { name: /Unopened history|未打开的历史会话|未打开的历史记录/i }).first().click()
        const historyContainer = sessionIndex.locator(M3_SELECTOR_CONTRACT.sessionIndexHistory).first()
        await historyContainer.waitFor({ state: 'visible', timeout: 8000 })
        const historyRow = historyContainer.locator('.ai-vault-session-row').filter({ hasText: /release checklist/i }).first()
        if (!(await waitForVisible(historyRow, 3000))) {
          const histRefresh = historyContainer
            .getByRole('button', { name: /Refresh Session History|刷新会话历史/i })
            .first()
          if (await waitForVisible(histRefresh, 1500)) {
            await histRefresh.click()
          }
        }
        await historyRow.waitFor({ state: 'visible', timeout: 10000 })
        await historyRow.getByTestId('ai-vault-session-more-actions').click()
        await page.getByRole('menuitem', { name: /^(Resume in New Chat|在新聊天中恢复)$/i }).first().click()
        const trustBtn = page
          .getByRole('button', { name: /^(Trust repository|信任仓库|Let agents ask|让智能体询问)$/i })
          .first()
        if (await waitForVisible(trustBtn, 3000)) {
          await trustBtn.click()
        }
        await page.getByText('The saved release notes are ready for review.', { exact: false }).first().waitFor({ state: 'visible', timeout: 15000 })
        return { vaultSearchVisible: true, sessionIndexHistoryHandoff: true }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T1-F03-04',
    tier: 1,
    featureArea: 'E2E-F03',
    refs: ['D.03', 'D.03.01', 'D.04', 'T.03'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't1-f03-04' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        const ws = await detectWorkspaceShell(page)
        if (!ws.integrated) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Multi-pane split, 5% keyboard divider & maximize/restore in default build',
            'Integrated Workspace split layout pending M3'
          )
        }
        const closeRightBtn = page.locator('[data-workspace-sidebar-toggle="right"][aria-expanded="true"]').first()
        if (await waitForVisible(closeRightBtn, 800)) {
          await closeRightBtn.click()
        }
        const splitLayout = await ensureDualPaneWorkspace(page)
        await page.waitForFunction(
          () => document.querySelector('[data-workspace-preview-chat-layout]')?.getAttribute('data-preview-split') === 'side-by-side',
          null,
          { timeout: 8000 }
        )
        const separator = splitLayout.getByRole('separator').first()
        await separator.waitFor({ state: 'visible', timeout: 5000 })
        const beforeVal = Number.parseFloat((await separator.getAttribute('aria-valuenow')) || '0')
        const maxVal = Number.parseFloat((await separator.getAttribute('aria-valuemax')) || '85')
        const expectedStep = Math.min(maxVal, beforeVal + 5)
        await separator.focus()
        await page.keyboard.press('ArrowRight')
        await page.waitForFunction(
          (expected) => document.querySelector('[data-workspace-preview-chat-layout] [role="separator"]')?.getAttribute('aria-valuenow') === String(expected),
          expectedStep,
          { timeout: 5000 }
        )
        const afterVal = Number.parseFloat((await separator.getAttribute('aria-valuenow')) || '0')
        assert.equal(afterVal, expectedStep, `Expected 5% step clamped to ${maxVal} (${beforeVal} -> ${afterVal})`)

        await page.keyboard.press('ArrowLeft')
        await page.waitForFunction(
          (expected) => document.querySelector('[data-workspace-preview-chat-layout] [role="separator"]')?.getAttribute('aria-valuenow') === String(expected),
          beforeVal,
          { timeout: 5000 }
        )

        // Collapse left sidebar and shrink below 646px container to verify Switch pane single-focus + wide restore
        const leftToggle = page.locator('[data-workspace-sidebar-toggle="left"]').first()
        if ((await waitForVisible(leftToggle, 1000)) && (await leftToggle.getAttribute('aria-expanded')) === 'true') {
          await leftToggle.click()
        }
        await setViewportSize(app, page, 620, 560)
        await page.waitForFunction(
          () => document.querySelector('[data-workspace-preview-chat-layout]')?.getAttribute('data-preview-split') === 'focused',
          null,
          { timeout: 6000 }
        )
        const switchPaneBtn = page.getByRole('button', { name: /Switch pane|切换窗格/i }).first()
        await switchPaneBtn.waitFor({ state: 'visible', timeout: 5000 })
        await switchPaneBtn.click()
        const radios = page.getByRole('menuitemradio')
        assert.equal(await radios.count(), 2, 'Switch pane menu must list both workspace sessions')
        await radios.last().click()
        await setViewportSize(app, page, 1280, 800)
        await page.waitForFunction(
          () => document.querySelector('[data-workspace-preview-chat-layout]')?.getAttribute('data-preview-split') === 'side-by-side',
          null,
          { timeout: 6000 }
        )
        return { beforeVal, afterVal, narrowPaneSwitchAndRestore: true }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T1-F03-05',
    tier: 1,
    featureArea: 'E2E-F03',
    refs: ['G.09.01', 'G.09.02', 'DDU-05', 'J07'],
    async run(ctx) {
      const repoA = createTempGitRepo({
        name: 't1-f03-05-a',
        files: { 'repo-a-only.txt': 'Alpha file content\n' }
      })
      const repoB = createTempGitRepo({
        name: 't1-f03-05-b',
        files: { 'repo-b-only.txt': 'Beta file content\n' }
      })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
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
        const ws = await detectWorkspaceShell(page)
        if (!ws.integrated) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'SidePanel Explorer Standalone <-> Embedded fixed-scope continuity in default build',
            'Pinned SidePanel Standalone/Embedded integration pending M3'
          )
        }
        // Switch back to repoA, ensure active workspace + session, then open Explorer pinned to repoA
        await selectWorktreeById(page, repoAId)
        await activateWorkspaceTab(page, 0)
        await addSessionToActiveWorkspace(page)

        await page.getByRole('button', { name: /^(New work object|新建工作对象)$/i }).first().click()
        await page.getByRole('menuitem', { name: /^(Open Explorer|打开资源管理器)$/i }).first().click()
        const folderPicker = page.getByRole('dialog').filter({ hasText: /Choose a folder for Explorer|选择资源管理器的目录/i }).first()
        if (await waitForVisible(folderPicker, 1500)) {
          await folderPicker.getByRole('option').filter({ hasText: path.basename(repoA.repoPath) }).first().click()
        }

        const standaloneExplorer = page.locator(`${M3_SELECTOR_CONTRACT.explorer}[data-presentation="standalone"]`).first()
        await standaloneExplorer.waitFor({ state: 'visible', timeout: 8000 })
        const explorerId = await standaloneExplorer.getAttribute('data-workspace-preview-explorer')
        await standaloneExplorer.getByText('repo-a-only.txt', { exact: false }).first().waitFor({ state: 'visible', timeout: 8000 })
        assert.equal(await standaloneExplorer.getByText('repo-b-only.txt').count(), 0)
        const initialScope = (await standaloneExplorer.locator(M3_SELECTOR_CONTRACT.explorerScope).first().innerText()).trim()

        // Embed Explorer into Workspace 1
        await standaloneExplorer.getByRole('button', { name: /Explorer placement|资源管理器位置/i }).first().click()
        await page.getByRole('menuitem', { name: /^(Move to |移至 )/i }).first().click()
        const embeddedExplorer = page.locator(`${M3_SELECTOR_CONTRACT.explorer}[data-presentation="embedded"]`).first()
        await embeddedExplorer.waitFor({ state: 'visible', timeout: 8000 })
        assert.equal(await embeddedExplorer.getAttribute('data-workspace-preview-explorer'), explorerId)
        assert.equal((await embeddedExplorer.locator(M3_SELECTOR_CONTRACT.explorerScope).first().innerText()).trim(), initialScope)
        await embeddedExplorer.getByText('repo-a-only.txt', { exact: false }).first().waitFor({ state: 'visible', timeout: 5000 })

        // Switch active worktree in Sidebar to repoB -> embedded Explorer must stay bound to repoA!
        await selectWorktreeById(page, repoBId)
        assert.equal((await embeddedExplorer.locator(M3_SELECTOR_CONTRACT.explorerScope).first().innerText()).trim(), initialScope)
        assert.equal(await embeddedExplorer.getByText('repo-a-only.txt').count() > 0, true)
        assert.equal(await embeddedExplorer.getByText('repo-b-only.txt').count(), 0)

        // Detach back to Standalone tab -> preserves same Explorer ID & scope
        await embeddedExplorer.getByRole('button', { name: /Explorer placement|资源管理器位置/i }).first().click()
        await page.getByRole('menuitem', { name: /Open as a tab|作为标签打开/i }).first().click()
        await standaloneExplorer.waitFor({ state: 'visible', timeout: 8000 })
        assert.equal(await standaloneExplorer.getAttribute('data-workspace-preview-explorer'), explorerId)
        assert.equal((await standaloneExplorer.locator(M3_SELECTOR_CONTRACT.explorerScope).first().innerText()).trim(), initialScope)
        return { explorerId, initialScope, persistedAcrossRepoBSwitch: true }
      } finally {
        await closeElectronApp(inst)
        repoA.cleanup()
        repoB.cleanup()
      }
    }
  },
  {
    id: 'T1-F03-06',
    tier: 1,
    featureArea: 'E2E-F03',
    refs: ['C.06', 'M.02-M.02.10', 'J07'],
    async run(ctx) {
      const repo = createTempGitRepo({
        name: 't1-f03-06',
        worktrees: [
          { branch: 'wt-clean' },
          { branch: 'wt-unique', uniqueCommitFile: 'unique.txt', uniqueCommitContent: 'unique commit\n' }
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
        const spaceText = await spacePage.locator('body').innerText()
        assert.ok(spaceText.length > 0, 'Space window rendered empty')
        await spacePage.close()
        return { spaceRendered: true, worktreesCreated: repo.worktrees.length }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },

  // =========================================================================
  // E2E-F04: Retained Local Workbench Tools & Local Browser (6 Tests)
  // =========================================================================
  {
    id: 'T1-F04-01',
    tier: 1,
    featureArea: 'E2E-F04',
    refs: ['H.01', 'H.02', 'C.09', 'J08'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't1-f04-01' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      const mod = primaryModifierKey()
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        const notesNode = page.getByText('notes.md', { exact: true }).first()
        await notesNode.waitFor({ state: 'visible', timeout: 10000 })
        await notesNode.dblclick()
        await page.getByText('Disposable editor text.', { exact: true }).first().waitFor({ timeout: 10000 })

        // Verify Markdown Preview renders rendered headings without XSS execution
        await openMarkdownPreviewAndVerify(page, 'Release Notes')

        // Open README.md in Source mode, edit, save via Cmd/Ctrl+S, and verify disk persistence
        const readmeNode = page.getByText('README.md', { exact: true }).first()
        await readmeNode.waitFor({ state: 'visible', timeout: 8000 })
        await readmeNode.dblclick()
        const sourceToggle = page
          .locator('[data-testid="markdown-view-switcher"] [aria-label*="Source" i], [data-testid="markdown-view-switcher"] [aria-label*="源码" i]')
          .first()
        if (await waitForVisible(sourceToggle, 3000)) {
          await sourceToggle.click()
        }
        const monacoLines = page.locator('.monaco-editor .view-lines').first()
        await monacoLines.waitFor({ state: 'visible', timeout: 10000 })
        await monacoLines.click()
        const marker = 'E2E_SAVED_MARKER_F04_01'
        await page.keyboard.type(`${marker} `)
        await page.keyboard.press(`${mod}+s`)

        const readmePath = path.join(repo.repoPath, 'README.md')
        const saveDeadline = Date.now() + 8000
        let savedOnDisk = false
        while (Date.now() < saveDeadline) {
          if (readFileSync(readmePath, 'utf8').includes(marker)) {
            savedOnDisk = true
            break
          }
          await sleep(150)
        }
        assert.equal(savedOnDisk, true, 'README.md edit did not persist to disk on Cmd/Ctrl+S')

        // Trigger Quick Open (Mod+P) via before-input-event pipeline and assert real dialog + file filtering + Esc close
        await page.locator('[data-tab-id][data-active="true"]').first().click()
        await page.keyboard.press(`${mod}+p`)
        const quickOpenDialog = page.locator('[role="dialog"]:visible').last()
        const quickOpenInput = quickOpenDialog.locator('input').first()
        if (!(await waitForVisible(quickOpenInput, 2000))) {
          // Playwright CDP modifier chords emit rawKeyDown; inject native Electron keyDown through before-input-event.
          await app.evaluate(({ BrowserWindow }, isMac) => {
            const win = BrowserWindow.getAllWindows()[0]
            if (!win) return
            const modFlag = isMac ? 'meta' : 'control'
            win.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'P', modifiers: [modFlag] })
            win.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'P', modifiers: [modFlag] })
          }, process.platform === 'darwin')
        }
        await quickOpenInput.waitFor({ state: 'visible', timeout: 8000 })
        await quickOpenInput.fill('sample.csv')
        await quickOpenDialog.getByText('sample.csv', { exact: false }).first().waitFor({ state: 'visible', timeout: 8000 })
        await page.keyboard.press('Escape')
        await quickOpenDialog.waitFor({ state: 'hidden', timeout: 5000 })
        return { openedNotesMd: true, markdownPreviewOk: true, savedOnDisk: true, quickOpenVerified: true }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T1-F04-02',
    tier: 1,
    featureArea: 'E2E-F04',
    refs: ['H.03', 'J08'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't1-f04-02' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)

        // 1. CSV viewer: assert real grid, headers, rows, and 1,050 row count
        const csvItem = page.getByText('sample.csv', { exact: true }).first()
        await csvItem.waitFor({ state: 'visible', timeout: 8000 })
        await csvItem.dblclick()
        const csvGrid = page.locator('[data-testid="csv-grid"]').first()
        await csvGrid.waitFor({ state: 'visible', timeout: 10000 })
        const csvCols = await csvGrid.locator('[role="columnheader"]').count()
        const csvRows = await csvGrid.locator('[role="row"]').count()
        assert.ok(csvCols >= 4, `Expected >=4 CSV column headers, got ${csvCols}`)
        assert.ok(csvRows >= 2, `Expected >=2 visible CSV grid rows, got ${csvRows}`)
        await page.getByText(/1,?050/).first().waitFor({ state: 'visible', timeout: 6000 })

        // 2. PNG viewer: assert decoded <img> with naturalWidth > 0
        const pngItem = page.getByText('sample.png', { exact: true }).first()
        await pngItem.waitFor({ state: 'visible', timeout: 8000 })
        await pngItem.dblclick()
        const pngImg = page.locator('img[alt="sample.png"]').first()
        await pngImg.waitFor({ state: 'visible', timeout: 10000 })
        const pngLoaded = await pngImg.evaluate((el) => el.complete && el.naturalWidth > 0)
        assert.equal(pngLoaded, true, 'sample.png <img> did not finish decoding with naturalWidth > 0')

        // 3. SVG viewer: assert vector image renders with non-zero natural dimensions
        const svgItem = page.getByText('sample.svg', { exact: true }).first()
        await svgItem.waitFor({ state: 'visible', timeout: 8000 })
        await svgItem.dblclick()
        const svgImg = page.locator('img[alt="sample.svg"]').first()
        await svgImg.waitFor({ state: 'visible', timeout: 10000 })
        const svgLoaded = await svgImg.evaluate((el) => el.complete && el.naturalWidth > 0)
        assert.equal(svgLoaded, true, 'sample.svg <img> did not render with naturalWidth > 0')

        // 4. HTML preview: verify source loads and Open Preview to the Side mounts guest preview
        const htmlItem = page.getByText('preview.html', { exact: true }).first()
        await htmlItem.waitFor({ state: 'visible', timeout: 8000 })
        await htmlItem.dblclick()
        const htmlPreviewBtn = page
          .locator('button[aria-label*="Open Preview to the Side" i], button[aria-label*="在侧边打开预览" i]')
          .first()
        await htmlPreviewBtn.waitFor({ state: 'visible', timeout: 8000 })
        await htmlPreviewBtn.click()
        const guestWaitDeadline = Date.now() + 8000
        let htmlGuestLoaded = false
        while (Date.now() < guestWaitDeadline) {
          htmlGuestLoaded = await app.evaluate(({ webContents }) =>
            webContents.getAllWebContents().some((wc) => wc.getURL().toLowerCase().endsWith('/preview.html'))
          )
          if (htmlGuestLoaded) break
          await sleep(200)
        }
        assert.equal(htmlGuestLoaded, true, 'preview.html Open Preview to the Side did not load guest webContents')
        assert.equal(await page.evaluate(() => Boolean(window.__xss)), false)
        return { csvCols, csvRows, pngLoaded, svgLoaded, htmlGuestLoaded }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T1-F04-03',
    tier: 1,
    featureArea: 'E2E-F04',
    refs: ['G.03', 'H.04', 'H.05', 'J08'],
    async run(ctx) {
      const repo = createTempGitRepo({
        name: 't1-f04-03',
        dirtyFiles: { 'notes.md': '# Modified\n\nChanged in test repository\n' }
      })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        const scBtn = page.getByRole('button', { name: /^(Source Control|源代码管理|源代码控制)/i }).first()
        await scBtn.waitFor({ state: 'visible', timeout: 10000 })
        await scBtn.click()
        const changedFile = page.getByText('notes.md', { exact: true }).last()
        await changedFile.waitFor({ state: 'visible', timeout: 10000 })
        await changedFile.click()
        await page.locator('.monaco-diff-editor').first().waitFor({ state: 'visible', timeout: 10000 })

        // Verify H.05 Git Graph commit table remains visible even when a commit detail <aside> is selected
        const gitGraphBtn = page.getByRole('button', { name: /^(Git Graph|Git 图谱|提交图)/i }).first()
        await gitGraphBtn.waitFor({ state: 'visible', timeout: 8000 })
        await gitGraphBtn.click()
        const commitBtn = page.locator('button').filter({ hasText: /^Initial E2E fixture$/i }).first()
        await commitBtn.waitFor({ state: 'visible', timeout: 10000 })
        await commitBtn.click()
        await page.locator('aside').last().waitFor({ state: 'visible', timeout: 5000 })
        const commitVisibleWithDetails = await commitBtn.evaluate((el) => {
          const r = el.getBoundingClientRect()
          return r.height > 8 && r.width > 20 && r.bottom > 0 && r.top < window.innerHeight
        })
        assert.equal(
          commitVisibleWithDetails,
          true,
          'Git Graph commit table was pushed off-screen when commit detail <aside> opened'
        )
        await setViewportSize(app, page, 600, 400)
        const overflow600 = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2)
        assert.equal(overflow600, false, 'Git Graph overflowed 600x400 viewport')
        return { diffEditorVisible: true, gitGraphCommitVisibleWithAside: true, overflow600 }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T1-F04-04',
    tier: 1,
    featureArea: 'E2E-F04',
    refs: ['I.01', 'I.03', 'J11'],
    async run(ctx) {
      const httpSrv = await startLoopbackHttpServer()
      const repo = createTempGitRepo({ name: 't1-f04-04' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        await page.getByRole('button', { name: /^(New tab|新标签页)$/i }).first().click()
        const browserItem = page.getByRole('menuitem', { name: /Browser|浏览器/i }).first()
        await browserItem.waitFor({ state: 'visible', timeout: 8000 })
        await browserItem.click()
        const addrBar = page.locator('[data-orca-browser-address-bar="true"]').first()
        await addrBar.waitFor({ state: 'visible', timeout: 10000 })
        await addrBar.fill(`${httpSrv.baseUrl}/page2`)
        await addrBar.press('Enter')
        await sleep(600)
        const hasGuest = await app.evaluate(({ webContents }, url) =>
          webContents.getAllWebContents().some((wc) => wc.getURL().startsWith(url)),
          httpSrv.baseUrl
        )
        assert.equal(hasGuest, true, 'Loopback guest webContents did not load URL')
        return { loopbackUrlLoaded: `${httpSrv.baseUrl}/page2` }
      } finally {
        await closeElectronApp(inst)
        await httpSrv.close()
        repo.cleanup()
      }
    }
  },
  {
    id: 'T1-F04-05',
    tier: 1,
    featureArea: 'E2E-F04',
    refs: ['L.03', 'L.05', 'L.06', 'G.08', 'J10'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't1-f04-05' })
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        profileOptions: { settings: { showSkillsButton: true, showAutomationsButton: true } }
      })
      const pluginFix = createSyntheticPluginFixture(ctx.porpitaRoot)
      try {
        const { app, page, homeDir } = inst
        const skill = createSyntheticSkillFixture(homeDir, 'e2e-offline-skill')
        await addLocalFolderProject(app, page, repo.repoPath)

        // 1. Verify Skills page strictly renders & filters synthetic local skill
        const skillsBtn = page.getByRole('button', { name: /^(Skills|技能)$/i }).first()
        await skillsBtn.waitFor({ state: 'visible', timeout: 10000 })
        await skillsBtn.click()
        const skillsList = page.locator('[data-skills-page-list="true"]').first()
        await skillsList.waitFor({ state: 'visible', timeout: 10000 })
        await skillsList.getByText(skill.skillName, { exact: false }).first().waitFor({ state: 'visible', timeout: 10000 })

        const searchInput = page.locator('input[placeholder*="Search skills" i], input[placeholder*="搜索" i]').first()
        await searchInput.waitFor({ state: 'visible', timeout: 5000 })
        await searchInput.fill(skill.skillName)
        await skillsList.getByText(skill.skillName, { exact: false }).first().waitFor({ state: 'visible', timeout: 5000 })
        const closeSkillsBtn = page.getByRole('button', { name: /^(Close skills|关闭技能)$/i }).first()
        await closeSkillsBtn.waitFor({ state: 'visible', timeout: 5000 })
        await closeSkillsBtn.click()
        await skillsList.waitFor({ state: 'hidden', timeout: 5000 })

        // 2. Open Settings -> Plugins, install & approve folder plugin, and verify RightSidebar panel loads cleanly
        await openSettingsPage(page)
        const pluginsNav = page.locator('aside button').filter({ hasText: /^(Plugins|插件)/i }).first()
        await pluginsNav.waitFor({ state: 'visible', timeout: 8000 })
        await pluginsNav.click()
        await installAndEnableFolderPlugin(app, page, pluginFix)
        const panelState = await openAndVerifyPluginPanel(page, pluginFix.title)
        return { skillCreated: skill.skillName, pluginTitle: pluginFix.title, panelState }
      } finally {
        await closeElectronApp(inst)
        pluginFix.cleanup()
        repo.cleanup()
      }
    }
  },
  {
    id: 'T1-F04-06',
    tier: 1,
    featureArea: 'E2E-F04',
    refs: ['N.*', 'L.01', 'L.02', 'L.03', 'J02'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't1-f04-06-repo' })
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        profileOptions: { settings: { showSkillsButton: true, showAutomationsButton: true } }
      })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)

        // 1. Verify AutomationsPage responsive layout at 1280x800, 820x580, and 600x400 (L.01, L.02)
        const automationsBtn = page.getByRole('button', { name: /^(Automations|自动化)$/i }).first()
        await automationsBtn.waitFor({ state: 'visible', timeout: 8000 })
        await automationsBtn.click()
        await page.getByRole('heading', { name: /^(Automations|自动化)$/i }).first().waitFor({ state: 'visible', timeout: 10000 })
        await assertHorizontalToolbarLayout(page, 'main', 'T1-F04-06 Automations 1280x800')
        await setViewportSize(app, page, 820, 580)
        await assertHorizontalToolbarLayout(page, 'main', 'T1-F04-06 Automations 820x580')
        await setViewportSize(app, page, 600, 400)
        const auto600 = await assertHorizontalToolbarLayout(page, 'main', 'T1-F04-06 Automations 600x400')

        // 2. Verify SkillsPage narrow 600x400 header/filter layout (L.03)
        await setViewportSize(app, page, 1280, 800)
        const skillsBtn = page.getByRole('button', { name: /^(Skills|技能)$/i }).first()
        await skillsBtn.waitFor({ state: 'visible', timeout: 8000 })
        await skillsBtn.click()
        await page.locator('[data-skills-page-list="true"]').first().waitFor({ state: 'visible', timeout: 10000 })
        await setViewportSize(app, page, 600, 400)
        await assertHorizontalToolbarLayout(page, 'header', 'T1-F04-06 Skills header 600x400')
        await assertHorizontalToolbarLayout(page, 'main', 'T1-F04-06 Skills main 600x400')
        const closeSkillsBtn = page.getByRole('button', { name: /^(Close skills|关闭技能)$/i }).first()
        await closeSkillsBtn.waitFor({ state: 'visible', timeout: 5000 })
        await closeSkillsBtn.click()
        await page.locator('[data-skills-page-list="true"]').first().waitFor({ state: 'hidden', timeout: 5000 })

        // 3. Sweep all Settings sections including repo-scoped N.repo section
        await setViewportSize(app, page, 1280, 800)
        await openSettingsPage(page)
        const navButtons = page
          .locator('aside button:visible')
          .filter({ hasNotText: /^(Back to app|返回应用)$/i })
        const count = await navButtons.count()
        assert.ok(count >= 15, `Expected >=15 visible settings targets, got ${count}`)
        const visited = []
        let repoSectionVisited = false
        for (let i = 0; i < count; i++) {
          const btn = navButtons.nth(i)
          const label = (await btn.innerText()).trim()
          await btn.click()
          await sleep(60)
          const ariaCurrent = await btn.getAttribute('aria-current')
          assert.equal(ariaCurrent, 'page', `Settings nav button ${label} did not become aria-current="page"`)
          const sec = await page
            .locator('section[data-settings-section]')
            .first()
            .getAttribute('data-settings-section')
          assert.ok(sec, `Settings section missing for nav button ${label}`)
          if (sec.startsWith('repo-')) repoSectionVisited = true
          visited.push(label || sec)
        }
        assert.equal(repoSectionVisited, true, 'Attached repository section (repo-*) missing from Settings nav')

        await setViewportSize(app, page, 600, 400)
        const narrowSectionsChecked = []
        for (const pattern of [
          /^(General|常规|通用)$/i,
          /^Git & Source Control|^Git$|源代码控制/i,
          /^(Terminal|终端)$/i,
          /t1-f04-06-repo/i
        ]) {
          const navBtn = page.locator('aside button:visible').filter({ hasText: pattern }).first()
          await navBtn.waitFor({ state: 'visible', timeout: 5000 })
          await navBtn.click()
          await sleep(150)
          const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2)
          assert.equal(overflow, false, `Settings horizontal overflow at 600x400 for ${pattern}`)
          narrowSectionsChecked.push(pattern.source)
        }
        await returnFromSettings(page)
        return {
          automations600ItemCount: auto600.itemCount,
          settingsTargetsVisited: visited.length,
          repoSectionVisited,
          narrowSectionsChecked
        }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },

  // =========================================================================
  // E2E-F05: ACS Collaboration, NativeLink & Loopback Core (6 Tests)
  // =========================================================================
  {
    id: 'T1-F05-01',
    tier: 1,
    featureArea: 'E2E-F05',
    refs: ['N.general.01', 'F04', 'F05', 'UX17'],
    timeoutMs: 360_000,
    async run(ctx) {
      const core = await startLoopbackAcsCore({ mode: 'full', agentCollabRoot: ctx.agentCollabRoot })
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        profileOptions: { locale: 'zh' }
      })
      try {
        const { app, page } = inst
        // 1. Disconnected initial state in zh: dropdown must read 尚未连接协作项目 (0 尚未连接工作区)
        const trigger = getCollaborationTrigger(page)
        await trigger.waitFor({ state: 'visible', timeout: 10000 })
        assert.equal(await trigger.getAttribute('data-collaboration-state'), 'disconnected')
        await trigger.focus()
        const dlgInitial = await openCollaborationDialog(page)
        const initialSelectText = (await dlgInitial.locator('select').first().innerText()).trim()
        const initialStatus = (await dlgInitial.locator('[role="status"]').first().innerText()).trim()
        assert.equal(/尚未连接工作区/.test(initialSelectText), false, `Found stale copy in zh dropdown: ${initialSelectText}`)
        assert.match(initialSelectText, /尚未连接协作项目/, `Expected 尚未连接协作项目 copy, got: ${initialSelectText}`)
        assert.equal(isCollaborationConnectedText(initialStatus), false, `Expected disconnected initially, got: ${initialStatus}`)
        await closeCollaborationDialogWithFocusCheck(page, dlgInitial)

        // 2. Connect via Settings -> General -> verify 600x400 narrow Settings inputs -> immediate Titlebar sync
        const generalSec = await connectCollaborationViaSettings(page, core)
        await setViewportSize(app, page, 600, 400)
        const narrowOverflowSettings = await page.evaluate(() => ({
          docOverflowX: document.documentElement.scrollWidth > window.innerWidth + 2,
          clippedInputs: [...document.querySelectorAll('section[data-settings-section="general"] input, section[data-settings-section="general"] button')]
            .map((el) => ({ r: el.getBoundingClientRect(), label: el.getAttribute('aria-label') || el.textContent?.trim() }))
            .filter(({ r }) => r.width > 0 && r.height > 0 && r.top < window.innerHeight && (r.right > window.innerWidth + 1 || r.left < -1))
            .map(({ r, label }) => ({ label, left: Math.round(r.left), right: Math.round(r.right), vw: window.innerWidth }))
        }))
        assert.equal(narrowOverflowSettings.docOverflowX, false, `Collaboration settings overflowed 600x400: ${JSON.stringify(narrowOverflowSettings)}`)
        assert.deepEqual(narrowOverflowSettings.clippedInputs, [], `Clipped Settings controls at 600x400: ${JSON.stringify(narrowOverflowSettings)}`)
        await setViewportSize(app, page, 1280, 800)
        assert.equal(await generalSec.getByText(/^(Connected|已连接)$/i).first().isVisible(), true)

        await returnFromSettings(page)
        await page.waitForFunction(
          () => document.querySelector('[data-collaboration-state]')?.getAttribute('data-collaboration-state') === 'connected',
          undefined,
          { timeout: 6000 }
        )
        const dlgConnected = await openCollaborationDialog(page)
        await page.waitForFunction(
          () => {
            const text = document.querySelector('[role="dialog"] [role="status"]')?.textContent?.trim() || ''
            return /^(Connected|已连接)$/i.test(text)
          },
          undefined,
          { timeout: 10000 }
        ).catch(() => {})
        const connectedStatus = (await dlgConnected.locator('[role="status"]').first().innerText()).trim()
        const connectedSelect = (await dlgConnected.locator('select').first().innerText()).trim()
        assert.equal(isCollaborationConnectedText(connectedStatus), true, `Expected immediate Titlebar Connected sync, got: ${connectedStatus}`)
        assert.match(connectedSelect, /Porpita/, `Expected connected project Porpita in dropdown, got: ${connectedSelect}`)
        await dlgConnected.locator('aside').getByRole('button', { name: /^slot-b$/i }).first().waitFor({ state: 'visible', timeout: 10000 })
        await closeCollaborationDialogWithFocusCheck(page, dlgConnected)

        // 3. Disconnect in Settings -> immediate Titlebar Disconnected sync without opening dialog first
        await disconnectCollaborationViaSettings(page)
        await returnFromSettings(page)
        await page.waitForFunction(
          () => document.querySelector('[data-collaboration-state]')?.getAttribute('data-collaboration-state') === 'disconnected',
          undefined,
          { timeout: 6000 }
        )
        const dlgDisconnected = await openCollaborationDialog(page)
        const disconnectedStatus = (await dlgDisconnected.locator('[role="status"]').first().innerText()).trim()
        const disconnectedSelect = (await dlgDisconnected.locator('select').first().innerText()).trim()
        assert.equal(isCollaborationConnectedText(disconnectedStatus), false, `Titlebar stayed Connected after Settings Disconnect: ${disconnectedStatus}`)
        assert.match(disconnectedSelect, /尚未连接协作项目/, `Expected 尚未连接协作项目 after Disconnect, got: ${disconnectedSelect}`)
        await closeCollaborationDialogWithFocusCheck(page, dlgDisconnected)

        // 4. Secondary Reconnect in Settings -> immediate Titlebar Connected sync + 600x400 dialog fit
        await reconnectCollaborationViaSettings(page)
        await returnFromSettings(page)
        await page.waitForFunction(
          () => document.querySelector('[data-collaboration-state]')?.getAttribute('data-collaboration-state') === 'connected',
          undefined,
          { timeout: 6000 }
        )
        const dlgReconnected = await openCollaborationDialog(page)
        const reconnectedStatus = (await dlgReconnected.locator('[role="status"]').first().innerText()).trim()
        assert.equal(isCollaborationConnectedText(reconnectedStatus), true, `Secondary Reconnect did not sync Titlebar immediately: ${reconnectedStatus}`)
        await dlgReconnected.locator('aside').getByRole('button', { name: /^slot-b$/i }).first().waitFor({ state: 'visible', timeout: 10000 })

        await setViewportSize(app, page, 600, 400)
        const dialog600 = await dlgReconnected.evaluate((el) => {
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
          `Collaboration dialog overflowed 600x400: ${JSON.stringify(dialog600)}`
        )
        await setViewportSize(app, page, 1280, 800)
        const focusAfterEsc = await closeCollaborationDialogWithFocusCheck(page, dlgReconnected)
        return {
          initialSelectText,
          connectedStatus,
          disconnectedStatus,
          reconnectedStatus,
          dialog600,
          focusAfterEsc
        }
      } finally {
        await closeElectronApp(inst)
        await core.cleanup()
      }
    }
  },
  {
    id: 'T1-F05-02',
    tier: 1,
    featureArea: 'E2E-F05',
    refs: ['K.01', 'K.02', 'UX06', 'UX09'],
    async run(ctx) {
      const core = await startLoopbackAcsCore({ mode: 'full', agentCollabRoot: ctx.agentCollabRoot })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { page } = inst
        const pid = core.info.project_id
        await connectCollaborationViaSettings(page, core)
        await returnFromSettings(page)

        // 1. Send 2 opaque messages through the real Electron composer UI
        const dlg = await openCollaborationDialog(page)
        const composer = await selectCollaborationContact(dlg, 'slot-b')
        const sendBtn = dlg.getByRole('button', { name: /^(Send|发送)$/i }).first()

        await composer.fill('Opaque UI msg #1 needle-alpha')
        await sendBtn.click()
        await dlg.locator('article').getByText('Opaque UI msg #1 needle-alpha', { exact: false }).first().waitFor({ state: 'visible', timeout: 10000 })
        await page.waitForFunction(
          () => (document.querySelector('[role="dialog"] textarea')?.value ?? '') === '',
          undefined,
          { timeout: 10000 }
        )

        await composer.fill('Opaque UI msg #2 needle-alpha')
        await sendBtn.click()
        await dlg.locator('article').getByText('Opaque UI msg #2 needle-alpha', { exact: false }).first().waitFor({ state: 'visible', timeout: 10000 })
        await page.waitForFunction(
          () => (document.querySelector('[role="dialog"] textarea')?.value ?? '') === '',
          undefined,
          { timeout: 10000 }
        )

        // Verify DeliverySummary appears on sent UI messages
        await dlg.getByText(/Delivered to inbox|Queued by the service|Native input|Waiting for native input|已投递|已入队/i).first().waitFor({ state: 'visible', timeout: 10000 })

        // 2. Peer B explicit reply referencing UI message #1 -> verifies reply link + Reply received in UI
        const listRes = await core.request('GET', `/projects/${pid}/messages?with=${encodeURIComponent(core.addresses.peer_b)}&limit=10`, {
          token: core.tokens.client
        })
        assert.equal(listRes.status, 200)
        const msg1 = listRes.json.items.find((m) => (typeof m.content === 'string' ? m.content : m.content?.text)?.includes('Opaque UI msg #1'))
        assert.ok(msg1?.message_handle, 'UI sent message #1 missing from server')
        const reply = await core.peerSend({
          actor: 'peer_b',
          to: core.addresses.client,
          content: 'Explicit peer reply needle-alpha',
          reply_to: [msg1.message_handle]
        })
        assert.ok(reply.message?.message_handle, 'Peer reply handle missing')

        await dlg.locator('article').getByText('Explicit peer reply needle-alpha', { exact: false }).first().waitFor({ state: 'visible', timeout: 25000 })
        await dlg.getByText(/Reply linked to the original message|回复已关联原消息/i).first().waitFor({ state: 'visible', timeout: 8000 })

        // 3. Real UI Search -> hit list -> click hit back to conversation
        const searchInput = dlg.getByRole('textbox', { name: /Search messages|搜索消息/i }).first()
        await searchInput.fill('needle-alpha')
        await searchInput.press('Enter')
        const hitBtn = dlg.locator('main button').filter({ hasText: /needle-alpha/i }).first()
        await hitBtn.waitFor({ state: 'visible', timeout: 10000 })
        await hitBtn.click()
        await dlg.locator('textarea').first().waitFor({ state: 'visible', timeout: 8000 })

        // 4. Verify cursor pagination limit=2 on loopback Core
        const page1 = await core.request('GET', `/projects/${pid}/messages?with=${encodeURIComponent(core.addresses.peer_b)}&limit=2`, {
          token: core.tokens.client
        })
        assert.equal(page1.status, 200)
        assert.equal(page1.json.items.length, 2)
        assert.ok(page1.json.page.next_cursor, 'Expected next_cursor for pagination')
        const page2 = await core.request(
          'GET',
          `/projects/${pid}/messages?with=${encodeURIComponent(core.addresses.peer_b)}&limit=2&cursor=${encodeURIComponent(page1.json.page.next_cursor)}`,
          { token: core.tokens.client }
        )
        assert.equal(page2.status, 200)
        assert.ok(page2.json.items.length >= 1)
        await closeCollaborationDialogWithFocusCheck(page, dlg)
        return { uiSentVerified: true, uiSearchHitVerified: true, paginatedCount: page1.json.items.length + page2.json.items.length }
      } finally {
        await closeElectronApp(inst)
        await core.cleanup()
      }
    }
  },
  {
    id: 'T1-F05-03',
    tier: 1,
    featureArea: 'E2E-F05',
    refs: ['K.03', 'UX11', 'communication-contract-adoption'],
    async run(ctx) {
      const core = await startLoopbackAcsCore({ mode: 'full', agentCollabRoot: ctx.agentCollabRoot })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { page } = inst
        const pid = core.info.project_id
        const conv = await core.request(
          'GET',
          `/projects/${pid}/conversations/resolve?with=${encodeURIComponent(core.addresses.peer_b)}`,
          { token: core.tokens.client }
        )
        assert.equal(conv.status, 200, conv.text)
        const cid = conv.json.conversation_id

        await connectCollaborationViaSettings(page, core)
        await returnFromSettings(page)

        // 1. Type draft in Electron UI -> wait for debounced server PUT /draft persistence
        const dlg = await openCollaborationDialog(page)
        const composer = await selectCollaborationContact(dlg, 'slot-b')
        await composer.fill('Viewer A UI private draft text')

        let savedDraft = null
        const deadline = Date.now() + 10000
        while (Date.now() < deadline) {
          const d = await core.request('GET', `/projects/${pid}/conversations/${cid}/draft`, {
            token: core.tokens.client
          })
          if (d.status === 200 && d.json.revision >= 1 && d.json.content === 'Viewer A UI private draft text') {
            savedDraft = d.json
            break
          }
          await sleep(250)
        }
        assert.ok(savedDraft, 'Debounced UI draft did not persist to loopback Core')
        assert.ok(savedDraft.updated_at, 'Persisted UI draft must have aware updated_at')

        // 2. Toggle Mute & Archive via UI buttons -> verify server preferences updated
        await dlg.getByRole('button', { name: /Toggle mute|静音/i }).first().click()
        await dlg.getByRole('button', { name: /Toggle archive|归档/i }).first().click()
        let prefsSaved = null
        const prefDeadline = Date.now() + 8000
        while (Date.now() < prefDeadline) {
          const p = await core.request('GET', `/projects/${pid}/conversations/${cid}/preferences`, {
            token: core.tokens.client
          })
          if (p.status === 200 && p.json.muted === true && p.json.archived === true) {
            prefsSaved = p.json
            break
          }
          await sleep(200)
        }
        assert.ok(prefsSaved, 'UI Mute/Archive preference toggles did not persist to server')

        // 3. Reopen Collaboration dialog -> UI restores saved server draft
        await closeCollaborationDialogWithFocusCheck(page, dlg)
        const dlgReopen = await openCollaborationDialog(page)
        const composerReopen = await selectCollaborationContact(dlgReopen, 'slot-b')
        assert.equal(await composerReopen.inputValue(), 'Viewer A UI private draft text')
        await closeCollaborationDialogWithFocusCheck(page, dlgReopen)

        // 4. Send seed message so peer_b sees pair, then verify peer_b draft remains isolated (rev 0)
        const seedMsg = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'draft-pair-seed-1' },
          body: { to: core.addresses.peer_b, content: 'Pair visibility seed', activation: 'message_only' }
        })
        assert.equal(seedMsg.status, 201, seedMsg.text)

        const bConv = await core.request(
          'GET',
          `/projects/${pid}/conversations/resolve?with=${encodeURIComponent(core.addresses.client)}`,
          { token: core.tokens.peer_b }
        )
        assert.equal(bConv.status, 200, bConv.text)
        const bDraft = await core.request(
          'GET',
          `/projects/${pid}/conversations/${bConv.json.conversation_id}/draft`,
          { token: core.tokens.peer_b }
        )
        assert.equal(bDraft.status, 200)
        assert.equal(bDraft.json.revision, 0)
        assert.equal(bDraft.json.updated_at, null)
        return { viewerADraftRev: savedDraft.revision, viewerBDraftRev: bDraft.json.revision, muted: prefsSaved.muted, archived: prefsSaved.archived }
      } finally {
        await closeElectronApp(inst)
        await core.cleanup()
      }
    }
  },
  {
    id: 'T1-F05-04',
    tier: 1,
    featureArea: 'E2E-F05',
    refs: ['K.04', 'UX10', 'C.10.08', 'communication-contract-adoption'],
    async run(ctx) {
      const core = await startLoopbackAcsCore({ mode: 'full', agentCollabRoot: ctx.agentCollabRoot })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { page } = inst
        const pid = core.info.project_id
        const fix = core.nativeLinkFixture
        // 1. Bind NativeLink + verify 12-field contract & include_native_source=true
        const bind = await core.request('PUT', `/projects/${pid}/native-links/link-e2e-1`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'bind-link-1' },
          body: fix
        })
        assert.equal(bind.status, 200, bind.text)
        assert.equal(Object.keys(bind.json).length, 12, 'NativeLink must return 12 fields')
        assert.equal(bind.json.host_ref, fix.expected_host_ref)

        const send = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'invoke-source-1' },
          body: { to: core.addresses.peer_b, content: 'Inspect native source turn', activation: 'invoke' }
        })
        assert.equal(send.status, 201, send.text)
        const plainSend = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'plain-source-1' },
          body: { to: core.addresses.peer_b, content: 'Plain inbox only turn', activation: 'message_only' }
        })
        assert.equal(plainSend.status, 201, plainSend.text)
        await core.dispatchPending()

        const read = await core.request(
          'GET',
          `/projects/${pid}/messages/${encodeURIComponent(send.json.message.message_handle)}?include_native_source=true`,
          { token: core.tokens.client }
        )
        assert.equal(read.status, 200, read.text)
        assert.equal(read.json.native_source?.available, true, `Expected available=true: ${read.text}`)
        assert.equal(read.json.native_source.value.operationId, send.json.operation_ref)

        // 2. Verify CommunicationMessage <details> + CommunicationSource ("View execution") in Electron UI
        await connectCollaborationViaSettings(page, core)
        await returnFromSettings(page)
        const dlg = await openCollaborationDialog(page)
        await selectCollaborationContact(dlg, 'slot-b')

        const invokeArticle = dlg.locator('article').filter({ hasText: 'Inspect native source turn' }).first()
        await invokeArticle.waitFor({ state: 'visible', timeout: 10000 })
        await invokeArticle.locator('details summary').first().click()
        await invokeArticle.getByText(/Native input|原生输入/i).first().waitFor({ state: 'visible', timeout: 5000 })
        await invokeArticle.getByText(/^accepted$/i).first().waitFor({ state: 'visible', timeout: 5000 })

        const viewExecBtn = invokeArticle.getByRole('button', { name: /View execution|查看执行/i }).first()
        await viewExecBtn.waitFor({ state: 'visible', timeout: 5000 })
        await viewExecBtn.click()
        await invokeArticle.locator('[role="status"]').filter({ hasText: /unavailable|不可用/i }).first().waitFor({ state: 'visible', timeout: 5000 })

        const plainArticle = dlg.locator('article').filter({ hasText: 'Plain inbox only turn' }).first()
        await plainArticle.waitFor({ state: 'visible', timeout: 8000 })
        await plainArticle.locator('details summary').first().click()
        await plainArticle.getByText(/^not_requested$/i).first().waitFor({ state: 'visible', timeout: 5000 })
        assert.equal(
          await plainArticle.getByRole('button', { name: /View execution|查看执行/i }).count(),
          0,
          'message_only turn must not render View execution button'
        )
        await closeCollaborationDialogWithFocusCheck(page, dlg)
        return {
          nativeLinkRevision: bind.json.revision,
          sourceProvider: read.json.native_source.value.nativeSession.providerRef,
          uiSourceInspected: true
        }
      } finally {
        await closeElectronApp(inst)
        await core.cleanup()
      }
    }
  },
  {
    id: 'T1-F05-05',
    tier: 1,
    featureArea: 'E2E-F05',
    refs: ['K.03', 'K.04', 'T04', 'communication-api-scope'],
    async run(ctx) {
      const core = await startLoopbackAcsCore({ mode: 'full', agentCollabRoot: ctx.agentCollabRoot })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { page } = inst
        const pid = core.info.project_id
        // 1. Verify /snapshot + /events SSE protocol & notice seen CAS
        const snap = await core.request('GET', `/projects/${pid}/snapshot?limit=10`, {
          token: core.tokens.client
        })
        assert.equal(snap.status, 200, snap.text)
        const afterCursor = snap.json.after_cursor
        assert.ok(afterCursor, 'Snapshot missing after_cursor')

        const controller = new AbortController()
        const ssePromise = (async () => {
          const res = await fetch(
            `${core.apiUrl}/projects/${pid}/events?after_cursor=${encodeURIComponent(afterCursor)}`,
            {
              headers: { Authorization: `Bearer ${core.tokens.client}` },
              signal: controller.signal
            }
          )
          assert.equal(res.status, 200, `SSE failed: ${res.status}`)
          const reader = res.body.getReader()
          const decoder = new TextDecoder()
          let buf = ''
          while (true) {
            const { value, done } = await reader.read()
            if (done) break
            buf += decoder.decode(value, { stream: true })
            if (buf.includes('message.committed') || buf.includes('event:')) {
              return buf
            }
          }
          return buf
        })()

        await sleep(200)
        await core.peerSend({ actor: 'peer_b', to: core.addresses.client, content: 'SSE live frame' })
        const sseFrame = await Promise.race([
          ssePromise,
          sleep(6000).then(() => {
            controller.abort()
            throw new Error('SSE stream timed out waiting for event')
          })
        ])
        controller.abort()
        assert.match(sseFrame, /event:\s*\S+/, `Unexpected SSE output: ${sseFrame}`)

        const noticeInfo = await core.emitNotice({ legacy_null_created_at: false })
        const notices = await core.request('GET', `/projects/${pid}/notices`, {
          token: core.tokens.client
        })
        assert.equal(notices.status, 200)
        const nItem = notices.json.items.find((n) => n.notice_handle === noticeInfo.notice_handle)
        assert.ok(nItem, 'Emitted notice not returned by GET /notices')
        const seenRes = await core.request(
          'PUT',
          `/projects/${pid}/notices/${encodeURIComponent(nItem.notice_handle)}/seen`,
          {
            token: core.tokens.client,
            headers: {
              'Idempotency-Key': 'notice-seen-1',
              'If-Match': `"${nItem.revision}"`
            },
            body: { seen: true }
          }
        )
        assert.equal(seenRes.status, 200, seenRes.text)
        assert.equal(seenRes.json.seen, true)

        // 2. Connect Electron -> return to Titlebar -> verify live SSE unread indicator, Notice strip dismiss, & Mark Read/Unread
        await connectCollaborationViaSettings(page, core)
        await returnFromSettings(page)
        const trigger = getCollaborationTrigger(page)
        const waitForCollabAttrs = async (predicate, timeout, label) => {
          try {
            await page.waitForFunction(predicate, undefined, { timeout })
          } catch (err) {
            const diag = await page
              .evaluate(() => {
                const el = document.querySelector('[data-collaboration-state]')
                return el
                  ? {
                      state: el.getAttribute('data-collaboration-state'),
                      unread: el.getAttribute('data-collaboration-unread'),
                      notices: el.getAttribute('data-collaboration-notices'),
                      ariaLabel: el.getAttribute('aria-label'),
                      ariaDescription: el.getAttribute('aria-description'),
                      title: el.getAttribute('title')
                    }
                  : null
              })
              .catch(() => null)
            const errs = await core.adminGet('/__e2e/errors').catch(() => null)
            const collabStatus = await page
              .evaluate(() => window.api.runtime.call({ method: 'collaboration.status' }))
              .catch((e) => ({ evalErr: String(e) }))
            throw new Error(
              `${label}: ${err.message} | dom=${JSON.stringify(diag)} | collabStatus=${JSON.stringify(collabStatus)} | serverErrs=${JSON.stringify(errs)}`,
              { cause: err }
            )
          }
        }
        await page.locator('[data-collaboration-state="connected"]').first().waitFor({ state: 'visible', timeout: 15000 })
        await waitForCollabAttrs(
          () => {
            const el = document.querySelector('[data-collaboration-state="connected"]')
            return Boolean(el) && Number(el.getAttribute('data-collaboration-unread') || 0) >= 1
          },
          25000,
          'Initial SSE snapshot unread >= 1'
        )
        await sleep(500)
        await core.emitNotice({ legacy_null_created_at: false })
        await core.peerSend({ actor: 'peer_b', to: core.addresses.client, content: 'SSE UI live unread ping' })
        await waitForCollabAttrs(
          () => {
            const el = document.querySelector('[data-collaboration-unread]')
            return (
              Number(el?.getAttribute('data-collaboration-unread') || 0) >= 2 &&
              Number(el?.getAttribute('data-collaboration-notices') || 0) >= 1
            )
          },
          25000,
          'Live SSE unread >= 2 && notices >= 1'
        )
        await trigger.locator('span').first().waitFor({ state: 'visible', timeout: 5000 })

        const dlg = await openCollaborationDialog(page)
        const dismissBtn = dlg.locator('[role="status"] button').first()
        await dismissBtn.waitFor({ state: 'visible', timeout: 6000 })
        await dismissBtn.click()
        await dismissBtn.waitFor({ state: 'hidden', timeout: 6000 })

        await selectCollaborationContact(dlg, 'slot-b')
        await dlg.getByText('SSE UI live unread ping', { exact: false }).first().waitFor({ state: 'visible', timeout: 8000 })
        await core.peerSend({ actor: 'peer_b', to: core.addresses.client, content: 'SSE live dialog push' })
        await dlg.getByText('SSE live dialog push', { exact: false }).first().waitFor({ state: 'visible', timeout: 10000 })
        await dlg.getByRole('button', { name: /Mark as read|标为已读|标记为已读/i }).first().click()
        const markUnreadBtn = dlg.getByRole('button', { name: /Mark as unread|标为未读|标记为未读/i }).first()
        await markUnreadBtn.click()
        await page.waitForFunction(
          () => Boolean(document.querySelector('[role="dialog"] button[aria-pressed="true"]')),
          undefined,
          { timeout: 15000 }
        )
        await closeCollaborationDialogWithFocusCheck(page, dlg)
        return { sseDelivered: true, noticeSeen: seenRes.json.seen, uiLiveUnreadDotSynced: true }
      } finally {
        await closeElectronApp(inst)
        await core.cleanup()
      }
    }
  },
  {
    id: 'T1-F05-06',
    tier: 1,
    featureArea: 'E2E-F05',
    refs: ['K.03', 'UX12', 'communication-api-scope'],
    async run(ctx) {
      const core = await startLoopbackAcsCore({ mode: 'full', agentCollabRoot: ctx.agentCollabRoot })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      const attTmpDir = mkdtempSync(path.join(os.tmpdir(), 'porpita-e2e-att-'))
      try {
        const { page } = inst
        const pid = core.info.project_id
        const payloadBytes = Buffer.from('Porpita attachment binary test payload\n', 'utf8')
        const digestHex = createHash('sha256').update(payloadBytes).digest('hex')
        const attPath = path.join(attTmpDir, 'report.txt')
        writeFileSync(attPath, payloadBytes)

        // 1. Connect Electron UI & send real attachment through CommunicationComposer + downloadAttachment verification
        await connectCollaborationViaSettings(page, core)
        await returnFromSettings(page)
        const dlg = await openCollaborationDialog(page)
        const composer = await selectCollaborationContact(dlg, 'slot-b')

        await dlg.locator('input[type="file"]').first().setInputFiles(attPath)
        await dlg.getByText('report.txt', { exact: true }).first().waitFor({ state: 'visible', timeout: 10000 })
        await composer.fill('Message with UI attachment')
        await dlg.getByRole('button', { name: /^(Send|发送)$/i }).first().click()

        const msgArticle = dlg.locator('article').filter({ hasText: 'Message with UI attachment' }).first()
        await msgArticle.waitFor({ state: 'visible', timeout: 10000 })
        const dlBtn = msgArticle.getByRole('button', { name: /report\.txt/i }).first()
        await dlBtn.waitFor({ state: 'visible', timeout: 8000 })
        await dlBtn.click()
        await msgArticle.getByRole('button', { name: /Show saved file in folder|在文件夹中显示|显示已保存文件/i }).first().waitFor({ state: 'visible', timeout: 10000 })
        await closeCollaborationDialogWithFocusCheck(page, dlg)

        // 2. Confirm Peer B downloads exact SHA-256 bytes from loopback Core
        const msgList = await core.request('GET', `/projects/${pid}/messages?with=${encodeURIComponent(core.addresses.peer_b)}&limit=10`, {
          token: core.tokens.client
        })
        assert.equal(msgList.status, 200)
        const attMsg = msgList.json.items.find((m) => m.attachment_refs?.length > 0)
        assert.ok(attMsg, 'Sent attachment message missing attachment_refs on Core')
        const attId = attMsg.attachment_refs[0].attachment_id

        const dlRes = await fetch(`${core.apiUrl}/projects/${pid}/attachments/${attId}/content`, {
          headers: { Authorization: `Bearer ${core.tokens.peer_b}` }
        })
        assert.equal(dlRes.status, 200)
        const dlBuf = Buffer.from(await dlRes.arrayBuffer())
        const dlDigest = createHash('sha256').update(dlBuf).digest('hex')
        assert.equal(dlDigest, digestHex, 'Downloaded attachment SHA-256 mismatch')
        return { attachmentId: attId, sha256: dlDigest, uiRoundTripVerified: true }
      } finally {
        await closeElectronApp(inst)
        await core.cleanup()
        rmSync(attTmpDir, { recursive: true, force: true })
      }
    }
  },

  // =========================================================================
  // E2E-F06: UI SPEC Audit, Crosswalk & Honest Boundaries (6 Tests)
  // =========================================================================
  {
    id: 'T1-F06-01',
    tier: 1,
    featureArea: 'E2E-F06',
    refs: ['ORIGINAL_REQUEST:R1', 'build_coverage.py'],
    async run(ctx) {
      const linkCheck = checkMarkdownLinks({
        specRoot: ctx.specRoot,
        orcaFirstPath: path.join(path.dirname(ctx.specRoot), 'ORCA-FIRST.zh-CN.md')
      })
      assert.equal(
        linkCheck.brokenCount,
        0,
        `Broken markdown links: ${JSON.stringify(linkCheck.broken)}`
      )

      const staged = runStagedBuildCoverage({
        specRoot: ctx.specRoot,
        porpitaRoot: ctx.porpitaRoot,
        historyRoot: ctx.historyRoot,
        agentCollabRoot: ctx.agentCollabRoot
      })
      assert.equal(staged.sourceIndexExitCode, 0, `source-index failed: ${staged.sourceIndexStderr}`)
      if (staged.buildCoverageExitCode !== 0) {
        if (ctx.mode === 'smoke') {
          pendingIfSmoke(
            ctx.mode,
            'M4',
            'Staged build_coverage.py exits 0 after catalog sync with M1-M3 changes',
            `build_coverage.py exit=${staged.buildCoverageExitCode}: ${staged.buildCoverageStderr.slice(0, 300)}`
          )
        }
        assert.fail(`build_coverage.py failed: ${staged.buildCoverageStderr}`)
      }
      assert.equal(staged.stdoutJson.domains, 20)
      assert.ok(staged.stdoutJson.rows >= 371)
      return {
        linksChecked: linkCheck.checkedFilesCount,
        domains: staged.stdoutJson.domains,
        rows: staged.stdoutJson.rows
      }
    }
  },
  {
    id: 'T1-F06-02',
    tier: 1,
    featureArea: 'E2E-F06',
    refs: ['ORIGINAL_REQUEST:R1', 'build_coverage.py'],
    async run(ctx) {
      const staged = runStagedBuildCoverage({
        specRoot: ctx.specRoot,
        porpitaRoot: ctx.porpitaRoot,
        historyRoot: ctx.historyRoot,
        agentCollabRoot: ctx.agentCollabRoot
      })
      assert.equal(staged.sourceIndexExitCode, 0, staged.sourceIndexStderr)
      const reg = staged.summary.registry
      assert.ok(reg.setting.length >= 34, `Expected >=34 settings renderers in summary, got ${reg.setting.length}`)
      assert.ok(reg.activeView.length >= 9, `Expected >=9 activeViews, got ${reg.activeView.length}`)
      if (staged.buildCoverageExitCode !== 0) {
        pendingIfSmoke(
          ctx.mode,
          'M4',
          'source-index & coverage-audit.json 100% registry parity',
          staged.buildCoverageStderr.slice(0, 300)
        )
      }
      assert.ok(staged.audit.settings_targets >= 37, `Expected >=37 settings_targets, got ${staged.audit.settings_targets}`)
      assert.ok(staged.audit.top_level_views >= 9)
      assert.ok(staged.audit.root_boundaries >= 37)
      assert.ok(staged.audit.primitive_wrappers >= 32)
      return {
        settingsRenderers: reg.setting.length,
        settingsTargets: staged.audit.settings_targets,
        topLevelViews: staged.audit.top_level_views,
        rootBoundaries: staged.audit.root_boundaries,
        primitiveWrappers: staged.audit.primitive_wrappers
      }
    }
  },
  {
    id: 'T1-F06-03',
    tier: 1,
    featureArea: 'E2E-F06',
    refs: ['ORIGINAL_REQUEST:R2', 'ORCA-FIRST'],
    async run(ctx) {
      const orcaFirstPath = path.join(path.dirname(ctx.specRoot), 'ORCA-FIRST.zh-CN.md')
      const cw = checkOrcaFirstCrosswalk({ orcaFirstPath, specRoot: ctx.specRoot })
      assert.equal(cw.foundTIds.length, 12, `Expected T01-T12, found ${cw.foundTIds.join(',')}`)
      assert.equal(cw.missingArchives.length, 0, `Missing ORCA-FIRST archives: ${cw.missingArchives.join(',')}`)
      if (!cw.referencedOrcaFirst || cw.untracedTs.length > 0) {
        pendingIfSmoke(
          ctx.mode,
          'M4',
          'ORCA-FIRST.zh-CN.md (T01-T12) explicitly cross-referenced in porpita-ui-spec',
          `referenced=${cw.referencedOrcaFirst}, untraced=${cw.untracedTs.join(',')}`
        )
      }
      return cw
    }
  },
  {
    id: 'T1-F06-04',
    tier: 1,
    featureArea: 'E2E-F06',
    refs: ['ORIGINAL_REQUEST:R2', 'UI_SPEC_BRIEF'],
    async run(ctx) {
      const cw = checkReferenceCrosswalk({ refRoot: ctx.refRoot, specRoot: ctx.specRoot })
      assert.equal(cw.deliverablesCount, 11)
      assert.equal(cw.openQuestionsCount, 12)
      if (cw.missingDeliverablesInRef.length > 0 || !cw.hasExplicitOpenCrosswalk) {
        pendingIfSmoke(
          ctx.mode,
          'M4',
          '11 Reference deliverables & Open Questions #1-#12 mapped in porpita-ui-spec',
          `missingDeliverables=${cw.missingDeliverablesInRef.join(',')}, openCrosswalk=${cw.hasExplicitOpenCrosswalk}`
        )
      }
      return cw
    }
  },
  {
    id: 'T1-F06-05',
    tier: 1,
    featureArea: 'E2E-F06',
    refs: ['ORIGINAL_REQUEST:R3', 'COVERAGE_CLOSURE.md'],
    async run(ctx) {
      const res = checkEnvBoundedHonesty({ specRoot: ctx.specRoot })
      assert.equal(
        res.uncoveredCategories.length,
        0,
        `ENV_BOUNDED categories missing from COVERAGE_CLOSURE.md: ${res.uncoveredCategories.join(',')}`
      )
      assert.equal(
        res.dishonestFindings.length,
        0,
        `Dishonest closure claims detected: ${res.dishonestFindings.join('; ')}`
      )
      return res
    }
  },
  {
    id: 'T1-F06-06',
    tier: 1,
    featureArea: 'E2E-F06',
    refs: ['ORIGINAL_REQUEST:R3', 'PROJECT'],
    async run(ctx) {
      const gitCheck = verifyGitBaselines({
        agentCollabRoot: ctx.agentCollabRoot,
        historyRoot: ctx.historyRoot
      })
      assert.equal(gitCheck.ok, true, `Git baseline drift: ${gitCheck.issues.join(' | ')}`)
      return {
        agentCollabHead: gitCheck.agentCollab.head,
        trackedModsCount: gitCheck.agentCollab.trackedModsCount,
        porpitaHead: gitCheck.porpita.head,
        porpitaDeletions: gitCheck.porpita.deletionsCount
      }
    }
  }
]
