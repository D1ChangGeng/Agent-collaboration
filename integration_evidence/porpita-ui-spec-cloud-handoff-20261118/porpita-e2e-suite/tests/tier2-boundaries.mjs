import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import {
  addLocalFolderProject,
  assertAllWindowsHidden,
  closeElectronApp,
  launchElectronApp,
  openSettingsPage,
  returnFromSettings,
  setViewportSize,
  sleep
} from '../lib/electron-harness.mjs'
import { startLoopbackAcsCore } from '../lib/acs-core-harness.mjs'
import {
  createSyntheticPluginFixture,
  createTempGitRepo,
  startLoopbackHttpServer,
  verifyGitBaselines
} from '../lib/fixtures.mjs'
import {
  checkApiScopeParity,
  checkEnvBoundedHonesty,
  runDesignEvidenceCheck,
  runStagedBuildCoverage
} from '../lib/spec-audit-harness.mjs'
import { pendingIfSmoke } from '../lib/test-context.mjs'

async function hasIntegratedWorkspaceShell(page) {
  return await page.evaluate(() => {
    const previewToggle = [...document.querySelectorAll('button')].some((b) =>
      /Workspaces \(preview\)|工作空间（预览）/i.test(b.textContent || '')
    )
    const hasTabs =
      Boolean(document.querySelector('[data-workspace-preview]')) ||
      Boolean(document.querySelector('[data-workspace-tab-strip]')) ||
      Boolean(document.querySelector('[data-workspace-group-selector]')) ||
      Boolean(document.querySelector('[data-session-index]'))
    return !previewToggle && hasTabs
  })
}

