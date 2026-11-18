const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { spawn } = require('node:child_process')

const fixtureServer = `const { createServer } = require('node:http')
const server = createServer((_, res) => {
  res.setHeader('Content-Type', 'text/html; charset=utf-8')
  res.end('<!doctype html><title>Porpita Loopback Fixture</title><main>Porpita UI SPEC loopback fixture</main>')
})
server.listen(0, '127.0.0.1', () => console.log(server.address().port))
`

async function startService(root) {
  const scriptPath = path.join(root, 'porpita-ports-fixture.cjs')
  fs.writeFileSync(scriptPath, fixtureServer)
  const child = spawn(process.execPath, [scriptPath], {
    cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'ignore']
  })
  const exited = new Promise(resolve => child.once('exit', resolve))
  let received = ''
  let timeout
  const port = await new Promise((resolve, reject) => {
    timeout = setTimeout(() => reject(new Error('Loopback fixture did not start')), 25000)
    child.once('error', reject)
    child.once('exit', () => reject(new Error('Loopback fixture exited before listening')))
    child.stdout.setEncoding('utf8')
    child.stdout.on('data', (part) => {
      received += part
      if (/^\d+\r?\n$/.test(received)) resolve(Number(received.trim()))
    })
  }).catch(error => {
    child.kill()
    throw error
  }).finally(() => clearTimeout(timeout))
  return { port, close: () => child.kill(), exited }
}

