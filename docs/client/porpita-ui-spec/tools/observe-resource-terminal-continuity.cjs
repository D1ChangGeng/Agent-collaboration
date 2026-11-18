const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

async function observeResourceTerminalContinuity({
  browser, caption, waits, step, episode, preview, enterPreview, setSize, selectedChat, poll,
  localWorkspace, remoteWorkspace, studioHost, localRoot, desktopApp, openNativeWorktree,
  studioPanelId, selectStudio, checks
}) {
  const selectionContinuity = process.argv.includes('--resource-selection-continuity')
  const cleanupContinuity = process.argv.includes('--space-cleanup-continuity')
  const page = browser()
  const studio = preview().locator('[data-workspace-preview-explorer]').filter({
    has: page.getByRole('option', { name: 'release.md', exact: true })
  })
  const manager = page.getByRole('dialog', {
    name: caption('Resource Manager', '资源管理器'), exact: true
  })
  const monitor = () => page.locator('[data-orca-status-bar]').getByRole('button', {
    name: caption(/local memory/, /本机内存/)
  })
  const openManager = async (view) => {
    await monitor().click(waits)
    await manager.waitFor(waits)
    const name = view === 'resources' ? caption(/^Resources$/, /^资源$/) : caption(/^Local PTYs/, /^本机 PTY/)
    await manager.getByRole('tab', { name }).click(waits)
    return manager.getByRole('tabpanel', { name })
  }
  const ptyRow = (list, sessionId) => {
    const prefix = JSON.stringify([sessionId]).slice(0, -1) + ','
    return list.locator('[data-resource-pty-row^=' + JSON.stringify(prefix) + ']')
  }
  const openTerminal = row => row.getByRole('button', { name: caption(/^Open /, /^打开 /) })
  const native = await desktopApp().browserWindow(page)
  const hidden = { ...waits, state: 'hidden' }
  let terminal
  const managedWorktrees = {}

  async function readTerminal(tabId) {
    return page.evaluate(id => {
      const state = window.__store.getState()
      const manager = window.__paneManagers?.get(id)
      const active = manager?.getActivePane()
      return {
        tabId: state.activeTabId,
        activeLeaf: active?.leafId ?? null,
        terminalFocus: Boolean(active?.container.contains(document.activeElement)),
        panes: (manager?.getPanes() ?? []).map(pane => ({
          leaf: pane.leafId, pty: pane.container.dataset.ptyId ?? null
        }))
      }
    }, tabId)
  }

  async function requireStudioPreview() {
    await studio.waitFor(waits)
    assert.equal(await studio.getAttribute('data-workspace-preview-explorer'), studioPanelId)
  }

  async function useDiagnosticFixture(allowed) {
    // Same diagnostic fixture as resource-manager-bound-ptys.spec; no native activation.
    const windowStillHidden = await native.evaluate((window, enabled) => {
      if (enabled) {
        if (window.isVisible() || window.isFocused()) return false
        window.isVisible = () => true
        window.isMinimized = () => false
      } else {
        delete window.isVisible
        delete window.isMinimized
        if (window.isVisible() || window.isFocused()) return false
      }
      window.webContents.send('memory:resourceWindowVisibility', enabled)
      return true
    }, allowed)
    assert.ok(windowStillHidden, 'The native test window must remain hidden and unfocused')
    await page.evaluate(enabled => {
      if (enabled) {
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
      } else {
        delete document.visibilityState
      }
      document.dispatchEvent(new Event('visibilitychange'))
    }, allowed)
  }

  async function failDiagnosticFetch(enabled) {
    await desktopApp().evaluate(({ ipcMain }, fail) => {
      const channel = 'pty:listSessions'
      if (fail) {
        const original = ipcMain._invokeHandlers?.get(channel)
        if (!original || globalThis.__specPtyInventoryHandler) {
          throw new Error('The isolated PTY inventory handler is unavailable')
        }
        globalThis.__specPtyInventoryHandler = original
        ipcMain.removeHandler(channel)
        ipcMain.handle(channel, (event, scope, admission) => {
          if (scope?.includeUnrouted && admission?.resourceManagerView) {
            throw new Error('Intentional diagnostic refresh failure')
          }
          return original(event, scope, admission)
        })
      } else if (globalThis.__specPtyInventoryHandler) {
        ipcMain.removeHandler(channel)
        ipcMain.handle(channel, globalThis.__specPtyInventoryHandler)
        delete globalThis.__specPtyInventoryHandler
      }
      return true
    }, enabled)
  }

  async function captureSpaceWindow(space, child, filename = 'i41-space-window.jpg') {
    const cdp = await space.context().newCDPSession(space)
    try {
      await cdp.send('Page.enable')
      await child.evaluate(window => {
        window.webContents.setBackgroundThrottling(false)
        window.setContentSize(1100, 700)
      })
      await space.waitForFunction(() => innerWidth === 1100 && innerHeight === 700, null, waits)
      await space.evaluate(async () => {
        const dialog = document.querySelector('[role="dialog"][data-state="open"]')
        const transitions = dialog?.getAnimations({ subtree: true }).filter(animation =>
          animation.playState === 'running' && Number.isFinite(animation.effect?.getComputedTiming().endTime)
        ) ?? []
        await Promise.allSettled(transitions.map(animation => animation.finished))
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      })
      const image = await cdp.send('Page.captureScreenshot', {
        format: 'jpeg', quality: 88, fromSurface: true, captureBeyondViewport: false
      })
      assert.equal(await child.evaluate(window => !window.isVisible() && !window.isFocused()), true)
      fs.writeFileSync(path.join(process.argv[2], filename), Buffer.from(image.data, 'base64'))
    } finally {
      await cdp.detach().catch(() => {})
    }
  }

  async function requireTerminal(target) {
    await preview().waitFor(hidden)
    await manager.waitFor(hidden)
    await poll(selectedChat, value => value.workspaceId === localWorkspace &&
      (value.activeHost ?? 'local') === 'local', 'Resource navigation did not reveal the local worktree')
    const active = await poll(() => readTerminal(terminal.tabId), value =>
      value.tabId === terminal.tabId && value.activeLeaf === target.leaf && value.terminalFocus,
      'The original terminal pane did not receive keyboard focus').catch(async error => {
      const state = await readTerminal(terminal.tabId)
      throw new Error(error.message + '. Tab matched: ' + (state.tabId === terminal.tabId) +
        ', leaf matched: ' + (state.activeLeaf === target.leaf) + ', pane focus: ' + state.terminalFocus)
    })
    assert.deepEqual(active.panes, terminal.panes, 'The existing PTY bindings must be retained')
  }

  await useDiagnosticFixture(true)
  try {
    await step('i39-resource-terminal', 'Resume the exact terminal panes via Resources and Local PTYs', async () => {
      assert.ok(checks.resourceSetup)
      await selectStudio()
      await requireStudioPreview()
      await openNativeWorktree(localWorkspace, 'local')
      const tabId = await page.evaluate(worktreeId =>
        window.__store.getState().tabsByWorktree[worktreeId]?.[0]?.id, localWorkspace)
      assert.ok(tabId, 'The loopback Local worktree has an original native terminal')
      await page.locator('[data-testid=sortable-tab][data-tab-id=' + JSON.stringify(tabId) + ']')
        .first().click(waits)
      await page.locator('.xterm-helper-textarea:visible').first().focus(waits)
      await page.keyboard.press('Control+Shift+d')
      terminal = await poll(() => readTerminal(tabId), value =>
        value.tabId === tabId && value.panes.length === 2 &&
        value.panes.every(pane => pane.pty) && value.activeLeaf === value.panes[1].leaf,
        'The actual terminal must have two distinct bound panes')
      assert.notEqual(terminal.panes[0].pty, terminal.panes[1].pty)
      await openNativeWorktree(remoteWorkspace, studioHost)
      await enterPreview()
      await selectStudio()
      await requireStudioPreview()

      const [first, second] = terminal.panes
      await episode('resource-to-original-terminal', [
        ['Read the resource tree and select the first real PTY', async () => {
          const tree = await openManager('resources')
          const row = tree.getByRole('button', { name: caption(/^Open /, /^打开 /) }).filter({
            has: page.getByRole('button', { name: new RegExp(first.pty.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) })
          })
          await row.waitFor(waits)
          assert.ok((await row.getAttribute('aria-label')).endsWith(caption('Pane 1', '窗格 1')))
          await row.focus()
        }],
        ['Activate the first pane from Resources', async () => {
          await page.keyboard.press('Enter')
          await requireTerminal(first)
        }],
        ['Select the other PTY from the local inventory', async () => {
          await enterPreview()
          await requireStudioPreview()
          const list = await openManager('ptys')
          const row = ptyRow(list, second.pty)
          await openTerminal(row).waitFor(waits)
          assert.ok((await openTerminal(row).getAttribute('aria-label')).endsWith(caption('Pane 2', '窗格 2')))
          await openTerminal(row).press('Space', waits)
          await requireTerminal(second)
        }],
        ['Return to the same Studio Explorer', async () => {
          await enterPreview()
          await requireStudioPreview()
        }]
      ])
      checks.terminalNavigation = { sameTab: true, bothOriginalPanes: true, distinctLabels: true, keyboardFocus: true, originalExplorer: true }
    })

    await step('i40-pty-availability', 'Review local binding and recover the real PTY inventory after a failed read', async () => {
      assert.ok(terminal?.panes.length === 2, 'The real terminal fixture must exist')
      if (await manager.isVisible()) {
        await page.keyboard.press('Escape')
        await manager.waitFor(hidden)
      }
      if (!(await preview().isVisible())) await enterPreview()
      await selectStudio()
      await requireStudioPreview()
      if (process.argv.includes('--compact-port-inspection')) {
        await setSize(600, 460)
        await page.emulateMedia({ reducedMotion: 'reduce' })
      }
      const unbound = await page.evaluate(({ cwd, worktreeId }) =>
        window.api.pty.spawn({ cols: 80, rows: 24, cwd, worktreeId, initiallyHidden: true }),
        { cwd: localRoot, worktreeId: localWorkspace })
      try {
        let list
        let original
        await episode('local-pty-availability', [
          ['Compare a real tab-less PTY and a bound pane', async () => {
            list = await openManager('ptys')
            const orphan = ptyRow(list, unbound.id)
            original = ptyRow(list, terminal.panes[0].pty)
            await orphan.getByText(caption('No tab', '无标签页'), { exact: true }).waitFor(waits)
            assert.equal(await openTerminal(orphan).count(), 0)
            await openTerminal(original).waitFor(waits)
          }],
          ['Fail a diagnostic read and inspect the retained list without navigation actions', async () => {
            await failDiagnosticFetch(true)
            await manager.getByRole('button', { name: caption('Refresh', '刷新'), exact: true }).first().click(waits)
            const alert = list.getByRole('alert').filter({
              hasText: caption('Last-observed terminals are shown.', '正在显示上次观察到的终端。')
            })
            await alert.waitFor(waits)
            await original.waitFor(waits)
            assert.equal(await openTerminal(original).count(), 0)
            await requireStudioPreview()
          }],
          ['Retry through the original control and recover the actual bound PTY', async () => {
            await failDiagnosticFetch(false)
            await list.getByRole('button', { name: caption('Retry', '重试'), exact: true }).press('Enter', waits)
            await openTerminal(original).waitFor(waits)
            await requireStudioPreview()
          }]
        ])
        checks.ptyAvailability = { tablessProcess: true, retainedFailureSample: true, navigationRestoredOnRetry: true }
      } finally {
        await failDiagnosticFetch(false)
        await page.evaluate(id => window.api.pty.kill(id), unbound.id)
      }
    })
    if (selectionContinuity) {
      await step('i42-pty-eligible-selection', 'Use the PTY bulk controls in three selection states', async () => {
        assert.ok(checks.ptyAvailability)
        const list = manager.getByRole('tabpanel', { name: caption(/^Local PTYs/, /^本机 PTY/) })
        const rows = terminal.panes.map(pane => ptyRow(list, pane.pty).getByRole('checkbox'))
        const all = list.getByRole('checkbox', {
          name: caption('Select all eligible terminals', '全选可结束的终端'),
          exact: true
        })
        const end = count => list.getByRole('button', {
          name: caption('End selected (' + count + ')', '结束所选终端（' + count + '）'),
          exact: true
        })
        const check = (count, state) => poll(async () => ({
          all: await all.getAttribute('aria-checked'),
          endExists: await end(count).count() === 1,
          checkedRows: (await Promise.all(rows.map(row => row.getAttribute('aria-checked'))))
            .filter(value => value === 'true').length
        }), value => value.all === state && value.endExists && value.checkedRows === count,
        'The eligible PTY selection did not reach the expected scope')
        await episode('pty-eligible-selection', [
          ['Read the empty selection', async () => {
            await poll(() => list.locator('[data-resource-pty-row]').count(), count => count === 2,
              'The disposable unbound PTY is still present')
            await check(0, 'false')
            assert.equal(await end(0).isDisabled(), true)
          }],
          ['Select one of the two original panes by keyboard', async () => {
            await rows[0].press('Space', waits)
            await check(1, 'mixed')
          }],
          ['Select all eligible terminals and then clear using the same control', async () => {
            await all.press('Space', waits)
            await check(2, 'true')
            assert.equal(await end(2).isEnabled(), true)
            await all.press('Space', waits)
            await check(0, 'false')
            assert.equal(await end(0).isDisabled(), true)
            await requireStudioPreview()
          }]
        ])
        checks.ptySelection = { originalPanes: 2, keyboard: true, states: ['false', 'mixed', 'true', 'false'] }
      })
    }
  } finally {
    if (await manager.isVisible()) {
      await page.keyboard.press('Escape')
      await manager.waitFor(hidden)
    }
    await useDiagnosticFixture(false)
  }

  await step('i41-space-review', 'Review a completed disk scan in the Space window and retain Studio Explorer', async () => {
    if (selectionContinuity) {
      const managedRoot = path.join(path.dirname(localRoot), 'managed-worktrees')
      const names = cleanupContinuity
        ? ['review-alpha', 'review-beta', 'review-gamma']
        : ['review-alpha', 'review-beta']
      const createdPaths = await page.evaluate(async ({ localWorkspace, managedRoot, names }) => {
        const state = window.__store.getState()
        const local = state.getKnownWorktreeById(localWorkspace, 'local')
        const normalize = value => value?.replaceAll('\\', '/').toLowerCase()
        if (!local?.repoId || normalize(state.settings?.workspaceDir) !== normalize(managedRoot)) {
          throw new Error('The local disposable workspace directory was not configured')
        }
        const paths = []
        for (const name of names) {
          const created = await state.createWorktree(local.repoId, name, 'main', 'skip')
          paths.push({ name, path: created.worktree.path })
        }
        return paths
      }, { localWorkspace, managedRoot, names })
      for (const created of createdPaths) {
        const relative = path.relative(fs.realpathSync(managedRoot), fs.realpathSync(created.path))
        assert.ok(relative && !relative.startsWith('..') && !path.isAbsolute(relative),
          'The created worktree is outside the isolated directory')
        managedWorktrees[created.name] = created.path
      }
    }
    if (!(await preview().isVisible())) await enterPreview()
    await selectStudio()
    await requireStudioPreview()
    const contents = await openManager('resources')
    const review = contents.getByRole('button', {
      name: caption('Review in Space', '在空间管理中查看'), exact: true
    })
    const originalAction = () => page.evaluate(() => {
      if (window.__specOriginalSpaceAction) {
        window.__store.setState({ openSpacePage: window.__specOriginalSpaceAction })
        delete window.__specOriginalSpaceAction
        delete window.__specRejectSpace
      }
    })
    let space
    try {
      await episode('resources-to-space', [
        ['Scan the disposable worktree and read the summary', async () => {
          await contents.getByRole('button', { name: caption('Scan', '扫描'), exact: true }).click(waits)
          await poll(() => page.evaluate(() => {
            const { workspaceSpaceAnalysis, workspaceSpaceScanning } = window.__store.getState()
            return { running: workspaceSpaceScanning, count: workspaceSpaceAnalysis?.scannedWorktreeCount ?? 0 }
          }), value => !value.running && value.count > 0, 'No real workspace disk-scan result')
        }],
        ['Keep the resource panel during a pending open and display a retriable error', async () => {
          await page.evaluate(() => {
            const store = window.__store
            window.__specOriginalSpaceAction = store.getState().openSpacePage
            store.setState({ openSpacePage: () => new Promise((_, reject) => {
              window.__specRejectSpace = reject
            }) })
          })
          await review.press('Enter', waits)
          await page.waitForFunction(() => document.activeElement?.getAttribute('aria-busy') === 'true',
            null, waits)
          await page.evaluate(() => window.__specRejectSpace(new Error('Intentional Space open failure')))
          await contents.getByRole('alert').filter({
            hasText: caption('Could not open Space. Try again.', '无法打开空间管理。请重试。')
          }).waitFor(waits)
          assert.equal(await review.evaluate(node => document.activeElement === node), true)
          await requireStudioPreview()
        }],
        ['Retry and open the actual separate Space window with the scan result', async () => {
          await originalAction()
          const existing = new Set(desktopApp().windows())
          ;[space] = await Promise.all([
            desktopApp().waitForEvent('window', { predicate: candidate => !existing.has(candidate), timeout: 14000 }),
            review.press('Enter', waits)
          ])
          await space.waitForLoadState('domcontentloaded', waits)
          assert.ok(new URL(space.url()).pathname.endsWith('/space.html'))
          const child = await desktopApp().browserWindow(space)
          assert.equal(await child.evaluate(window => !window.isVisible() && !window.isFocused()), true)
          await space.getByPlaceholder(caption('Filter workspaces', '搜索工作区')).waitFor(waits)
          await space.getByText('Release-review', { exact: true }).first().waitFor(waits)
          await captureSpaceWindow(space, child)
          await manager.waitFor(hidden)
          await requireStudioPreview()
          await child.evaluate(window => window.close())
          await requireStudioPreview()
        }]
      ])
      checks.spaceReview = { actualScan: true, pendingAndRetry: true, realHiddenWindow: true, originalExplorer: true }
    } finally {
      await originalAction()
      if (space && !space.isClosed()) {
        const child = await desktopApp().browserWindow(space)
        await child.evaluate(window => window.close())
      }
    }
  })
  if (selectionContinuity) {
    const { observeSpaceSelection } = require('./observe-space-selection.cjs')
    await observeSpaceSelection({
      caption, waits, step, poll, desktopApp, openManager, requireStudioPreview,
      captureSpaceWindow, checks, managedWorktrees
    })
  }
  if (await manager.isVisible()) {
    await page.keyboard.press('Escape')
    await manager.waitFor(hidden)
  }
  await setSize(1280, 800)
  await page.emulateMedia({ reducedMotion: 'no-preference' })
}

module.exports = { observeResourceTerminalContinuity }