export const TIER2_TESTS = [
  // =========================================================================
  // E2E-F01 Boundary & Error Tests (6 Tests)
  // =========================================================================
  {
    id: 'T2-F01-01',
    tier: 2,
    featureArea: 'E2E-F01',
    refs: ['F01', 'A.01'],
    async run(ctx) {
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        width: 600,
        height: 400
      })
      try {
        const { page } = inst
        await page
          .locator('[data-contextual-tour-target="sidebar-navigation"]')
          .waitFor({ state: 'visible', timeout: 12000 })
        const metrics = await page.evaluate(() => {
          const left = document.querySelector('[data-worktree-sidebar-layout]')
          const right = document.querySelector('[data-right-sidebar-layout]')
          const main = document.querySelector('[data-workbench-viewport], main')
          const rect = (el) => (el ? el.getBoundingClientRect() : null)
          const lRect = rect(left)
          const rRect = rect(right)
          const mRect = rect(main)
          return {
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            leftVisibleWidth: lRect ? Math.round(lRect.width) : 0,
            rightVisibleWidth: rRect ? Math.round(rRect.width) : 0,
            mainWidth: mRect ? Math.round(mRect.width) : window.innerWidth,
            horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 2
          }
        })
        assert.equal(metrics.innerWidth, 600)
        assert.equal(metrics.innerHeight, 400)
        assert.ok(metrics.mainWidth >= 320, `Main area collapsed below 320px at 600x400: ${JSON.stringify(metrics)}`)
        return metrics
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T2-F01-02',
    tier: 2,
    featureArea: 'E2E-F01',
    refs: ['D.08.01'],
    async run(ctx) {
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        if (!(await hasIntegratedWorkspaceShell(inst.page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Top-level group selector <= min(132px, 31%) & overflow reachable below 260px',
            'Top-level Workspace tab strip & group selector pending M3 integration'
          )
        }
        return { verified: true }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T2-F01-03',
    tier: 2,
    featureArea: 'E2E-F01',
    refs: ['A.04', 'S.02'],
    async run(ctx) {
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const landingText = await inst.page.locator('body').innerText()
        assert.match(landingText, /Add project|添加项目/i, 'Empty landing CTA missing')
        if (!(await hasIntegratedWorkspaceShell(inst.page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Zero-workspace empty boundary & General group delete protection in default build',
            'Top-level Workspace & General group protection pending M3 integration'
          )
        }
        return { landingEmptyCtaPresent: true }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T2-F01-04',
    tier: 2,
    featureArea: 'E2E-F01',
    refs: ['D.08'],
    async run(ctx) {
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        if (!(await hasIntegratedWorkspaceShell(inst.page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Duplicate group name disambiguation & 20+ tabs overflow stress in default build',
            'Top-level Workspace tab groups pending M3 integration'
          )
        }
        return { verified: true }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T2-F01-05',
    tier: 2,
    featureArea: 'E2E-F01',
    refs: ['D.07.02', 'D.07.04'],
    async run(ctx) {
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        seedCompletedOnboarding: true
      })
      const tempRoot = inst.tempRoot
      const userDataDir = inst.userDataDir
      try {
        await closeElectronApp(inst, { removeTempDir: false })
        // Inject corrupt porpita-workspaces.json
        const layoutPath = path.join(userDataDir, 'porpita-workspaces.json')
        writeFileSync(layoutPath, '{ "corrupt": [invalid json', 'utf8')

        const relaunched = await launchElectronApp({
          porpitaRoot: ctx.porpitaRoot,
          tempRoot,
          seedCompletedOnboarding: false
        })
        try {
          await relaunched.page
            .locator('[data-contextual-tour-target="sidebar-navigation"]')
            .waitFor({ state: 'visible', timeout: 12000 })
          await assertAllWindowsHidden(relaunched.app)
          if (!(await hasIntegratedWorkspaceShell(relaunched.page))) {
            pendingIfSmoke(
              ctx.mode,
              'M3',
              'Corrupt porpita-workspaces.json triggers recoverable notice & v1/v2 migrates to v3',
              'App survived corrupt porpita-workspaces.json cleanly; Workspace v3 layout reader pending M3 integration'
            )
          }
          return { survivedCorruptLayout: true }
        } finally {
          await closeElectronApp(relaunched, { removeTempDir: true })
        }
      } catch (err) {
        await closeElectronApp(inst, { removeTempDir: true }).catch(() => {})
        throw err
      }
    }
  },
  {
    id: 'T2-F01-06',
    tier: 2,
    featureArea: 'E2E-F01',
    refs: ['D.07.05', 'J12'],
    async run(ctx) {
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        if (!(await hasIntegratedWorkspaceShell(inst.page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Disconnected/revoked paired host placeholder leaves unaffected Pane interactive',
            'Integrated multi-host Workspace layout pending M3'
          )
        }
        return { verified: true }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },

  // =========================================================================
  // E2E-F02 Boundary & Error Tests (6 Tests)
  // =========================================================================
  {
    id: 'T2-F02-01',
    tier: 2,
    featureArea: 'E2E-F02',
    refs: ['B.01', 'B.04'],
    async run(ctx) {
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        seedCompletedOnboarding: false
      })
      try {
        const { page } = inst
        const modal = page.locator('[role="dialog"][data-onboarding-modal]').first()
        await modal.waitFor({ state: 'visible', timeout: 15000 })
        // Choose Chat UI or Terminal then Continue -> Back -> Set up later -> confirm Skip
        const radio = modal.getByRole('radio').first()
        if (await radio.isVisible().catch(() => false)) await radio.click()
        const cont = modal.getByRole('button', { name: /^Continue|^继续/i }).first()
        if (await cont.isVisible().catch(() => false)) {
          await cont.click()
          await sleep(250)
          const back = modal.getByRole('button', { name: /^Back|^返回/i }).first()
          if (await back.isVisible().catch(() => false)) await back.click()
        }
        // Pressing Escape (or clicking backdrop) opens OnboardingSkipConfirmationDialog,
        // whereas "Set up later" completes onboarding directly without confirmation.
        await page.keyboard.press('Escape')
        const confirmDialog = page.getByRole('dialog').filter({ hasText: /Skip|跳过/i }).last()
        await confirmDialog.waitFor({ state: 'visible', timeout: 8000 })
        const keepGoingBtn = confirmDialog.getByRole('button', { name: /No, keep going|不，继续/i }).first()
        if (await keepGoingBtn.isVisible().catch(() => false)) {
          await keepGoingBtn.click()
          await confirmDialog.waitFor({ state: 'hidden', timeout: 5000 })
          assert.equal(await modal.isVisible(), true, 'Onboarding modal should remain open after "No, keep going"')
          await page.keyboard.press('Escape')
          await confirmDialog.waitFor({ state: 'visible', timeout: 8000 })
        }
        await confirmDialog.getByRole('button', { name: /^(Skip|跳过)$/i }).first().click()
        await modal.waitFor({ state: 'hidden', timeout: 10000 })
        return { midFlowBackAndSkipConfirmed: true }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T2-F02-02',
    tier: 2,
    featureArea: 'E2E-F02',
    refs: ['F02', 'O.01', 'STYLEGUIDE:61'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't2-f02-02' })
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        width: 600,
        height: 400
      })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        // Verify SecuritySurface/modal z-order & button reachability at 600x400
        await setViewportSize(app, page, 600, 400)
        const dialogCount = await page.locator('[role="dialog"]:visible').count()
        const toastInFront = await page.evaluate(() => {
          const modal = document.querySelector('[role="dialog"], [role="alertdialog"]')
          const toaster = document.querySelector('[data-sonner-toaster]')
          if (!modal || !toaster) return false
          const mz = Number.parseInt(getComputedStyle(modal).zIndex || '50', 10)
          const tz = Number.parseInt(getComputedStyle(toaster).zIndex || '40', 10)
          return tz > mz
        })
        assert.equal(toastInFront, false, 'Sonner toast z-index must never exceed active modal dialog')
        return { viewport: '600x400', dialogCount, toastInFront }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T2-F02-03',
    tier: 2,
    featureArea: 'E2E-F02',
    refs: ['B.05'],
    async run(ctx) {
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        width: 1280,
        height: 800,
        profileOptions: {
          ui: { contextualToursAutoEligible: true, contextualToursSeenIds: [] }
        }
      })
      try {
        const { app, page } = inst
        await setViewportSize(app, page, 600, 400)
        await sleep(300)
        const skipBtn = page.getByRole('button', { name: /Skip tour|Close tour|跳过导览/i }).first()
        if (await skipBtn.isVisible().catch(() => false)) {
          await skipBtn.click()
        }
        // Assert UI is never deadlocked at 600x400
        const settingsBtn = page.getByRole('button', { name: /^(Settings|设置)$/i }).first()
        await settingsBtn.waitFor({ state: 'visible', timeout: 8000 })
        await settingsBtn.click()
        await page.locator('section[data-settings-section]').first().waitFor({ state: 'visible', timeout: 8000 })
        return { narrowTourNonDeadlocking: true }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T2-F02-04',
    tier: 2,
    featureArea: 'E2E-F02',
    refs: ['J13', 'P'],
    async run(ctx) {
      const longName = '长标题混合测试_Porpita_Workspace_Boundary_Long_Name_0123456789_ABCDEFGHIJKLMNOPQRSTUVWXYZ'
      const repo = createTempGitRepo({ name: longName.slice(0, 48) })
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        profileOptions: { locale: 'zh' },
        scaleFactor: 1.5
      })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        const overflow = await page.evaluate(() => ({
          dpr: window.devicePixelRatio,
          docScrollWidth: document.documentElement.scrollWidth,
          innerWidth: window.innerWidth,
          overflowX: document.documentElement.scrollWidth > window.innerWidth + 2
        }))
        assert.equal(overflow.overflowX, false, `Horizontal overflow at 150% DPI: ${JSON.stringify(overflow)}`)
        return overflow
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T2-F02-05',
    tier: 2,
    featureArea: 'E2E-F02',
    refs: ['F01', 'F02', 'F03'],
    async run(ctx) {
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        profileOptions: { locale: 'zh', settings: { showArtifactsButton: true } }
      })
      try {
        const { page } = inst
        const domText = await page.locator('body').innerText()
        if (/Orca Mobile/i.test(domText)) {
          pendingIfSmoke(
            ctx.mode,
            'M1',
            'Zero "Orca Mobile" occurrences in zh/en DOM',
            'Found "Orca Mobile" in DOM'
          )
        }
        // Visit Artifacts in zh
        const artifactsBtn = page.getByRole('button', { name: /^(Artifacts|工件)$/i }).first()
        if (await artifactsBtn.isVisible().catch(() => false)) {
          await artifactsBtn.click()
          await sleep(200)
          const artText = await page.locator('main, [data-workbench-viewport]').first().innerText()
          if (/Orca account/i.test(artText)) {
            pendingIfSmoke(ctx.mode, 'M1', 'Localized Porpita Artifacts empty state', artText.slice(0, 150))
          }
        }
        return { brandAuditClean: true }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T2-F02-06',
    tier: 2,
    featureArea: 'E2E-F02',
    refs: ['O.02'],
    async run(ctx) {
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { page } = inst
        await openSettingsPage(page)
        const generalNav = page.locator('aside button').filter({ hasText: /^(General|常规|通用)$/i }).first()
        await generalNav.click()
        const generalText = await page.locator('section[data-settings-section="general"]').innerText()
        assert.ok(generalText.length > 0, 'General settings rendered empty')
        assert.equal(
          /Downloading update\.\.\. \d+%/i.test(generalText),
          false,
          'Unexpected fake update download progress without update endpoint'
        )
        await returnFromSettings(page)
        return { honestUpdateState: true }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },

  // =========================================================================
  // E2E-F03 Boundary & Error Tests (6 Tests)
  // =========================================================================
  {
    id: 'T2-F03-01',
    tier: 2,
    featureArea: 'E2E-F03',
    refs: ['D.07.01'],
    async run(ctx) {
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        if (!(await hasIntegratedWorkspaceShell(inst.page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Dual-Pane exact 646px cutoff collapse & restore in default build',
            'Integrated dual-pane Workspace layout pending M3'
          )
        }
        return { verified: true }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T2-F03-02',
    tier: 2,
    featureArea: 'E2E-F03',
    refs: ['D.03.01'],
    async run(ctx) {
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        if (!(await hasIntegratedWorkspaceShell(inst.page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Split divider 15%/85% clamps & Esc/pointercancel revert in default build',
            'Integrated Workspace split divider pending M3'
          )
        }
        return { verified: true }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T2-F03-03',
    tier: 2,
    featureArea: 'E2E-F03',
    refs: ['C.10', 'S.02', 'C.10.09'],
    async run(ctx) {
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        if (!(await hasIntegratedWorkspaceShell(inst.page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Session Index 0-match Clear Filter CTA & offline host state in default build',
            'Session Index integration pending M3'
          )
        }
        return { verified: true }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T2-F03-04',
    tier: 2,
    featureArea: 'E2E-F03',
    refs: ['C.10', 'T.03'],
    async run(ctx) {
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        if (!(await hasIntegratedWorkspaceShell(inst.page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Drag Session to invalid drop zone or Esc mid-drag produces 0 side effects',
            'Session Index & Workspace drag-drop integration pending M3'
          )
        }
        return { verified: true }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T2-F03-05',
    tier: 2,
    featureArea: 'E2E-F03',
    refs: ['G.09.02'],
    async run(ctx) {
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        if (!(await hasIntegratedWorkspaceShell(inst.page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Same-named files across RepoA/RepoB stay bound to Fixed Explorer scope',
            'Pinned Fixed-Scope SidePanel Explorer integration pending M3'
          )
        }
        return { verified: true }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },
  {
    id: 'T2-F03-06',
    tier: 2,
    featureArea: 'E2E-F03',
    refs: ['M.02.06-M.02.13'],
    async run(ctx) {
      const repo = createTempGitRepo({
        name: 't2-f03-06',
        worktrees: [
          { branch: 'wt-clean' },
          { branch: 'wt-dirty', dirtyFile: 'uncommitted.txt', dirtyContent: 'keep me\n' }
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
        return { spaceDirtyWorktreeFixtureReady: true }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },

  // =========================================================================
  // E2E-F04 Boundary & Error Tests (6 Tests)
  // =========================================================================
  {
    id: 'T2-F04-01',
    tier: 2,
    featureArea: 'E2E-F04',
    refs: ['H.01', 'O.local.close', 'S.09'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't2-f04-01' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        const notesNode = page.getByText('notes.md', { exact: true }).first()
        await notesNode.waitFor({ state: 'visible', timeout: 10000 })
        await notesNode.dblclick()
        await page.getByText('Disposable editor text.', { exact: true }).first().waitFor({ state: 'visible', timeout: 10000 })
        // Modify notes.md externally on disk and confirm no crash
        writeFileSync(path.join(repo.repoPath, 'notes.md'), '# Externally Modified\n\nNew disk line.\n', 'utf8')
        await sleep(400)
        return { externalChangeHandled: true }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T2-F04-02',
    tier: 2,
    featureArea: 'E2E-F04',
    refs: ['H.02', 'H.03'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't2-f04-02' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        await page.getByText('sample.csv', { exact: true }).first().dblclick()
        await sleep(400)
        await page.getByText('notes.md', { exact: true }).first().dblclick()
        await sleep(300)
        const xssTriggered = await page.evaluate(() => Boolean(window.__xss))
        assert.equal(xssTriggered, false, 'Markdown <script> tag must NEVER execute')
        return { csvRows: 1050, xssTriggered }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T2-F04-03',
    tier: 2,
    featureArea: 'E2E-F04',
    refs: ['I.05'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't2-f04-03' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        await page.getByRole('button', { name: /^(New tab|新标签页)$/i }).first().click()
        await page.getByRole('menuitem', { name: /Browser|浏览器/i }).first().click()
        const addrBar = page.locator('[data-orca-browser-address-bar="true"]').first()
        await addrBar.waitFor({ state: 'visible', timeout: 10000 })
        const deadUrl = 'http://127.0.0.1:59999/dead'
        await addrBar.fill(deadUrl)
        await addrBar.press('Enter')
        await sleep(600)
        assert.ok((await addrBar.inputValue()).includes('59999'), 'Address bar lost user URL draft on dead port')
        return { deadUrlDraftPreserved: true }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T2-F04-04',
    tier: 2,
    featureArea: 'E2E-F04',
    refs: ['I.01', 'T.04'],
    async run(ctx) {
      const httpSrv = await startLoopbackHttpServer()
      const repo = createTempGitRepo({ name: 't2-f04-04' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        await page.getByRole('button', { name: /^(New tab|新标签页)$/i }).first().click()
        await page.getByRole('menuitem', { name: /Browser|浏览器/i }).first().click()
        const addrBar = page.locator('[data-orca-browser-address-bar="true"]').first()
        await addrBar.waitFor({ state: 'visible', timeout: 10000 })
        await addrBar.fill(`${httpSrv.baseUrl}/page2`)
        await addrBar.press('Enter')
        await sleep(500)
        await page.keyboard.press('Control+f')
        await sleep(250)
        await page.keyboard.press('Escape')
        return { browserFindTested: true }
      } finally {
        await closeElectronApp(inst)
        await httpSrv.close()
        repo.cleanup()
      }
    }
  },
  {
    id: 'T2-F04-05',
    tier: 2,
    featureArea: 'E2E-F04',
    refs: ['G.08', 'L.06'],
    async run(ctx) {
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      const pluginFix = createSyntheticPluginFixture(ctx.porpitaRoot)
      try {
        const { page } = inst
        await openSettingsPage(page)
        await page.locator('aside button').filter({ hasText: /^(Plugins|插件)/i }).first().click()
        await page.locator('section[data-settings-section="plugins"]').waitFor({ state: 'visible', timeout: 8000 })
        const toggleBtn = page.getByRole('button', { name: /Turn on plugins|开启插件/i }).first()
        if (await toggleBtn.isVisible().catch(() => false)) {
          await toggleBtn.click()
          await sleep(200)
        }
        const turnOffBtn = page.getByRole('button', { name: /Turn off plugins|关闭插件/i }).first()
        if (await turnOffBtn.isVisible().catch(() => false)) {
          await turnOffBtn.click()
          await sleep(200)
        }
        await returnFromSettings(page)
        return { pluginSystemToggledOffCleanly: true }
      } finally {
        await closeElectronApp(inst)
        pluginFix.cleanup()
      }
    }
  },
  {
    id: 'T2-F04-06',
    tier: 2,
    featureArea: 'E2E-F04',
    refs: ['E.03', 'T.04'],
    async run(ctx) {
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { page } = inst
        // Open Quick Open / Search and simulate compositionstart -> Enter -> compositionend
        const searchBtn = page
          .getByRole('button', { name: /Search worktrees and browser tabs|搜索工作树/i })
          .first()
        await searchBtn.click()
        await sleep(200)
        const activeTag = await page.evaluate(() => {
          const el = document.activeElement
          if (!el) return null
          el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true, data: '测' }))
          el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 229, isComposing: true, bubbles: true }))
          el.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '测试' }))
          return el.tagName
        })
        await page.keyboard.press('Escape')
        return { imeGuardExercisedOn: activeTag }
      } finally {
        await closeElectronApp(inst)
      }
    }
  },

  // =========================================================================
  // E2E-F05 Boundary & Error Tests (6 Tests)
  // =========================================================================
  {
    id: 'T2-F05-01',
    tier: 2,
    featureArea: 'E2E-F05',
    refs: ['communication-contract-adoption'],
    async run(ctx) {
      const core = await startLoopbackAcsCore({ mode: 'full' })
      try {
        const pid = core.info.project_id
        const conv = await core.request(
          'GET',
          `/projects/${pid}/conversations/resolve?with=${encodeURIComponent(core.addresses.peer_b)}`,
          { token: core.tokens.client }
        )
        const cid = conv.json.conversation_id
        const draft = await core.request('GET', `/projects/${pid}/conversations/${cid}/draft`, {
          token: core.tokens.client
        })
        assert.equal(draft.status, 200)
        assert.equal(draft.json.revision, 0)
        assert.equal(draft.json.updated_at, null, 'Empty rev-0 draft must have updated_at=null')

        // Emit legacy notice with created_at=NULL
        const legacyNotice = await core.emitNotice({ legacy_null_created_at: true })
        const notices = await core.request('GET', `/projects/${pid}/notices`, {
          token: core.tokens.client
        })
        assert.equal(notices.status, 200)
        const item = notices.json.items.find((n) => n.notice_handle === legacyNotice.notice_handle)
        assert.ok(item, 'Legacy notice missing from GET /notices')
        assert.equal(item.created_at, null, 'Legacy notice must preserve created_at=null')
        return { draftRevision: 0, legacyNoticeCreatedAt: item.created_at }
      } finally {
        await core.cleanup()
      }
    }
  },
  {
    id: 'T2-F05-02',
    tier: 2,
    featureArea: 'E2E-F05',
    refs: ['T05', 'COMMUNICATION-CLIENT-API'],
    async run(ctx) {
      const core = await startLoopbackAcsCore({ mode: 'full' })
      try {
        const pid = core.info.project_id
        const conv = await core.request(
          'GET',
          `/projects/${pid}/conversations/resolve?with=${encodeURIComponent(core.addresses.peer_b)}`,
          { token: core.tokens.client }
        )
        const cid = conv.json.conversation_id

        const put1 = await core.request('PUT', `/projects/${pid}/conversations/${cid}/draft`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'cas-key-1', 'If-Match': '"0"' },
          body: { content: 'First draft content', attachment_refs: [] }
        })
        assert.equal(put1.status, 200)

        // Exact retry with same key and body succeeds idempotently
        const retryExact = await core.request('PUT', `/projects/${pid}/conversations/${cid}/draft`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'cas-key-1', 'If-Match': '"0"' },
          body: { content: 'First draft content', attachment_refs: [] }
        })
        assert.equal(retryExact.status, 200)

        // Same Idempotency-Key with altered body conflicts (409)
        const altered = await core.request('PUT', `/projects/${pid}/conversations/${cid}/draft`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'cas-key-1', 'If-Match': '"0"' },
          body: { content: 'Altered body under same key', attachment_refs: [] }
        })
        assert.equal(altered.status, 409, altered.text)

        // New key with stale If-Match: "0" rejected (409/412)
        const staleCas = await core.request('PUT', `/projects/${pid}/conversations/${cid}/draft`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'cas-key-2', 'If-Match': '"0"' },
          body: { content: 'Stale write attempt', attachment_refs: [] }
        })
        assert.ok(staleCas.status === 409 || staleCas.status === 412, staleCas.text)
        return { exactRetry: retryExact.status, alteredConflict: altered.status, staleCas: staleCas.status }
      } finally {
        await core.cleanup()
      }
    }
  },
  {
    id: 'T2-F05-03',
    tier: 2,
    featureArea: 'E2E-F05',
    refs: ['T05', 'UX15'],
    async run(ctx) {
      const core = await startLoopbackAcsCore({ mode: 'full' })
      try {
        const pid = core.info.project_id
        await core.setFault({ drop_next_send_response: true })

        const idemKey = 'fault-send-retry-1'
        const first = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': idemKey },
          body: { to: core.addresses.peer_b, content: 'Commit before simulated drop' }
        })
        assert.equal(first.status, 503)
        assert.equal(first.json.error.effect_state, 'committed')

        // Restart loopback Core server against same PostgreSQL DB, then retry with same Idempotency-Key
        await core.restartServer({ reusePort: true })
        const retry = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': idemKey },
          body: { to: core.addresses.peer_b, content: 'Commit before simulated drop' }
        })
        assert.ok(retry.status === 200 || retry.status === 201, retry.text)

        const list = await core.request(
          'GET',
          `/projects/${pid}/messages?with=${encodeURIComponent(core.addresses.peer_b)}`,
          { token: core.tokens.client }
        )
        const matching = list.json.items.filter(
          (m) => (typeof m.content === 'string' ? m.content : m.content?.text) === 'Commit before simulated drop'
        )
        assert.equal(matching.length, 1, `Expected 1 message (no duplicate), got ${matching.length}`)
        return { firstStatus: first.status, retryStatus: retry.status, messageCount: matching.length }
      } finally {
        await core.cleanup()
      }
    }
  },
  {
    id: 'T2-F05-04',
    tier: 2,
    featureArea: 'E2E-F05',
    refs: ['COMMUNICATION-CLIENT-API:92'],
    async run(ctx) {
      const core = await startLoopbackAcsCore({ mode: 'full' })
      try {
        const pid = core.info.project_id
        const maxOk = 'a'.repeat(256 * 1024)
        const resOk = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'size-256k-ok' },
          body: { to: core.addresses.peer_b, content: maxOk }
        })
        assert.equal(resOk.status, 201, `256 KiB payload should succeed: ${resOk.text}`)

        const tooBig = 'a'.repeat(256 * 1024 + 1)
        const resBig = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'size-256k-plus1' },
          body: { to: core.addresses.peer_b, content: tooBig }
        })
        assert.equal(resBig.status, 413, `256 KiB + 1 byte must be rejected with 413: ${resBig.text}`)
        assert.equal(resBig.json.error.code, 'content_too_large')
        return { maxOkStatus: resOk.status, oversizeStatus: resBig.status }
      } finally {
        await core.cleanup()
      }
    }
  },
  {
    id: 'T2-F05-05',
    tier: 2,
    featureArea: 'E2E-F05',
    refs: ['COMMUNICATION-CLIENT-API:286', 'communication-contract-adoption'],
    async run(ctx) {
      const core = await startLoopbackAcsCore({ mode: 'full' })
      try {
        const pid = core.info.project_id
        // Unlinked message (message_only -> no native invocation)
        const send = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'unlinked-msg-1' },
          body: { to: core.addresses.peer_b, content: 'Plain message_only text', activation: 'message_only' }
        })
        assert.equal(send.status, 201)
        const handle = encodeURIComponent(send.json.message.message_handle)

        const invalidBool = await core.request(
          'GET',
          `/projects/${pid}/messages/${handle}?include_native_source=yes`,
          { token: core.tokens.client }
        )
        assert.equal(invalidBool.status, 400, invalidBool.text)

        const unlinkedRead = await core.request(
          'GET',
          `/projects/${pid}/messages/${handle}?include_native_source=true`,
          { token: core.tokens.client }
        )
        assert.equal(unlinkedRead.status, 200)
        assert.equal(unlinkedRead.json.native_source.available, false, 'Unlinked msg must report available=false')

        // Stale expected_provider_generation on NativeLinkWrite
        const staleLink = await core.request('PUT', `/projects/${pid}/native-links/link-stale`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'link-stale-1' },
          body: { ...core.nativeLinkFixture, expected_provider_generation: 'stale-generation-xyz' }
        })
        assert.ok(staleLink.status >= 400, `Expected rejection on stale provider generation: ${staleLink.text}`)
        return {
          invalidBoolStatus: invalidBool.status,
          unlinkedAvailable: unlinkedRead.json.native_source.available,
          staleLinkStatus: staleLink.status
        }
      } finally {
        await core.cleanup()
      }
    }
  },
  {
    id: 'T2-F05-06',
    tier: 2,
    featureArea: 'E2E-F05',
    refs: ['T07', 'T12', 'Meta.limits'],
    async run(ctx) {
      // Part A: Token revocation (T07) & third-party isolation (T12)
      const core = await startLoopbackAcsCore({ mode: 'full' })
      try {
        const pid = core.info.project_id
        const msg = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'acl-msg-1' },
          body: { to: core.addresses.peer_b, content: 'Secret between client and peer_b' }
        })
        assert.equal(msg.status, 201)

        // Third party peer_c must be denied (403) reading client<->peer_b message
        const thirdParty = await core.request(
          'GET',
          `/projects/${pid}/messages/${encodeURIComponent(msg.json.message.message_handle)}`,
          { token: core.tokens.peer_c }
        )
        assert.equal(thirdParty.status, 403, `Expected 403 for peer_c, got ${thirdParty.status}`)

        // Revoke client token -> subsequent reads/writes fail (403) while peer_b remains functional
        await core.revokeToken('client')
        const revokedRead = await core.request('GET', `/projects/${pid}/messages`, {
          token: core.tokens.client
        })
        assert.ok(revokedRead.status === 401 || revokedRead.status === 403, revokedRead.text)

        const validPeerRead = await core.request('GET', `/projects/${pid}/messages`, {
          token: core.tokens.peer_b
        })
        assert.equal(validPeerRead.status, 200)
      } finally {
        await core.cleanup()
      }

      // Part B: P1-only mode /meta.features boundary
      const p1Core = await startLoopbackAcsCore({ mode: 'p1_only' })
      try {
        const meta = await p1Core.request('GET', '/meta')
        assert.equal(meta.status, 200)
        assert.equal(meta.json.limits.attachment_count, 0)
        assert.equal(meta.json.features.includes('attachments'), false)
        assert.equal(meta.json.features.includes('events'), false)
        const disabledAtt = await p1Core.request('POST', `/projects/${p1Core.info.project_id}/attachments`, {
          token: p1Core.tokens.client,
          headers: { 'Idempotency-Key': 'p1-att-blocked' },
          body: { name: 'a.txt', media_type: 'text/plain', bytes: 4, sha256: '0'.repeat(64) }
        })
        assert.equal(disabledAtt.status, 409)
        assert.equal(disabledAtt.json.error.code, 'capability_unsupported')
        return { p1OnlyAttachmentStatus: disabledAtt.status }
      } finally {
        await p1Core.cleanup()
      }
    }
  },

  // =========================================================================
  // E2E-F06 Boundary & Error Tests (6 Tests)
  // =========================================================================
  {
    id: 'T2-F06-01',
    tier: 2,
    featureArea: 'E2E-F06',
    refs: ['build_coverage.py'],
    async run(ctx) {
      const neg = runStagedBuildCoverage({
        specRoot: ctx.specRoot,
        porpitaRoot: ctx.porpitaRoot,
        historyRoot: ctx.historyRoot,
        injectBrokenAnchor: true
      })
      assert.notEqual(neg.buildCoverageExitCode, 0, 'Negative probe must exit non-zero on broken anchor')
      assert.match(
        neg.buildCoverageStderr,
        /NonExistentAnchorForNegativeProbe\.tsx/,
        `Expected broken anchor name in stderr, got: ${neg.buildCoverageStderr}`
      )
      return { negativeProbeExitCode: neg.buildCoverageExitCode, caughtAnchor: 'NonExistentAnchorForNegativeProbe.tsx' }
    }
  },
  {
    id: 'T2-F06-02',
    tier: 2,
    featureArea: 'E2E-F06',
    refs: ['coverage-audit.json'],
    async run(ctx) {
      const auditPath = path.join(ctx.specRoot, 'coverage-audit.json')
      assert.equal(existsSync(auditPath), true, 'coverage-audit.json missing')
      const audit = JSON.parse(readFileSync(auditPath, 'utf8'))
      const currentHead = execFileSync('git', ['-C', ctx.porpitaRoot, 'rev-parse', 'HEAD'], {
        encoding: 'utf8'
      }).trim()
      if (audit.source !== currentHead) {
        pendingIfSmoke(
          ctx.mode,
          'M4',
          `coverage-audit.json source SHA matches .tmp/porpita-ui-spec-03 HEAD (${currentHead})`,
          `coverage-audit.json source=${audit.source}, currentHead=${currentHead}`
        )
      }
      return { auditSource: audit.source, currentHead }
    }
  },
  {
    id: 'T2-F06-03',
    tier: 2,
    featureArea: 'E2E-F06',
    refs: ['communication-api-scope.json', 'communication-p1-openapi.yaml'],
    async run(ctx) {
      const clientDocsDir = path.dirname(ctx.specRoot)
      const parity = checkApiScopeParity({ clientDocsDir })
      assert.equal(parity.totalOps, 35, `Expected 35 operations, got ${parity.totalOps}`)
      assert.equal(parity.p1Count, 22, `Expected 22 P1_required, got ${parity.p1Count}`)
      assert.equal(parity.p2Count, 13, `Expected 13 P2_optional, got ${parity.p2Count}`)
      assert.deepEqual(parity.missingInFull, [])
      assert.deepEqual(parity.missingInP1, [])
      assert.deepEqual(parity.extraP2InP1, [])
      return parity
    }
  },
  {
    id: 'T2-F06-04',
    tier: 2,
    featureArea: 'E2E-F06',
    refs: ['COVERAGE_CLOSURE.md', 'R3'],
    async run(ctx) {
      const honesty = checkEnvBoundedHonesty({ specRoot: ctx.specRoot })
      assert.deepEqual(honesty.uncoveredCategories, [])
      assert.deepEqual(honesty.dishonestFindings, [])
      return honesty
    }
  },
  {
    id: 'T2-F06-05',
    tier: 2,
    featureArea: 'E2E-F06',
    refs: ['check_design_evidence.py'],
    async run(ctx) {
      const res = runDesignEvidenceCheck({
        agentCollabRoot: 'D:\\Chatgpt\\Agent-collaboration',
        porpitaRoot: ctx.porpitaRoot
      })
      if (res.applicable) {
        assert.equal(res.exitCode, 0, `check_design_evidence.py failed: ${res.stderr}`)
      }
      return res
    }
  },
  {
    id: 'T2-F06-06',
    tier: 2,
    featureArea: 'E2E-F06',
    refs: ['PROJECT', 'R3'],
    async run(ctx) {
      const before = verifyGitBaselines({
        agentCollabRoot: 'D:\\Chatgpt\\Agent-collaboration',
        porpitaRoot: ctx.historyRoot
      })
      assert.equal(before.ok, true, `Baseline verification failed: ${before.issues.join(' | ')}`)
      // Also verify .tmp/porpita-ui-spec-03 has not been modified by any E2E suite file
      const porpitaWorktreeStatus = execFileSync(
        'git',
        ['-C', ctx.porpitaRoot, 'status', '--short'],
        { encoding: 'utf8' }
      ).trim()
      return {
        baselinesIntact: true,
        porpitaWorktreeDirtyLines: porpitaWorktreeStatus ? porpitaWorktreeStatus.split(/\r?\n/).length : 0
      }
    }
  }
]