function createPortsReplay({ browser, caption, waits, hostName, localRoot, studioRoot }) {
  const bar = () => browser().locator('[data-orca-status-bar]')
  const title = host => host
    ? caption(`Ports on ${host}`, `${host} 的端口`)
    : caption('Ports', '端口')
  const refresh = caption('Refresh Ports', '刷新端口')
  const handoff = caption('Go to Worktree', '转到工作树')
  let local
  let studio
  let retiredPort
  let resourceSample

  async function open(host) {
    const name = title(host)
    await bar().getByRole('button', { name, exact: true }).click(waits)
    const popover = browser().getByRole('dialog', { name, exact: true })
    await popover.waitFor(waits)
    return popover
  }

  async function clearResourceSample() {
    if (resourceSample) {
      await browser().evaluate((previous) => window.__store.setState(previous), resourceSample)
      resourceSample = undefined
    }
  }
  async function close(popover) {
    await browser().keyboard.press('Escape')
    await popover.waitFor({ ...waits, state: 'hidden' })
    await clearResourceSample()
  }

  return {
    async start() {
      local = await startService(localRoot)
      studio = await startService(studioRoot)
    },
    async replaceStudio() {
      retiredPort = studio.port
      const replacement = await startService(studioRoot)
      studio.close()
      studio = replacement
    },
    async replaceLocal() {
      const previous = local
      local = await startService(localRoot)
      previous.close()
      await previous.exited
      return local.port
    },
    dispose() {
      studio?.close()
      local?.close()
    },
    async inspect(host, keepOpen = false) {
      assert.ok(local && studio, 'Both disposable listeners must be running')
      const own = host === hostName ? studio.port : local.port
      const other = host === hostName ? local.port : studio.port
      const popover = await open(host)
      try {
        await popover.getByText(String(own), { exact: true }).waitFor(waits)
      } catch (error) {
        const observed = await popover.innerText({ timeout: 1200 }).catch(() => 'Closed while the host reconnected')
        throw new Error(`Port ${own} missing for ${host}. Scoped panel: ${observed}\n${error.message}`)
      }
      assert.equal(await popover.getByText(String(other), { exact: true }).count(), 0)
      if (retiredPort) {
        assert.equal(await popover.getByText(String(retiredPort), { exact: true }).count(), 0)
      }
      assert.equal(await popover.getByRole('button', { name: caption('Stop Process', '停止进程'), exact: true }).count(), 0)
      if (!keepOpen) await close(popover)
      return own
    },
    async handoff(host) {
      await browser().getByRole('dialog', { name: title(host), exact: true })
        .getByRole('button', { name: handoff, exact: true }).press('Enter', waits)
    },
    async details(host, openPopover = null) {
      const port = host === hostName ? studio.port : local.port
      const popover = openPopover ?? await open(host)
      await popover.getByRole('button', {
        name: caption(`Inspect port :${port}`, `查看端口 :${port} 的详情`), exact: true
      }).press('Enter', waits)
      const dialog = browser().getByRole('dialog', { name: caption(`Port :${port}`, `端口：${port}`), exact: true })
      await dialog.waitFor(waits)
      await dialog.getByText(host, { exact: true }).waitFor(waits)
      await dialog.getByText(`127.0.0.1:${port}`, { exact: true }).first().waitFor(waits)
      return { dialog, port }
    },
    async closeDetails(host, dialog) {
      await close(dialog)
      await browser().waitForFunction(
        label => document.activeElement?.getAttribute('aria-label') === label, title(host), waits
      )
    },
    async disconnected() {
      const popover = await open(hostName)
      await popover.getByRole('status').filter({ hasText: caption(`${hostName} offline`, `${hostName} 已离线`) }).waitFor(waits)
      assert.equal(await popover.getByRole('button', { name: refresh, exact: true }).count(), 0)
      assert.equal(await popover.getByText(String(studio.port), { exact: true }).count(), 0)
      await close(popover)
    },
    async revoked(keepOpen = false) {
      const popover = await open(null)
      await popover.getByRole('status').filter({ hasText: caption('Worktree ports unavailable', '工作树端口不可用') }).waitFor(waits)
      assert.doesNotMatch(await popover.innerText(), /Studio/)
      assert.equal(await popover.getByRole('button', { name: handoff, exact: true }).count(), 0)
      if (!keepOpen) await close(popover)
    },
    async resources(keepOpen = false, sampleWorktreeId = null) {
      await bar().getByRole('button', { name: caption(/local memory/, /本机内存/) }).click(waits)
      const popover = browser().getByRole('dialog', { name: caption('Resource Manager', '资源管理器'), exact: true })
      await popover.waitFor(waits)
      const resourceTab = popover.getByRole('tab', { name: caption('Resources', '资源'), exact: true })
      await resourceTab.click(waits)
      await popover.getByText(caption('Local summary', '本机汇总'), { exact: true }).waitFor(waits)
      const ptys = popover.getByRole('tab', { name: caption(/^Local PTYs/, /^本机 PTY/) })
      await ptys.click(waits)
      assert.equal(await ptys.getAttribute('aria-selected'), 'true')
      await resourceTab.click(waits)
      if (keepOpen) {
        // Hidden test windows do not admit native resource polling. Use a representative sample for layout.
        resourceSample = await browser().evaluate((worktreeId) => {
          const store = window.__store
          const { memorySnapshot, memorySnapshotError } = store.getState()
          const mb = 1024 * 1024
          const worktree = worktreeId && store.getState().getKnownWorktreeById(worktreeId, 'local')
          if (worktreeId && !worktree) throw new Error('The resource fixture needs the original local worktree')
          store.setState({
            memorySnapshotError: null,
            memorySnapshot: {
              app: {
                cpu: 12, memory: 320 * mb, privateMemory: 440 * mb,
                main: { cpu: 4, memory: 120 * mb },
                renderer: { cpu: 7, memory: 160 * mb },
                other: { cpu: 1, memory: 40 * mb },
                history: [280 * mb, 320 * mb]
              },
              worktrees: worktree ? [{
                worktreeId: worktree.id, worktreeName: worktree.displayName,
                repoId: worktree.repoId, repoName: 'Release-review', cpu: 2,
                memory: 48 * mb, history: [40 * mb, 48 * mb], sessions: []
              }] : [],
              host: {
                totalMemory: 16 * 1024 * mb, freeMemory: 8 * 1024 * mb, availableMemory: 8 * 1024 * mb,
                usedMemory: 8 * 1024 * mb, availableMemorySource: 'free-memory',
                memoryUsagePercent: 50, cpuCoreCount: 8, loadAverage1m: 0
              },
              processMemoryMetric: 'working-set',
              processCommitMetric: 'private-bytes',
              totalCpu: 12,
              totalMemory: 320 * mb,
              totalPrivateMemory: 440 * mb,
              collectedAt: Date.now()
            }
          })
          return { memorySnapshot, memorySnapshotError }
        }, sampleWorktreeId)
        try {
          await popover.getByText(/320(?:\.0)?\s*M(?:i)?B/).first().waitFor(waits)
        } catch (error) {
          await close(popover)
          throw error
        }
      }
      if (!keepOpen) await close(popover)
      return popover
    },
    close,
    clearResourceSample
  }
}

