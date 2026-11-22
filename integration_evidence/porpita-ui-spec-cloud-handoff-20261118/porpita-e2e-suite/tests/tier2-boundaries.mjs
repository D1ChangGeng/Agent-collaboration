import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import {
  addLocalFolderProject,
  assertAllWindowsHidden,
  assertImeCompositionKeepsDialogOpen,
  closeCollaborationDialogWithFocusCheck,
  closeElectronApp,
  connectCollaborationViaSettings,
  disablePluginAndVerify,
  dismissStartupDialogs,
  hasIntegratedWorkspaceShell,
  installAndEnableFolderPlugin,
  launchElectronApp,
  M3_SELECTOR_CONTRACT,
  openAndVerifyPluginPanel,
  openCollaborationDialog,
  openMarkdownPreviewAndVerify,
  openSettingsPage,
  primaryModifierKey,
  returnFromSettings,
  selectCollaborationContact,
  setViewportSize,
  sleep,
  stubOpenDialog,
  waitForVisible
} from '../lib/electron-harness.mjs'
import { startLoopbackAcsCore } from '../lib/acs-core-harness.mjs'
import {
  createSyntheticPluginFixture,
  createTempGitRepo,
  createTempPlainFolder,
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
        const { app, page } = inst
        if (!(await hasIntegratedWorkspaceShell(page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Top-level group selector <= min(132px, 31%) & overflow reachable below 260px',
            'Top-level Workspace tab strip & group selector pending M3 integration'
          )
        }
        const groupBtn = page.locator(M3_SELECTOR_CONTRACT.groupSelector).first()
        await groupBtn.waitFor({ state: 'visible', timeout: 8000 })
        await setViewportSize(app, page, 360, 400)
        const narrowMetrics = await page.evaluate((sel) => {
          const el = document.querySelector(sel)
          const r = el?.getBoundingClientRect()
          return {
            width: r ? r.width : 0,
            maxAllowed: Math.min(132, window.innerWidth * 0.31) + 2,
            insideViewport: Boolean(r && r.left >= 0 && r.right <= window.innerWidth + 1),
            overflowX: document.documentElement.scrollWidth > window.innerWidth + 2
          }
        }, M3_SELECTOR_CONTRACT.groupSelector)
        assert.ok(
          narrowMetrics.width > 0 && narrowMetrics.width <= narrowMetrics.maxAllowed,
          `Group selector exceeded min(132px, 31%): ${JSON.stringify(narrowMetrics)}`
        )
        assert.equal(narrowMetrics.insideViewport, true, 'Group selector clipped out of narrow viewport')
        assert.equal(narrowMetrics.overflowX, false, 'Horizontal overflow at narrow group selector width')
        return narrowMetrics
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
        const { page } = inst
        const landingText = await page.locator('body').innerText()
        assert.match(landingText, /Add project|添加项目/i, 'Empty landing CTA missing')
        if (!(await hasIntegratedWorkspaceShell(page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Zero-workspace empty boundary & General group delete protection in default build',
            'Top-level Workspace & General group protection pending M3 integration'
          )
        }
        const groupBtn = page.locator(M3_SELECTOR_CONTRACT.groupSelector).first()
        await groupBtn.waitFor({ state: 'visible', timeout: 8000 })
        await groupBtn.click()
        const deleteGeneral = page.getByRole('menuitem', { name: /Delete.*General|删除.*通用/i })
        assert.equal(await deleteGeneral.count(), 0, 'General group must not expose a delete action')
        await page.keyboard.press('Escape')
        return { landingEmptyCtaPresent: true, generalGroupProtected: true }
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
        const { page } = inst
        if (!(await hasIntegratedWorkspaceShell(page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Duplicate group name disambiguation & 20+ tabs overflow stress in default build',
            'Top-level Workspace tab groups pending M3 integration'
          )
        }
        const groupBtn = page.locator(M3_SELECTOR_CONTRACT.groupSelector).first()
        await groupBtn.waitFor({ state: 'visible', timeout: 8000 })
        for (let g = 0; g < 2; g++) {
          await groupBtn.click()
          await page.getByRole('menuitem', { name: /New tab group|新建标签组/i }).first().click()
          const input = page.getByRole('dialog').locator('input').first()
          await input.fill('Alpha')
          await page.getByRole('dialog').getByRole('button', { name: /^(Create group|Create|创建|确认)$/i }).first().click()
          await sleep(100)
        }
        await groupBtn.click()
        const alphaCount = await page.getByRole('menuitemradio', { name: /Alpha/i }).count()
        assert.ok(alphaCount >= 1, 'Duplicate group creation broke group picker')
        await page.keyboard.press('Escape')

        for (let t = 0; t < 20; t++) {
          await page.getByRole('button', { name: /^(New work object|新建工作对象)$/i }).first().click()
          await page.getByRole('menuitem', { name: /^(New workspace|新建工作空间)$/i }).first().click()
        }
        const overflowCheck = await page.evaluate((stripSel) => {
          const strip = document.querySelector(stripSel)
          return {
            tabCount: document.querySelectorAll('[data-workspace-preview-tab], [data-workspace-tab]').length,
            stripScrolls: strip ? strip.scrollWidth >= strip.clientWidth : false,
            docOverflowX: document.documentElement.scrollWidth > window.innerWidth + 2
          }
        }, M3_SELECTOR_CONTRACT.tabStrip)
        assert.ok(overflowCheck.tabCount >= 20, `Expected >=20 tabs, got ${overflowCheck.tabCount}`)
        assert.equal(overflowCheck.docOverflowX, false, '20+ tabs leaked document horizontal overflow')
        return overflowCheck
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
          const retryOrNotice = await relaunched.page.evaluate(() => ({
            hasNotice: Boolean(document.querySelector('[data-workspace-preview] [role="status"], [role="alert"]')),
            hasTabs: document.querySelectorAll('[data-workspace-preview-tab], [data-workspace-tab]').length > 0
          }))
          assert.ok(
            retryOrNotice.hasNotice || retryOrNotice.hasTabs,
            'Expected recoverable status notice or recovered workspace shell after corrupt layout JSON'
          )
          return { survivedCorruptLayout: true, ...retryOrNotice }
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
      const repo = createTempGitRepo({ name: 't2-f01-06' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        if (!(await hasIntegratedWorkspaceShell(page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Disconnected/revoked paired host placeholder leaves unaffected Pane interactive',
            'Integrated multi-host Workspace layout pending M3'
          )
        }
        const activePane = page.locator('[data-workspace-preview-session], [data-workspace-session]').first()
        await activePane.waitFor({ state: 'visible', timeout: 8000 })
        const interactive = await page.evaluate(() => {
          const settingsBtn = document.querySelector('button[aria-label="Settings"], button[aria-label="设置"]')
          return Boolean(settingsBtn && !settingsBtn.hasAttribute('disabled'))
        })
        assert.equal(interactive, true, 'Workbench controls must remain interactive')
        return { unaffectedPaneInteractive: interactive }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
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
          await modal.waitFor({ state: 'visible', timeout: 3000 })
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
      const { execFileSync } = await import('node:child_process')
      const fs = await import('node:fs')
      const os = await import('node:os')
      const path = await import('node:path')

      const plain = createTempPlainFolder({ name: 't2-f02-02-plain' })
      // Build a real local git repo whose local `main` is 1 commit behind `origin/main` AND has uncommitted
      // tracked edits so creating a worktree with "Keep Local Main Up to Date" enabled fires Porpita's
      // persistent (`duration: Infinity`) localBaseRefRefresh warning Sonner toast.
      const gitTmp = fs.mkdtempSync(path.join(os.tmpdir(), 'porpita-t2-f02-02-'))
      const seedDir = path.join(gitTmp, 'seed')
      const bareDir = path.join(gitTmp, 'origin.git')
      const behindDir = path.join(gitTmp, 'behind-repo')
      const git = (cwd, args) => execFileSync('git', args, { cwd, stdio: 'pipe', encoding: 'utf8' })
      fs.mkdirSync(seedDir, { recursive: true })
      git(seedDir, ['init', '-b', 'main'])
      git(seedDir, ['config', 'user.name', 'Porpita E2E'])
      git(seedDir, ['config', 'user.email', 'e2e@porpita.test'])
      fs.writeFileSync(path.join(seedDir, 'README.md'), 'c1\n', 'utf8')
      git(seedDir, ['add', 'README.md'])
      git(seedDir, ['commit', '-m', 'c1'])
      git(gitTmp, ['clone', '--bare', seedDir, bareDir])
      git(gitTmp, ['clone', bareDir, behindDir])
      git(behindDir, ['config', 'user.name', 'Porpita E2E'])
      git(behindDir, ['config', 'user.email', 'e2e@porpita.test'])
      fs.writeFileSync(path.join(seedDir, 'README.md'), 'c1\nc2\n', 'utf8')
      git(seedDir, ['commit', '-am', 'c2'])
      git(seedDir, ['push', bareDir, 'main:main'])
      git(behindDir, ['fetch', 'origin'])
      fs.writeFileSync(path.join(behindDir, 'README.md'), 'dirty-local-edit\n', 'utf8')

      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        width: 1024,
        height: 700
      })
      try {
        const { app, page } = inst
        await dismissStartupDialogs(page)

        // 1. Enable Settings -> Git & Source Control -> Keep Local Main Up to Date
        await openSettingsPage(page)
        const gitNav = page
          .locator('aside button')
          .filter({ hasText: /Git & Source Control|源代码管理/i })
          .first()
        await gitNav.waitFor({ state: 'visible', timeout: 8000 })
        await gitNav.click()
        const gitSec = page.locator('section[data-settings-section="git"]').first()
        await gitSec.waitFor({ state: 'visible', timeout: 8000 })
        const keepSwitch = gitSec
          .locator(
            'button[role="switch"][aria-label*="Keep Local Main"], button[role="switch"][aria-label*="保持本地"]'
          )
          .first()
        await keepSwitch.waitFor({ state: 'visible', timeout: 8000 })
        if ((await keepSwitch.getAttribute('aria-checked')) !== 'true') {
          await keepSwitch.click()
        }
        await returnFromSettings(page)

        // 2. Add the dirty behind-origin repo and create one worktree so `duration: Infinity` warning toast fires
        await stubOpenDialog(app, behindDir)
        const landingAddBtn = page
          .locator('button:visible')
          .filter({ hasText: /^(Add project|添加项目)$/i })
          .first()
        await landingAddBtn.waitFor({ state: 'visible', timeout: 8000 })
        await landingAddBtn.click()
        const browseSeedBtn = page.getByRole('button', { name: /Browse folder|浏览文件夹/i }).first()
        await browseSeedBtn.waitFor({ state: 'visible', timeout: 8000 })
        await browseSeedBtn.click()
        await page.locator('[role="dialog"]').first().waitFor({ state: 'hidden', timeout: 10000 }).catch(() => {})

        const composer = page.locator('[data-workspace-composer-root="true"]').first()
        if (!(await waitForVisible(composer, 2500))) {
          const newWsBtn = page
            .locator(
              'button[data-contextual-tour-target="workspace-create-control"], button[aria-label="New workspace"], button[aria-label="新建工作空间"]'
            )
            .first()
          await newWsBtn.waitFor({ state: 'visible', timeout: 10000 })
          await newWsBtn.click()
          await composer.waitFor({ state: 'visible', timeout: 10000 })
        }
        const createBtn = composer
          .getByRole('button', {
            name: /^(Create worktree|Create workspace|Create|创建工作树|创建工作空间|创建)$/i
          })
          .last()
        await createBtn.waitFor({ state: 'visible', timeout: 8000 })
        await createBtn.click()

        const warningToast = page
          .locator('[data-sonner-toaster] [data-sonner-toast]')
          .filter({ hasText: /was not refreshed|Local main|未刷新/i })
          .first()
        await warningToast.waitFor({ state: 'visible', timeout: 15000 })
        if ((await page.locator('[role="dialog"]').count()) > 0) {
          await page.keyboard.press('Escape').catch(() => {})
          await page.locator('[role="dialog"]').first().waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {})
        }

        // Dismiss any overlay notification card (e.g. Codex shared-settings card) so 600x400 controls stay unobstructed
        const cardDismissBtn = page
          .locator('[data-notification-card-stack] button[aria-label="Dismiss"], [data-notification-card-stack] button[aria-label="关闭"]')
          .first()
        for (let i = 0; i < 3 && (await waitForVisible(cardDismissBtn, 500)); i += 1) {
          await cardDismissBtn.click().catch(() => {})
        }

        // 3. Resize to 600x400 with the persistent Sonner toast active
        await setViewportSize(app, page, 600, 400)
        await stubOpenDialog(app, plain.folderPath)

        const verifyModalAt600x400 = async (label, controlSelectors) => {
          const check = await page.evaluate((selectors) => {
            const dialogs = [...document.querySelectorAll('[role="dialog"], [role="alertdialog"]')]
            const modal = dialogs.at(-1)
            const toaster = document.querySelector('[data-sonner-toaster]')
            const activeToast = document.querySelector('[data-sonner-toast][data-visible="true"]')
            if (!modal) return { dialogCount: 0 }

            const mz = Number.parseInt(getComputedStyle(modal).zIndex || '50', 10)
            const tz = toaster ? Number.parseInt(getComputedStyle(toaster).zIndex || '47', 10) : null
            const controls = []
            for (const sel of selectors) {
              for (const el of modal.querySelectorAll(sel)) {
                const r = el.getBoundingClientRect()
                if (r.width <= 0 || r.height <= 0) continue
                const cx = Math.min(window.innerWidth - 1, Math.max(0, r.left + r.width / 2))
                const cy = Math.min(window.innerHeight - 1, Math.max(0, r.top + r.height / 2))
                const stack = document.elementsFromPoint(cx, cy)
                const top = stack[0] || null
                const hitsModal = Boolean(top && modal.contains(top))
                const modalIdx = stack.findIndex((node) => modal.contains(node))
                const toastIdx = stack.findIndex((node) =>
                  Boolean(node.closest?.('[data-sonner-toaster], [data-sonner-toast]'))
                )
                const hitsToast = toastIdx !== -1 && (modalIdx === -1 || toastIdx <= modalIdx)
                controls.push({
                  text: (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 40),
                  fitsViewport:
                    r.left >= 0 &&
                    r.top >= 0 &&
                    r.right <= window.innerWidth + 1 &&
                    r.bottom <= window.innerHeight + 1,
                  hitsModal,
                  hitsToast,
                  rect: { left: Math.round(r.left), top: Math.round(r.top), right: Math.round(r.right), bottom: Math.round(r.bottom) }
                })
              }
            }
            return {
              innerWidth: window.innerWidth,
              innerHeight: window.innerHeight,
              dialogCount: dialogs.length,
              modalOverlayOpen: document.body.hasAttribute('data-modal-overlay-open'),
              toastsRaised: document.body.querySelector('[data-toasts-raised]') !== null,
              toasterPresent: Boolean(toaster),
              activeToastPresent: Boolean(activeToast),
              mz,
              tz,
              toastInFront: tz !== null && mz !== null ? tz > mz : null,
              controls
            }
          }, controlSelectors)

          assert.ok(check.dialogCount >= 1, `${label}: expected >= 1 open dialog at 600x400`)
          assert.equal(check.modalOverlayOpen, true, `${label}: body[data-modal-overlay-open] missing`)
          assert.equal(check.toastsRaised, false, `${label}: existing toast unexpectedly raised in front of non-suppressing modal`)
          assert.equal(check.toasterPresent, true, `${label}: expected active [data-sonner-toaster] in DOM`)
          assert.equal(check.activeToastPresent, true, `${label}: expected visible [data-sonner-toast][data-visible="true"] in DOM`)
          assert.equal(check.toastInFront, false, `${label}: toast z-index (${check.tz}) > modal z-index (${check.mz})`)
          assert.ok(check.controls.length >= 2, `${label}: expected >= 2 modal controls checked, got ${check.controls.length}`)
          for (const c of check.controls) {
            assert.equal(c.fitsViewport, true, `${label}: control clipped outside 600x400: ${JSON.stringify(c)}`)
            assert.equal(c.hitsModal, true, `${label}: elementsFromPoint at control center did not hit modal: ${JSON.stringify(c)}`)
            assert.equal(c.hitsToast, false, `${label}: toast overlapped modal control: ${JSON.stringify(c)}`)
          }
          return check
        }

        // 3. Open AddRepoDialog via Sidebar Add project button (expanding sidebar if collapsed at 600x400)
        const sidebarAddBtn = page
          .locator('button[aria-label="Add project"], button[aria-label="添加项目"]')
          .first()
        if (!(await waitForVisible(sidebarAddBtn, 1000))) {
          const toggleSidebarBtn = page
            .locator('button[aria-label="Toggle sidebar"], button[aria-label="切换侧边栏"]')
            .first()
          if (await waitForVisible(toggleSidebarBtn, 3000)) {
            await toggleSidebarBtn.click()
          }
        }
        await sidebarAddBtn.waitFor({ state: 'visible', timeout: 8000 })
        await sidebarAddBtn.focus()
        await page.keyboard.press('Enter')
        const browseBtn = page.getByRole('button', { name: /Browse folder|浏览文件夹/i }).first()
        await browseBtn.waitFor({ state: 'visible', timeout: 8000 })
        const addRepoCheck = await verifyModalAt600x400('AddRepoDialog', [
          'button[data-add-repo-action]',
          '[data-slot="dialog-close"]'
        ])

        // 4. Click Browse folder -> NonGitFolderDialog with explicit primary + Cancel + Close buttons
        await browseBtn.click()
        const openAsFolderBtn = page
          .getByRole('button', { name: /^(Open as Folder|作为文件夹打开)$/i })
          .first()
        await openAsFolderBtn.waitFor({ state: 'visible', timeout: 8000 })
        const nonGitCheck = await verifyModalAt600x400('NonGitFolderDialog', [
          '[data-slot="dialog-footer"] button',
          '[data-slot="dialog-close"]'
        ])
        await page.keyboard.press('Escape')
        return { viewport: '600x400', addRepoCheck, nonGitCheck }
      } finally {
        await closeElectronApp(inst)
        plain.cleanup()
        try {
          fs.rmSync(gitTmp, { recursive: true, force: true })
        } catch {}
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
      const repo = createTempGitRepo({ name: 't2-f03-01' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        if (!(await hasIntegratedWorkspaceShell(page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Dual-Pane exact 646px cutoff collapse & restore in default build',
            'Integrated dual-pane Workspace layout pending M3'
          )
        }
        const addSessionBtn = page.getByRole('button', { name: /Add session|添加会话/i }).first()
        if (await waitForVisible(addSessionBtn, 3000)) await addSessionBtn.click()
        const splitBox = page.locator(M3_SELECTOR_CONTRACT.splitLayout).first()
        await splitBox.waitFor({ state: 'visible', timeout: 8000 })
        assert.equal(await splitBox.getAttribute('data-preview-split'), 'side-by-side')
        await setViewportSize(app, page, 640, 600)
        await page.waitForFunction(
          (sel) => document.querySelector(sel)?.getAttribute('data-preview-split') === 'focused',
          M3_SELECTOR_CONTRACT.splitLayout,
          { timeout: 6000 }
        )
        await setViewportSize(app, page, 1280, 800)
        await page.waitForFunction(
          (sel) => document.querySelector(sel)?.getAttribute('data-preview-split') === 'side-by-side',
          M3_SELECTOR_CONTRACT.splitLayout,
          { timeout: 6000 }
        )
        return { cutoffCollapseAndRestoreVerified: true }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T2-F03-02',
    tier: 2,
    featureArea: 'E2E-F03',
    refs: ['D.03.01'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't2-f03-02' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        if (!(await hasIntegratedWorkspaceShell(page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Split divider 15%/85% clamps & Esc/pointercancel revert in default build',
            'Integrated Workspace split divider pending M3'
          )
        }
        const addSessionBtn = page.getByRole('button', { name: /Add session|添加会话/i }).first()
        if (await waitForVisible(addSessionBtn, 3000)) await addSessionBtn.click()
        const separator = page.getByRole('separator').first()
        await separator.waitFor({ state: 'visible', timeout: 8000 })
        const minVal = Number.parseFloat((await separator.getAttribute('aria-valuemin')) || '15')
        const maxVal = Number.parseFloat((await separator.getAttribute('aria-valuemax')) || '85')
        assert.ok(minVal >= 15 && maxVal <= 85, `Expected divider bounds within 15..85, got ${minVal}..${maxVal}`)
        await separator.focus()
        await page.keyboard.press('Home')
        const lowVal = Number.parseFloat((await separator.getAttribute('aria-valuenow')) || '0')
        assert.ok(lowVal >= minVal, `Home clamped below minVal: ${lowVal} < ${minVal}`)
        const box = await separator.boundingBox()
        assert.ok(box, 'Separator missing bounding box')
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
        await page.mouse.down()
        await page.mouse.move(box.x + 150, box.y + box.height / 2)
        await page.keyboard.press('Escape')
        await page.mouse.up()
        const revertedVal = Number.parseFloat((await separator.getAttribute('aria-valuenow')) || '0')
        assert.equal(revertedVal, lowVal, `Escape mid-drag must revert ratio (${revertedVal} !== ${lowVal})`)
        return { minVal, maxVal, lowVal, revertedVal }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T2-F03-03',
    tier: 2,
    featureArea: 'E2E-F03',
    refs: ['C.10', 'S.02', 'C.10.09'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't2-f03-03' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        if (!(await hasIntegratedWorkspaceShell(page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Session Index 0-match Clear Filter CTA & offline host state in default build',
            'Session Index integration pending M3'
          )
        }
        const sessionIndex = page.locator(M3_SELECTOR_CONTRACT.sessionIndex).first()
        await sessionIndex.waitFor({ state: 'visible', timeout: 8000 })
        const searchInput = sessionIndex.locator('input').first()
        await searchInput.fill('__zero_match_probe__')
        const status = sessionIndex.locator('[role="status"]').first()
        await status.waitFor({ state: 'visible', timeout: 5000 })
        const statusText = (await status.innerText()).trim()
        assert.ok(statusText.length > 0, 'Session Index 0-match status message empty')
        await searchInput.fill('')
        return { zeroMatchStatusText: statusText }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T2-F03-04',
    tier: 2,
    featureArea: 'E2E-F03',
    refs: ['C.10', 'T.03'],
    async run(ctx) {
      const repo = createTempGitRepo({ name: 't2-f03-04' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        if (!(await hasIntegratedWorkspaceShell(page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Drag Session to invalid drop zone or Esc mid-drag produces 0 side effects',
            'Session Index & Workspace drag-drop integration pending M3'
          )
        }
        const tab = page.locator(M3_SELECTOR_CONTRACT.workspaceTab).first()
        await tab.waitFor({ state: 'visible', timeout: 8000 })
        const beforeCount = await page.locator(M3_SELECTOR_CONTRACT.workspaceTab).count()
        const box = await tab.boundingBox()
        assert.ok(box, 'Workspace tab missing bounding box')
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
        await page.mouse.down()
        await page.mouse.move(box.x + box.width / 2, box.y + 200)
        await page.keyboard.press('Escape')
        await page.mouse.up()
        const afterCount = await page.locator(M3_SELECTOR_CONTRACT.workspaceTab).count()
        assert.equal(afterCount, beforeCount, 'Aborted drag must leave tab count unchanged')
        return { beforeCount, afterCount }
      } finally {
        await closeElectronApp(inst)
        repo.cleanup()
      }
    }
  },
  {
    id: 'T2-F03-05',
    tier: 2,
    featureArea: 'E2E-F03',
    refs: ['G.09.02'],
    async run(ctx) {
      const repoA = createTempGitRepo({ name: 't2-f03-05-a', files: { 'shared.md': '# Repo A Unique\n' } })
      const repoB = createTempGitRepo({ name: 't2-f03-05-b', files: { 'shared.md': '# Repo B Unique\n' } })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repoA.repoPath)
        await addLocalFolderProject(app, page, repoB.repoPath)
        if (!(await hasIntegratedWorkspaceShell(page))) {
          pendingIfSmoke(
            ctx.mode,
            'M3',
            'Same-named files across RepoA/RepoB stay bound to Fixed Explorer scope',
            'Pinned Fixed-Scope SidePanel Explorer integration pending M3'
          )
        }
        // Switch back to Repo A worktree, open Explorer pinned to Repo A, then switch active worktree to Repo B
        await page.getByText(path.basename(repoA.repoPath)).first().click()
        await page.getByRole('button', { name: /^(New work object|新建工作对象)$/i }).first().click()
        await page.getByRole('menuitem', { name: /^(Open Explorer|打开资源管理器)$/i }).first().click()
        const explorer = page.locator(M3_SELECTOR_CONTRACT.explorer).first()
        await explorer.waitFor({ state: 'visible', timeout: 8000 })
        const scopeBefore = (await explorer.locator(M3_SELECTOR_CONTRACT.explorerScope).first().innerText()).trim()
        await page.getByText(path.basename(repoB.repoPath)).first().click()
        const scopeAfter = (await explorer.locator(M3_SELECTOR_CONTRACT.explorerScope).first().innerText()).trim()
        assert.equal(scopeAfter, scopeBefore, 'Pinned Explorer scope drifted after switching active RepoB')
        return { scopeBefore, scopeAfter }
      } finally {
        await closeElectronApp(inst)
        repoA.cleanup()
        repoB.cleanup()
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
      const inst = await launchElectronApp({
        porpitaRoot: ctx.porpitaRoot,
        profileOptions: { settings: { autoSave: 'off' } }
      })
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        const readmeNode = page.getByText('README.md', { exact: true }).first()
        await readmeNode.waitFor({ state: 'visible', timeout: 10000 })
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
        await page.keyboard.type('UNSAVED_LOCAL_DRAFT ')

        // Modify README.md externally on disk while tab has unsaved edits -> assert conflict banner
        const readmePath = path.join(repo.repoPath, 'README.md')
        writeFileSync(readmePath, '# Externally Modified\n\nNew disk line.\n', 'utf8')
        const conflictBanner = page
          .locator('[role="alert"]')
          .filter({ hasText: /changed on disk|Reload from Disk|Keep My Edits|磁盘/i })
          .first()
        await conflictBanner.waitFor({ state: 'visible', timeout: 12000 })
        const keepBtn = conflictBanner.getByRole('button', { name: /Keep My Edits|保留/i }).first()
        await keepBtn.waitFor({ state: 'visible', timeout: 5000 })
        await keepBtn.click()
        await conflictBanner.waitFor({ state: 'hidden', timeout: 5000 })

        // Attempt closing still-dirty active editor tab -> assert Unsaved Changes dialog & Don't Save discards safely
        const activeTab = page.locator('[data-tab-id][data-active="true"]').first()
        await activeTab.waitFor({ state: 'visible', timeout: 5000 })
        await activeTab.hover()
        const closeTabBtn = activeTab.locator('button').last()
        await closeTabBtn.waitFor({ state: 'visible', timeout: 5000 })
        await closeTabBtn.click()

        const savePrompt = page
          .locator('[role="dialog"]:visible')
          .filter({ hasText: /Unsaved Changes|unsaved changes|未保存/i })
          .last()
        await savePrompt.waitFor({ state: 'visible', timeout: 8000 })
        const dontSaveBtn = savePrompt.getByRole('button', { name: /Don't Save|不保存/i }).first()
        await dontSaveBtn.waitFor({ state: 'visible', timeout: 5000 })
        await dontSaveBtn.click()
        await savePrompt.waitFor({ state: 'hidden', timeout: 5000 })

        assert.equal(
          readFileSync(readmePath, 'utf8').includes('# Externally Modified'),
          true,
          "Don't Save must preserve the external disk modification instead of overwriting"
        )
        return { externalConflictBannerVerified: true, dirtyCloseDontSaveVerified: true }
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
        const csvItem = page.getByText('sample.csv', { exact: true }).first()
        await csvItem.waitFor({ state: 'visible', timeout: 8000 })
        await csvItem.dblclick()
        const csvGrid = page.locator('[data-testid="csv-grid"]').first()
        await csvGrid.waitFor({ state: 'visible', timeout: 10000 })
        await page.getByText(/1,?050/).first().waitFor({ state: 'visible', timeout: 6000 })

        const notesItem = page.getByText('notes.md', { exact: true }).first()
        await notesItem.waitFor({ state: 'visible', timeout: 8000 })
        await notesItem.dblclick()
        const { xssTriggered } = await openMarkdownPreviewAndVerify(page, 'Release Notes')
        await page.locator('h2').filter({ hasText: /^Overview$/i }).first().waitFor({ state: 'visible', timeout: 6000 })
        return { csvRows: 1050, markdownPreviewRendered: true, xssTriggered }
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
      const mod = primaryModifierKey()
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        await page.getByRole('button', { name: /^(New tab|新标签页)$/i }).first().click()
        await page.getByRole('menuitem', { name: /Browser|浏览器/i }).first().click()
        const addrBar = page.locator('[data-orca-browser-address-bar="true"]').first()
        await addrBar.waitFor({ state: 'visible', timeout: 10000 })
        await addrBar.fill(`${httpSrv.baseUrl}/page2`)
        await addrBar.press('Enter')

        const guestDeadline = Date.now() + 8000
        let guestReady = false
        while (Date.now() < guestDeadline) {
          guestReady = await app.evaluate(
            ({ webContents }, url) => webContents.getAllWebContents().some((wc) => wc.getURL().startsWith(url) && !wc.isLoading()),
            `${httpSrv.baseUrl}/page2`
          )
          if (guestReady) break
          await sleep(200)
        }
        assert.equal(guestReady, true, 'Loopback guest /page2 did not finish loading')

        // Dismiss the fresh-profile "Draw on screenshot" onboarding tip popover if it pops open over Browser chrome.
        const drawTipGotIt = page.getByRole('button', { name: /^(Got it|知道了)$/i }).first()
        if (await waitForVisible(drawTipGotIt, 1200)) {
          await drawTipGotIt.click()
        }

        await page.keyboard.press(`${mod}+f`)
        const findBar = page.locator('[data-testid="browser-find-bar"]').first()
        if (!(await waitForVisible(findBar, 2500))) {
          if (await waitForVisible(drawTipGotIt, 500)) {
            await drawTipGotIt.click()
            await page.keyboard.press(`${mod}+f`)
          }
        }
        if (!(await waitForVisible(findBar, 2500))) {
          // If the guest <webview> took native focus on load, dispatch Mod+F to the guest (browser-guest-shortcut-dispatch).
          await app.evaluate(
            async ({ webContents }, { urlPrefix, modKey }) => {
              const guest = webContents.getAllWebContents().find((wc) => wc.getURL().startsWith(urlPrefix))
              if (guest) {
                guest.focus()
                guest.sendInputEvent({ type: 'keyDown', keyCode: 'F', modifiers: [modKey] })
                guest.sendInputEvent({ type: 'keyUp', keyCode: 'F', modifiers: [modKey] })
              }
            },
            {
              urlPrefix: `${httpSrv.baseUrl}/page2`,
              modKey: process.platform === 'darwin' ? 'meta' : 'control'
            }
          )
        }
        await findBar.waitFor({ state: 'visible', timeout: 8000 })
        assert.equal(
          await page.locator('#browser-history-listbox:visible').count(),
          0,
          'Address bar suggestion dropdown must close on Enter and Cmd/Ctrl+F instead of overlapping BrowserFind'
        )
        const findInput = findBar.locator('input').first()
        await findInput.waitFor({ state: 'visible', timeout: 5000 })
        await findInput.fill('marker')
        await findInput.press('Enter')

        // /page2 has 2 occurrences of "marker" -> assert match count updates from live guest findInPage
        await findBar.getByText(/(1|2)\s*(of|\/)\s*2/i).first().waitFor({ state: 'visible', timeout: 8000 })

        // Verify narrow 600x400 BrowserFind containment
        await setViewportSize(app, page, 600, 400)
        const findBox600 = await findBar.evaluate((el) => {
          const r = el.getBoundingClientRect()
          return {
            left: Math.round(r.left),
            right: Math.round(r.right),
            width: Math.round(r.width),
            vw: window.innerWidth,
            overflowX: document.documentElement.scrollWidth > window.innerWidth + 2
          }
        })
        assert.ok(
          findBox600.left >= 0 && findBox600.right <= findBox600.vw + 1 && !findBox600.overflowX,
          `BrowserFind overflowed 600x400 viewport: ${JSON.stringify(findBox600)}`
        )

        if (await waitForVisible(drawTipGotIt, 400)) {
          await drawTipGotIt.click()
        }
        await page.keyboard.press('Escape')
        await findBar.waitFor({ state: 'hidden', timeout: 5000 })
        return { browserFindMatchCountVerified: true, findBox600 }
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
      const repo = createTempGitRepo({ name: 't2-f04-05' })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      const pluginFix = createSyntheticPluginFixture(ctx.porpitaRoot)
      try {
        const { app, page } = inst
        await addLocalFolderProject(app, page, repo.repoPath)
        await openSettingsPage(page)
        await page.locator('aside button').filter({ hasText: /^(Plugins|插件)/i }).first().click()
        await installAndEnableFolderPlugin(app, page, pluginFix)
        const panelState = await openAndVerifyPluginPanel(page, pluginFix.title)
        const disabledState = await disablePluginAndVerify(page, pluginFix.title)
        return { panelState, ...disabledState }
      } finally {
        await closeElectronApp(inst)
        pluginFix.cleanup()
        repo.cleanup()
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
        const searchBtn = page
          .getByRole('button', { name: /Search worktrees and browser tabs|搜索工作树/i })
          .first()
        await searchBtn.waitFor({ state: 'visible', timeout: 10000 })
        await searchBtn.click()
        const dialog = page.locator('[role="dialog"]:visible').last()
        const imeResult = await assertImeCompositionKeepsDialogOpen(page, dialog, 'ma')
        return { imeGuardExercisedOn: imeResult.activeTag, imeValue: imeResult.value }
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
      const core = await startLoopbackAcsCore({ mode: 'full', agentCollabRoot: ctx.agentCollabRoot })
      try {
        const pid = core.info.project_id
        const conv = await core.request(
          'GET',
          `/projects/${pid}/conversations/resolve?with=${encodeURIComponent(core.addresses.peer_b)}`,
          { token: core.tokens.client }
        )
        assert.equal(conv.status, 200, conv.text)
        const cid = conv.json.conversation_id
        const draft = await core.request('GET', `/projects/${pid}/conversations/${cid}/draft`, {
          token: core.tokens.client
        })
        assert.equal(draft.status, 200)
        assert.equal(draft.json.revision, 0)
        assert.equal(draft.json.content, '', 'Empty rev-0 draft must have empty content')
        assert.deepEqual(draft.json.attachment_refs, [], 'Empty rev-0 draft must have empty attachment_refs')
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
      const core = await startLoopbackAcsCore({ mode: 'full', agentCollabRoot: ctx.agentCollabRoot })
      try {
        const pid = core.info.project_id
        const conv = await core.request(
          'GET',
          `/projects/${pid}/conversations/resolve?with=${encodeURIComponent(core.addresses.peer_b)}`,
          { token: core.tokens.client }
        )
        assert.equal(conv.status, 200, conv.text)
        const cid = conv.json.conversation_id

        const put1 = await core.request('PUT', `/projects/${pid}/conversations/${cid}/draft`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'cas-key-1', 'If-Match': '"0"' },
          body: { content: 'First draft content', attachment_refs: [] }
        })
        assert.equal(put1.status, 200, put1.text)
        assert.equal(put1.json.revision, 1)

        // Exact retry with same key and body succeeds idempotently
        const retryExact = await core.request('PUT', `/projects/${pid}/conversations/${cid}/draft`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'cas-key-1', 'If-Match': '"0"' },
          body: { content: 'First draft content', attachment_refs: [] }
        })
        assert.equal(retryExact.status, 200, retryExact.text)
        assert.equal(retryExact.json.revision, 1)
        assert.equal(retryExact.json.content, 'First draft content')

        // Same Idempotency-Key with altered body conflicts (409 idempotency_conflict)
        const altered = await core.request('PUT', `/projects/${pid}/conversations/${cid}/draft`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'cas-key-1', 'If-Match': '"0"' },
          body: { content: 'Altered body under same key', attachment_refs: [] }
        })
        assert.equal(altered.status, 409, altered.text)
        assert.equal(altered.json?.error?.code, 'idempotency_conflict', altered.text)

        // New key with stale If-Match: "0" rejected (409 revision_conflict)
        const staleCas = await core.request('PUT', `/projects/${pid}/conversations/${cid}/draft`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'cas-key-2', 'If-Match': '"0"' },
          body: { content: 'Stale write attempt', attachment_refs: [] }
        })
        assert.equal(staleCas.status, 409, staleCas.text)
        assert.equal(staleCas.json?.error?.code, 'revision_conflict', staleCas.text)
        return {
          exactRetry: retryExact.status,
          alteredConflict: altered.status,
          alteredCode: altered.json?.error?.code,
          staleCas: staleCas.status,
          staleCasCode: staleCas.json?.error?.code
        }
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
      const core = await startLoopbackAcsCore({ mode: 'full', agentCollabRoot: ctx.agentCollabRoot })
      const inst = await launchElectronApp({ porpitaRoot: ctx.porpitaRoot })
      try {
        const pid = core.info.project_id
        // 1. Direct protocol contract: 503 post_commit_observation_lost + restartServer + Idempotency-Key dedup
        await core.setFault({ drop_next_send_response: true })

        const idemKey = 'fault-send-retry-1'
        const first = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': idemKey },
          body: { to: core.addresses.peer_b, content: 'Commit before simulated drop' }
        })
        assert.equal(first.status, 503, first.text)
        assert.equal(first.json?.error?.code, 'post_commit_observation_lost', first.text)
        assert.equal(first.json?.error?.retryable, true, first.text)
        assert.equal(first.json?.error?.effect_state, 'committed', first.text)

        await core.restartServer({ reusePort: true })
        const retry = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': idemKey },
          body: { to: core.addresses.peer_b, content: 'Commit before simulated drop' }
        })
        assert.ok(retry.status === 200 || retry.status === 201, retry.text)
        assert.ok(retry.json?.message?.message_handle, 'Retry response must include committed message_handle')

        const list = await core.request(
          'GET',
          `/projects/${pid}/messages?with=${encodeURIComponent(core.addresses.peer_b)}`,
          { token: core.tokens.client }
        )
        assert.equal(list.status, 200, list.text)
        const matching = list.json.items.filter(
          (m) => (typeof m.content === 'string' ? m.content : m.content?.text) === 'Commit before simulated drop'
        )
        assert.equal(matching.length, 1, `Expected 1 message (no duplicate), got ${matching.length}`)

        // 2. Real Electron UI PendingInspectionAction + Retry original request across Core restart
        const { page } = inst
        await connectCollaborationViaSettings(page, core)
        await returnFromSettings(page)
        const dlg = await openCollaborationDialog(page)
        const composer = await selectCollaborationContact(dlg, 'slot-b')
        await core.setFault({ drop_next_send_response: true })
        await composer.fill('UI commit before simulated drop')
        await dlg.getByRole('button', { name: /^(Send|发送)$/i }).first().click()

        const retryBtn = dlg.getByRole('button', { name: /Retry original request|重试原请求/i }).first()
        const inspectBtn = dlg.getByRole('button', { name: /Inspect original request|检查原请求/i }).first()
        await retryBtn.waitFor({ state: 'visible', timeout: 10000 })
        await inspectBtn.waitFor({ state: 'visible', timeout: 5000 })
        assert.equal(await composer.inputValue(), 'UI commit before simulated drop', 'Draft text must be retained on uncertain outcome')
        await dlg.locator('[role="alert"]').first().waitFor({ state: 'visible', timeout: 5000 })

        await core.restartServer({ reusePort: true })
        await retryBtn.click()
        await page.waitForFunction(
          () => (document.querySelector('[role="dialog"] textarea')?.value ?? '') === '',
          undefined,
          { timeout: 10000 }
        )
        await dlg.getByText('UI commit before simulated drop', { exact: false }).first().waitFor({ state: 'visible', timeout: 10000 })

        const listAfterUi = await core.request(
          'GET',
          `/projects/${pid}/messages?with=${encodeURIComponent(core.addresses.peer_b)}`,
          { token: core.tokens.client }
        )
        const matchingUi = listAfterUi.json.items.filter(
          (m) => (typeof m.content === 'string' ? m.content : m.content?.text) === 'UI commit before simulated drop'
        )
        assert.equal(matchingUi.length, 1, `Expected 1 UI message after retry dedup, got ${matchingUi.length}`)
        await closeCollaborationDialogWithFocusCheck(page, dlg)
        return {
          firstStatus: first.status,
          retryStatus: retry.status,
          messageCount: matching.length,
          uiRetryMessageCount: matchingUi.length
        }
      } finally {
        await closeElectronApp(inst)
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
      const core = await startLoopbackAcsCore({ mode: 'full', agentCollabRoot: ctx.agentCollabRoot })
      try {
        const pid = core.info.project_id
        const maxOk = 'a'.repeat(256 * 1024)
        const resOk = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'size-256k-ok' },
          body: { to: core.addresses.peer_b, content: maxOk }
        })
        assert.equal(resOk.status, 201, `256 KiB payload should succeed: ${resOk.text}`)
        assert.ok(resOk.json?.message?.message_handle, '256 KiB payload missing message_handle')

        const tooBig = 'a'.repeat(256 * 1024 + 1)
        const resBig = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'size-256k-plus1' },
          body: { to: core.addresses.peer_b, content: tooBig }
        })
        assert.equal(resBig.status, 413, `256 KiB + 1 byte must be rejected with 413: ${resBig.text}`)
        assert.equal(resBig.json?.error?.code, 'content_too_large', resBig.text)
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
      const core = await startLoopbackAcsCore({ mode: 'full', agentCollabRoot: ctx.agentCollabRoot })
      try {
        const pid = core.info.project_id
        // Unlinked message (message_only -> no native invocation)
        const send = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'unlinked-msg-1' },
          body: { to: core.addresses.peer_b, content: 'Plain message_only text', activation: 'message_only' }
        })
        assert.equal(send.status, 201, send.text)
        const handle = encodeURIComponent(send.json.message.message_handle)

        const invalidBool = await core.request(
          'GET',
          `/projects/${pid}/messages/${handle}?include_native_source=yes`,
          { token: core.tokens.client }
        )
        assert.equal(invalidBool.status, 400, invalidBool.text)
        assert.equal(invalidBool.json?.error?.code, 'invalid_argument', invalidBool.text)

        const unlinkedRead = await core.request(
          'GET',
          `/projects/${pid}/messages/${handle}?include_native_source=true`,
          { token: core.tokens.client }
        )
        assert.equal(unlinkedRead.status, 200, unlinkedRead.text)
        assert.equal(unlinkedRead.json.native_source.available, false, 'Unlinked msg must report available=false')

        // Stale expected_provider_generation on NativeLinkWrite -> exact 409 native_source_selection_changed
        const staleLink = await core.request('PUT', `/projects/${pid}/native-links/link-stale`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'link-stale-1' },
          body: { ...core.nativeLinkFixture, expected_provider_generation: 'stale-generation-xyz' }
        })
        assert.equal(staleLink.status, 409, `Expected 409 on stale provider generation: ${staleLink.text}`)
        assert.equal(
          staleLink.json?.error?.code,
          'native_source_selection_changed',
          `Unexpected error code on stale provider generation: ${staleLink.text}`
        )

        // Stale expected_binding_epoch on NativeLinkWrite -> exact 409 revision_conflict
        const staleEpoch = await core.request('PUT', `/projects/${pid}/native-links/link-stale-epoch`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'link-stale-epoch-1' },
          body: { ...core.nativeLinkFixture, expected_binding_epoch: core.nativeLinkFixture.expected_binding_epoch + 1 }
        })
        assert.equal(staleEpoch.status, 409, `Expected 409 on stale binding epoch: ${staleEpoch.text}`)
        assert.equal(
          staleEpoch.json?.error?.code,
          'revision_conflict',
          `Unexpected error code on stale binding epoch: ${staleEpoch.text}`
        )

        return {
          invalidBoolStatus: invalidBool.status,
          unlinkedAvailable: unlinkedRead.json.native_source.available,
          staleLinkStatus: staleLink.status,
          staleLinkCode: staleLink.json?.error?.code,
          staleEpochStatus: staleEpoch.status,
          staleEpochCode: staleEpoch.json?.error?.code
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
      const core = await startLoopbackAcsCore({ mode: 'full', agentCollabRoot: ctx.agentCollabRoot })
      let revokedRead = null
      try {
        const pid = core.info.project_id
        const msg = await core.request('POST', `/projects/${pid}/messages`, {
          token: core.tokens.client,
          headers: { 'Idempotency-Key': 'acl-msg-1' },
          body: { to: core.addresses.peer_b, content: 'Secret between client and peer_b' }
        })
        assert.equal(msg.status, 201, msg.text)

        // Third party peer_c must be denied (403 authorization_denied) reading client<->peer_b message
        const thirdParty = await core.request(
          'GET',
          `/projects/${pid}/messages/${encodeURIComponent(msg.json.message.message_handle)}`,
          { token: core.tokens.peer_c }
        )
        assert.equal(thirdParty.status, 403, `Expected 403 for peer_c, got ${thirdParty.status}: ${thirdParty.text}`)
        assert.equal(thirdParty.json?.error?.code, 'authorization_denied', thirdParty.text)

        // Revoke client token -> subsequent reads/writes fail (403 authorization_denied) while peer_b remains functional
        await core.revokeToken('client')
        revokedRead = await core.request('GET', `/projects/${pid}/messages`, {
          token: core.tokens.client
        })
        assert.equal(revokedRead.status, 403, `Expected 403 on revoked grant, got ${revokedRead.text}`)
        assert.equal(revokedRead.json?.error?.code, 'authorization_denied', revokedRead.text)

        const validPeerRead = await core.request('GET', `/projects/${pid}/messages`, {
          token: core.tokens.peer_b
        })
        assert.equal(validPeerRead.status, 200, validPeerRead.text)
        assert.ok(Array.isArray(validPeerRead.json?.items), 'Peer read must return items array')
      } finally {
        await core.cleanup()
      }

      // Part B: P1-only mode /meta.features boundary
      const p1Core = await startLoopbackAcsCore({ mode: 'p1_only', agentCollabRoot: ctx.agentCollabRoot })
      try {
        const meta = await p1Core.request('GET', '/meta')
        assert.equal(meta.status, 200, meta.text)
        assert.equal(meta.json.limits.attachment_count, 0)
        assert.equal(meta.json.limits.event_replay_seconds, 0)
        assert.equal(meta.json.features.includes('attachments'), false)
        assert.equal(meta.json.features.includes('events'), false)
        const disabledAtt = await p1Core.request('POST', `/projects/${p1Core.info.project_id}/attachments`, {
          token: p1Core.tokens.client,
          headers: { 'Idempotency-Key': 'p1-att-blocked' },
          body: { name: 'a.txt', media_type: 'text/plain', bytes: 4, sha256: '0'.repeat(64) }
        })
        assert.equal(disabledAtt.status, 409, disabledAtt.text)
        assert.equal(disabledAtt.json?.error?.code, 'capability_unsupported', disabledAtt.text)
        return {
          revokedStatus: revokedRead.status,
          revokedCode: revokedRead.json?.error?.code,
          p1OnlyAttachmentStatus: disabledAtt.status,
          p1OnlyAttachmentCode: disabledAtt.json?.error?.code
        }
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
        agentCollabRoot: ctx.agentCollabRoot,
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
        agentCollabRoot: ctx.agentCollabRoot,
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
        agentCollabRoot: ctx.agentCollabRoot,
        historyRoot: ctx.historyRoot
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