async function observeFixedPorts({
  browser, caption, waits, step, episode, write, preview, enterPreview, setSize, selectedChat, poll,
  localWorkspace, remoteWorkspace, studioHost, hostName, localRoot, studioRoot,
  stopStudio, restartStudio, removeStudioPairing, desktopApp
}) {
  assert.ok(localWorkspace && remoteWorkspace, 'Both disposable worktrees must exist')
  const ports = createPortsReplay({ browser, caption, waits, hostName, localRoot, studioRoot })
  const checks = { boundary: 'Two paired Runtime profiles sharing one Windows port table, distinct worktree roots' }
  const terminalContinuity = process.argv.includes('--resource-terminal-continuity')
  const refreshOnly = process.argv.includes('--port-refresh-regression')
  const followTarget = refreshOnly || process.argv.includes('--port-target-continuity')
  const manage = followTarget || process.argv.includes('--port-resource-management')
  const button = (en, zh) => browser().getByRole('button', { name: caption(en, zh), exact: true }).first()
  const panel = host => preview().locator(
    `[data-workspace-preview-explorer][data-execution-host=${JSON.stringify(host)}]`
  )
  const tab = id => preview().locator(`[data-workspace-preview-tab=${JSON.stringify(id)}]`)
  let localPanelId
  let studioPanelId

  async function openNativeWorktree(worktree, host) {
    if (await preview().isVisible()) {
      await button('Return to worktree', '返回工作树').click(waits)
      await preview().waitFor({ ...waits, state: 'hidden' })
    }
    const escaped = await browser().evaluate(id => CSS.escape(id), worktree)
    await browser().locator(`[data-worktree-id=${escaped}] [data-worktree-card-surface]`)
      .first().click(waits)
    await poll(selectedChat, value => value.workspaceId === worktree &&
      (value.activeHost ?? 'local') === host, 'The selected worktree did not resolve to its host')
  }

  async function openExplorer(worktree, host) {
    await openNativeWorktree(worktree, host)
    await enterPreview()
    await button('New work object', '新建工作对象').click(waits)
    await browser().getByRole('menuitem', { name: caption('Open Explorer', '打开资源管理器'), exact: true }).click(waits)
    await panel(host).waitFor(waits)
    return panel(host).getAttribute('data-workspace-preview-explorer')
  }

  async function signalResourceFixtureVisibility(visible) {
    const setRendererVisibility = () => browser().evaluate(eligible => {
      if (eligible) {
        if (Object.hasOwn(document, 'visibilityState')) throw new Error('Unexpected visibility fixture')
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
      } else {
        delete document.visibilityState
      }
      document.dispatchEvent(new Event('visibilitychange'))
    }, visible)
    if (!visible) await setRendererVisibility()
    // Retry a lost CDP evaluation only. The isolated signal is idempotent; native admission stays intact.
    for (let attempt = 0; ; attempt += 1) {
      try {
        const count = await desktopApp().evaluate(({ BrowserWindow }, eligible) => {
          const windows = BrowserWindow.getAllWindows()
          for (const window of windows) {
            if (window.isVisible() || window.isFocused()) throw new Error('The replay window is not hidden')
            window.webContents.send('memory:resourceWindowVisibility', eligible)
          }
          return windows.length
        }, visible)
        assert.ok(count > 0, 'The hidden replay window is missing')
        break
      } catch (error) {
        if (attempt >= 2 || !error.message.includes('Resulting promise was garbage collected')) throw error
      }
    }
    if (visible) await setRendererVisibility()
  }

  async function releaseResourceFixture() {
    try {
      await signalResourceFixtureVisibility(false)
    } finally {
      await ports.clearResourceSample()
    }
  }

  function localBrowserState() {
    return browser().evaluate(worktreeId => {
      const state = window.__store.getState()
      return {
        activeId: state.activeBrowserTabId,
        activeType: state.activeTabType,
        tabs: (state.browserTabsByWorktree[worktreeId] ?? []).map(tab => ({
          id: tab.id, pageId: tab.activePageId, url: tab.url, title: tab.title
        }))
      }
    }, localWorkspace)
  }

  if (terminalContinuity) {
    await step('i39-resource-worktree-setup', 'Open the original Local and Studio worktrees and their Explorers', async () => {
      localPanelId = await openExplorer(localWorkspace, 'local')
      studioPanelId = await openExplorer(remoteWorkspace, studioHost)
      checks.resourceSetup = { localExplorer: true, studioExplorer: true }
    })
    const { observeResourceTerminalContinuity } = require('./observe-resource-terminal-continuity.cjs')
    await observeResourceTerminalContinuity({
      browser, caption, waits, step, episode, preview, enterPreview, setSize, selectedChat, poll,
      localWorkspace, remoteWorkspace, studioHost, localRoot, desktopApp, openNativeWorktree,
      studioPanelId, selectStudio: () => tab(studioPanelId).click(waits), checks
    })
    write('workspace-ports-continuity-checks.json', checks)
    return
  }

  try {
    await step('i30-ports-scope', 'Read the actual listeners for two fixed Explorers with the same project name', async () => {
      await ports.start()
      await episode('fixed-explorer-port-scope', [
        ['Open the Local Explorer and verify its listener', async () => {
          localPanelId = await openExplorer(localWorkspace, 'local')
          await ports.inspect('Local Windows')
        }],
        ['Open the Studio Explorer and verify its listener', async () => {
          studioPanelId = await openExplorer(remoteWorkspace, studioHost)
          await ports.inspect(hostName, true)
        }]
      ])
      checks.scope = { bothHostsScanned: true, actualListeners: true, unrelatedListenerExcluded: true }
    })
    await step('i30-ports-worktree', 'Follow the Studio port panel to its original worktree and return to the same Explorer', async () => {
      assert.ok(checks.scope)
      await episode('ports-to-native-worktree', [
        ['Go to the owning worktree', async () => {
          await ports.handoff(hostName)
          await preview().waitFor({ ...waits, state: 'hidden' })
          await poll(selectedChat, value => value.workspaceId === remoteWorkspace &&
            value.activeHost === studioHost, 'The Studio worktree handoff changed owners')
        }],
        ['Return to the same fixed Explorer', async () => {
          await enterPreview()
          assert.equal(await panel(studioHost).getAttribute('data-workspace-preview-explorer'), studioPanelId)
        }]
      ])
      checks.handoff = { originalWorktree: true, originalHost: true, restoredExplorer: true }
    })
    let resourcePopover
    await step('i32-resource-scope', 'Check the local summary and PTYs across the two fixed Explorer hosts', async () => {
      assert.ok(checks.handoff)
      await setSize(600, 460)
      await episode('local-resource-scope', [
        ['Check the Local summary and PTY tab beside Local Explorer', async () => {
          await tab(localPanelId).click(waits)
          await ports.resources()
        }],
        ['Check the same local scope beside Studio Explorer with a sample', async () => {
          await tab(studioPanelId).click(waits)
          resourcePopover = await ports.resources(true)
        }]
      ])
      checks.resource = { localAcrossHosts: true, localPtys: true, populatedNumbersAreFixture: true }
    })
    if (resourcePopover) await ports.close(resourcePopover)
    await setSize(1280, 800)
    if (manage) {
      const openInBrowser = { name: caption('Open in app Browser', '在应用内浏览器打开'), exact: true }
      const field = (dialog, en, zh) => dialog.getByText(caption(en, zh), { exact: true })
        .locator('xpath=following-sibling::dd[1]')
      let localDetails
      let studioDetails
      if (!refreshOnly) await step(followTarget ? 'i36-port-address' : 'i33-port-details', 'Inspect both listeners with host, worktree and address provenance', async () => {
        assert.ok(checks.handoff)
        if (process.argv.includes('--compact-port-inspection')) await setSize(600, 460)
        await episode(followTarget ? 'port-address-provenance' : 'port-detail-origin', [
          ['Read the Local listening address and Browser target', async () => {
            await tab(localPanelId).click(waits)
            localDetails = await ports.details('Local Windows')
            assert.equal(await localDetails.dialog.getByRole('button', openInBrowser).count(), 1)
            if (followTarget) {
              const { dialog, port } = localDetails
              assert.equal(await field(dialog, 'Listening on', '监听地址').textContent(), `127.0.0.1:${port}`)
              assert.equal(await field(dialog, 'Browser URL', '浏览器地址').textContent(), `http://127.0.0.1:${port}`)
              assert.equal(await field(dialog, 'Kind', '种类').textContent(), caption('Workspace listener', '工作树服务'))
              assert.equal(await field(dialog, 'Protocol', '协议').textContent(), caption('Unknown', '未知'))
              assert.equal(await field(dialog, 'Evidence', '证据').textContent(), caption('Command line', '命令行'))
              assert.equal(await dialog.evaluate(node =>
                node.getBoundingClientRect().width <= window.innerWidth && node.scrollWidth <= node.clientWidth
              ), true, 'Port details overflow the window')
            }
          }],
          ['Exit details with Escape and return focus to the Ports trigger', async () => {
            await ports.closeDetails('Local Windows', localDetails.dialog)
          }],
          ['Reveal the Studio listener and check the read-only details', async () => {
            await tab(studioPanelId).click(waits)
            studioDetails = await ports.details(hostName)
            assert.equal(await studioDetails.dialog.getByRole('button', openInBrowser).count(), 0)
            if (followTarget) {
              assert.equal(await field(studioDetails.dialog, 'Browser URL', '浏览器地址').count(), 0)
              assert.equal(await field(studioDetails.dialog, 'Listening on', '监听地址').textContent(),
                `127.0.0.1:${studioDetails.port}`)
            }
          }]
        ])
        checks.details = { localAndStudioOrigins: true, actualAddresses: true, returnedFocus: true }
        if (followTarget) checks.address = { separateLocalBrowserUrl: true, localizedAttribution: true, pairedListenerOnly: true }
      })
      if (studioDetails) await ports.closeDetails(hostName, studioDetails.dialog)
      await setSize(1280, 800)
      let originalBrowser
      await step(followTarget ? 'i37-port-refresh' : 'i34-port-browser', 'Recover a stale listener and open the selected replacement', async () => {
        assert.ok(refreshOnly ? checks.scope : checks.details)
        await tab(localPanelId).press('Enter', waits)
        const before = await localBrowserState()
        const old = await ports.details('Local Windows')
        let refreshed
        let replacementPort
        await episode(followTarget ? 'refresh-stale-listener' : 'port-to-browser', [
          ['Replace only the disposable Local process while its details are open', async () => {
            replacementPort = await ports.replaceLocal()
          }],
          ['Check the changed-listener feedback and stay in preview', async () => {
            await old.dialog.getByRole('button', openInBrowser).click(waits)
            await old.dialog.getByRole('alert').filter({ hasText: caption(
              'The listener changed. Refresh ports and try again.', '监听服务已变化。刷新端口后重试。'
            ) }).waitFor(waits)
            await preview().waitFor(waits)
          }],
          ...(followTarget ? [['Refresh the same Local port list with Enter and keep its focus', async () => {
            await old.dialog.getByRole('button', { name: caption('Refresh Ports', '刷新端口'), exact: true })
              .press('Enter', waits)
            await old.dialog.waitFor({ ...waits, state: 'hidden' })
            refreshed = browser().getByRole('dialog', { name: caption('Ports on Local Windows', 'Local Windows 的端口'), exact: true })
            await refreshed.waitFor(waits)
            await browser().waitForFunction(
              label => document.activeElement?.getAttribute('aria-label') === label &&
                document.activeElement?.getAttribute('role') === 'dialog',
              caption('Ports on Local Windows', 'Local Windows 的端口'), waits
            )
            const replacement = refreshed.getByText(String(replacementPort), { exact: true })
            await replacement.waitFor({ ...waits, timeout: 4000 }).catch(async error => {
              if (error.name !== 'TimeoutError' || !(await refreshed.getByRole('status').isVisible())) {
                throw error
              }
              await refreshed.getByRole('button', {
                name: caption('Refresh Ports', '刷新端口'), exact: true
              }).press('Enter', waits)
              await replacement.waitFor(waits)
            })
            assert.equal(await refreshed.getByText(String(old.port), { exact: true }).count(), 0)
            assert.deepEqual(await localBrowserState(), before, 'Refresh opened a Browser tab without selection')
          }]] : []),
          ['Reopen new listener details and render the real loopback page in the app', async () => {
            if (!followTarget) await ports.closeDetails('Local Windows', old.dialog)
            const fresh = await ports.details('Local Windows', refreshed)
            assert.equal(fresh.port, replacementPort)
            assert.notEqual(fresh.port, old.port)
            await fresh.dialog.getByRole('button', openInBrowser).click(waits)
            await preview().waitFor({ ...waits, state: 'hidden' })
            await poll(selectedChat, value => value.workspaceId === localWorkspace &&
              (value.activeHost ?? 'local') === 'local', 'Browser did not return to its source worktree')
            const url = `http://127.0.0.1:${fresh.port}/`
            await poll(() => desktopApp().evaluate(({ webContents }, expected) =>
              webContents.getAllWebContents().some(contents => !contents.isDestroyed() &&
                contents.getURL() === expected && contents.getTitle() === 'Porpita Loopback Fixture'),
              url), Boolean, 'The embedded Browser did not load the fixture page')
            if (followTarget) {
              const state = await localBrowserState()
              originalBrowser = state.tabs.find(tab => tab.id === state.activeId)
              assert.equal(state.activeType, 'browser')
              assert.ok(originalBrowser?.pageId)
              assert.equal(new URL(originalBrowser.url).href, url)
              assert.equal(state.tabs.length, before.tabs.length + 1)
            }
          }]
        ])
        checks.browser = { staleListenerRefused: true, originalWorktree: true, realGuestDocument: true }
        if (followTarget) checks.refresh = { sameScopedList: true, listFocus: true, explicitReplacementSelection: true }
      })
      if (refreshOnly) {
        write('workspace-ports-continuity-checks.json', checks)
        return
      }
      await step('i35-resource-worktree', 'Follow the sampled local worktree row from the Studio preview and restore the original Explorer', async () => {
        assert.ok(checks.browser)
        await enterPreview()
        await tab(studioPanelId).click(waits)
        await ports.inspect(hostName, true)
        await ports.handoff(hostName)
        await preview().waitFor({ ...waits, state: 'hidden' })
        await poll(selectedChat, value => value.workspaceId === remoteWorkspace &&
          value.activeHost === studioHost, 'Studio is not the active native worktree before the resource handoff')
        await enterPreview()
        const worktreeName = await browser().evaluate(id =>
          window.__store.getState().getKnownWorktreeById(id, 'local')?.displayName, localWorkspace)
        try {
          await signalResourceFixtureVisibility(true)
          await episode('resource-to-native-worktree', [
            ['Show an attributed sample for the actual Local worktree beside Studio Explorer', async () => {
              const manager = await ports.resources(true, localWorkspace)
              await manager.getByRole('button', {
                name: caption(`Resume workspace ${worktreeName}`, `恢复工作区 ${worktreeName}`), exact: true
              }).press('Enter', waits)
              await preview().waitFor({ ...waits, state: 'hidden' })
              await poll(selectedChat, value => value.workspaceId === localWorkspace &&
                (value.activeHost ?? 'local') === 'local', 'Resource navigation did not reveal the sample owner')
            }],
            ['Return to the same Studio Explorer', async () => {
              await enterPreview()
              assert.equal(await panel(studioHost).getAttribute('data-workspace-preview-explorer'), studioPanelId)
            }]
          ])
          checks.resourceNavigation = { ownerSampleIsFixture: true, realNavigation: true, restoredExplorer: true }
        } finally {
          await releaseResourceFixture()
        }
      })
      if (followTarget) {
        await step('i38-resource-browser', 'Switch from Studio Explorer to the original Local Browser tab from Resources', async () => {
          assert.ok(originalBrowser?.pageId)
          await ports.inspect(hostName, true)
          await ports.handoff(hostName)
          await preview().waitFor({ ...waits, state: 'hidden' })
          await poll(selectedChat, value => value.workspaceId === remoteWorkspace &&
            value.activeHost === studioHost, 'Studio must be the native scope before resuming the Browser')
          await enterPreview()
          const before = await localBrowserState()
          assert.notEqual(before.activeId, originalBrowser.id)
          try {
            await signalResourceFixtureVisibility(true)
            let manager
            let row
            await episode('resources-to-existing-browser', [
              ['Focus the existing Browser row while Studio Explorer remains selected', async () => {
                manager = await ports.resources(true, localWorkspace)
                row = manager.getByRole('button', { name: caption(
                  'Switch to Browser tab Porpita Loopback Fixture',
                  '切换到浏览器标签页 Porpita Loopback Fixture'
                ), exact: true })
                if (!await row.isVisible()) {
                  const name = await browser().evaluate(id =>
                    window.__store.getState().getKnownWorktreeById(id, 'local')?.displayName, localWorkspace)
                  const worktree = manager.getByRole('button', {
                    name: caption(`Resume workspace ${name}`, `恢复工作区 ${name}`), exact: true
                  })
                  const expand = worktree.locator('..').getByRole('button', {
                    name: caption('Expand workspace', '扩大工作区'), exact: true
                  })
                  if (await expand.isVisible()) await expand.click(waits)
                }
                await row.waitFor(waits)
                await row.focus(waits)
                await panel(studioHost).waitFor(waits)
              }],
              ['Press Space and verify the original Browser tab and page are active', async () => {
                await browser().keyboard.press('Space')
                await manager.waitFor({ ...waits, state: 'hidden' })
                await preview().waitFor({ ...waits, state: 'hidden' })
                await poll(selectedChat, value => value.workspaceId === localWorkspace &&
                  (value.activeHost ?? 'local') === 'local', 'Browser navigation did not reveal the original owner')
                const after = await poll(localBrowserState, state =>
                  state.activeType === 'browser' && state.activeId === originalBrowser.id,
                  'The selected Browser tab was not active')
                assert.equal(after.tabs.length, before.tabs.length, 'Resource navigation created another Browser')
                assert.equal(after.tabs.find(tab => tab.id === after.activeId).pageId, originalBrowser.pageId)
              }],
              ['Return to the same Studio Explorer', async () => {
                await enterPreview()
                assert.equal(await panel(studioHost).getAttribute('data-workspace-preview-explorer'), studioPanelId)
              }]
            ])
            checks.resourceBrowser = { originalTab: true, originalPage: true, tabCountUnchanged: true, restoredExplorer: true }
          } finally {
            await releaseResourceFixture()
          }
        })
      }
    }
    await step('i31-ports-outage', 'Stop Studio while Local still has a functioning listener', async () => {
      assert.ok(checks.handoff)
      await episode('ports-host-outage', [
        ['Stop the Studio Runtime', stopStudio],
        ['Read the offline status on the Studio port panel', () => ports.disconnected()],
        ['Switch to the Local Explorer and read its live listener', async () => {
          await tab(localPanelId).click(waits)
          await ports.inspect('Local Windows')
        }]
      ])
      await ports.replaceStudio()
      checks.offline = { studioUnavailable: true, localScanStillUsable: true }
    })
    await step('i31-ports-recovery', 'Reconnect the Studio Explorer and read its replacement listener', async () => {
      assert.ok(checks.offline)
      await tab(studioPanelId).click(waits)
      await restartStudio()
      const reconnect = panel(studioHost).getByRole('button', {
        name: caption('Reconnect', '重新连接'), exact: true
      })
      if (await reconnect.isVisible()) await reconnect.click({ timeout: 3000 }).catch(error => {
        if (error.name !== 'TimeoutError') throw error
      })
      await panel(studioHost).getByRole('option', { name: 'release.md', exact: true }).waitFor(waits)
      await ports.inspect(hostName, true)
      checks.recovered = { freshListener: true, previousListenerExcluded: true }
    })
    await browser().keyboard.press('Escape')
    await step('i31-ports-revoked', 'Withdraw Studio pairing and check the retired port panel', async () => {
      assert.ok(checks.recovered)
      await removeStudioPairing()
      await ports.revoked(true)
      checks.retired = { unavailableStatus: true, oldHostAndHandoffHidden: true }
    })
    write('workspace-ports-continuity-checks.json', checks)
  } finally {
    ports.dispose()
  }
}

module.exports = { createPortsReplay, observeFixedPorts }
