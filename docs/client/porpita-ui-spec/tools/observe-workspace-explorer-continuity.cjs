const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const project = 'Release-review'
const originalFile = 'handoff-note.md'
const localText = 'The Local handoff uses the blue release checklist.'
const studioText = 'The Studio handoff uses the green release checklist.'
const selectedReview = 'review-055.md'

function seedExplorerFolders(local, studio) {
  for (const [root, marker, text] of [
    [local, 'local-source.md', localText],
    [studio, 'studio-source.md', studioText]
  ]) {
    const handoff = path.join(root, 'handoff')
    fs.mkdirSync(handoff)
    fs.writeFileSync(path.join(handoff, originalFile), `# ${text}\n`)
    fs.writeFileSync(path.join(handoff, marker), '# Source marker\n')
    for (let index = 1; index <= 76; index++) {
      const filename = `review-${String(index).padStart(3, '0')}.md`
      fs.writeFileSync(path.join(handoff, filename), '# Review item\n')
    }
  }
}

async function observeExplorer(context) {
  const ports = context.workspacePortsContinuity
    ? require('./observe-workspace-ports-continuity.cjs').createPortsReplay({
        ...context, browser: () => context.desktop().page
      })
    : null
  try {
    await observeExplorerJourney({ ...context, ports })
  } finally {
    ports?.dispose()
  }
}

async function observeExplorerJourney({
  desktop, step, episode, write, waits, caption, hostName, studioHost, localHostLabel,
  workspaceChatTitle, workspaceId, localWorkspace, remoteWorkspace, environmentId,
  preview, pane, composer, enterPreview, setSize, poll, readLayout, studioRuntimeIdentity,
  restartStudio, stopStudio, removeStudioPairing, restartDesktop, studioRoot, workspaceUsageContinuity, ports
}) {
  const browser = () => desktop().page
  const button = (en, zh) => browser().getByRole('button', { name: caption(en, zh), exact: true })
  const menuitem = (en, zh) => browser().getByRole('menuitem', { name: caption(en, zh), exact: true })
  const picker = () => browser().getByRole('dialog', {
    name: caption('Choose a folder for Explorer', '选择资源管理器的目录'), exact: true
  })
  const panel = (host) => preview().locator(
    `[data-workspace-preview-explorer][data-execution-host=${JSON.stringify(host)}]`
  )
  const filter = (host) => panel(host).locator('[data-explorer-query-input=files]')
  const file = (host, filename) => panel(host).getByRole('option', { name: filename, exact: true })
  const list = (host) => panel(host).getByRole('listbox')
  const activeObject = () => preview().locator('[data-workspace-preview-object]')
  const topTab = (id) => preview().locator(`[data-workspace-preview-tab=${JSON.stringify(id)}]`)
  const reconnect = () => panel(studioHost).getByRole('button', {
    name: caption('Reconnect', '重新连接'), exact: true
  })
  const readPanelId = (host) => panel(host).getAttribute('data-workspace-preview-explorer')
  const checks = { boundary: 'Windows development preview, two authenticated loopback Runtime profiles, disposable Git roots' }
  const usage = workspaceUsageContinuity
    ? require('./observe-workspace-usage-continuity.cjs').observeUsage({
        browser, caption, waits, preview, workspaceId, composer, studioHost, hostName
      })
    : null
  let studioPanelId
  let localPanelId
  let storedLayout
  let localOfflineDraft

  async function showPicker() {
    await topTab(workspaceId).click(waits)
    await button('New work object', '新建工作对象').click(waits)
    await menuitem('Open Explorer', '打开资源管理器').click(waits)
    await picker().waitFor(waits)
  }

  async function pick(host) {
    const search = picker().locator('[cmdk-input]')
    await search.fill(host, waits)
    await picker().locator('[cmdk-item][aria-selected=true]').getByText(host, { exact: true }).waitFor(waits)
    await search.press('Enter', waits)
    await picker().waitFor({ ...waits, state: 'hidden' })
  }

  async function openHandoff(host) {
    await file(host, 'handoff').dblclick(waits)
    await file(host, originalFile).waitFor(waits)
  }

  async function expectView(host, query, name) {
    await filter(host).waitFor(waits)
    assert.equal(await filter(host).inputValue(), query)
    const selected = file(host, name)
    await selected.waitFor(waits)
    assert.equal(await selected.getAttribute('aria-selected'), 'true')
  }

  async function placement(host, embedded) {
    await panel(host).getByRole('button', {
      name: caption('Explorer placement', '资源管理器位置'), exact: true
    }).click(waits)
    await (embedded
      ? menuitem(`Move to ${workspaceChatTitle}`, `移至 ${workspaceChatTitle}`)
      : menuitem('Open as a tab', '作为标签打开')).click(waits)
    assert.equal(await panel(host).getAttribute('data-presentation'), embedded ? 'embedded' : 'standalone')
    await browser().waitForFunction(owner =>
      document.activeElement?.matches('[data-explorer-query-input=files]') &&
      document.activeElement.closest('[data-workspace-preview-explorer]')?.getAttribute('data-execution-host') === owner,
      host, waits)
  }

  async function openOriginal(host, workspace, message, environment) {
    await filter(host).press('Enter', waits)
    await preview().waitFor({ ...waits, state: 'hidden' })
    await browser().getByText(message, { exact: true }).first().waitFor(waits)
    const observed = await browser().evaluate(() => {
      const state = window.__store.getState()
      const file = state.openFiles.find(item =>
        item.id === state.activeFileId && item.relativePath.replaceAll('\\', '/') === 'handoff/handoff-note.md'
      )
      return file && { worktree: file.worktreeId, runtime: file.runtimeEnvironmentId ?? null, path: file.relativePath.replaceAll('\\', '/') }
    })
    assert.deepEqual(observed, { worktree: workspace, runtime: environment, path: 'handoff/handoff-note.md' })
    await usage?.nativeEditor(host)
  }

  await step('i24-source-picker', 'Show identical project titles with explicit Local and Studio source labels', async () => {
    assert.ok(workspaceId, 'The mixed Workspace must exist before opening Explorer')
    await showPicker()
    const candidates = picker().getByRole('option')
    assert.equal(await candidates.count(), 2)
    for (const candidate of await candidates.all()) {
      assert.ok((await candidate.innerText()).includes(project))
    }
    await candidates.filter({ has: browser().getByText(localHostLabel) }).waitFor(waits)
    await candidates.filter({ has: browser().getByText(hostName, { exact: true }) }).waitFor(waits)
    checks.picker = { sameProjectName: true, explicitHostChoices: 2 }
  })

  await step('i24-two-explorers', 'Create two scoped instances, each listing only its own actual folder', async () => {
    assert.ok(checks.picker)
    await episode('explorer-scope-selection', [
      ['Choose Studio by keyword and Enter', () => pick(hostName)],
      ['Read the Studio folder and select the shared filename', async () => {
        studioPanelId = await readPanelId(studioHost)
        await openHandoff(studioHost)
        await file(studioHost, 'studio-source.md').waitFor(waits)
        assert.equal(await file(studioHost, 'local-source.md').count(), 0)
        await filter(studioHost).fill('handoff-note', waits)
        await file(studioHost, originalFile).click(waits)
      }],
      ['Choose Local and repeat for its own folder', async () => {
        await showPicker()
        const label = await picker().getByText(localHostLabel).innerText()
        await pick(label)
        localPanelId = await readPanelId('local')
        assert.notEqual(localPanelId, studioPanelId)
        await openHandoff('local')
        await file('local', 'local-source.md').waitFor(waits)
        assert.equal(await file('local', 'studio-source.md').count(), 0)
        await filter('local').fill('handoff', waits)
        await filter('local').press('ArrowDown', waits)
        await expectView('local', 'handoff', originalFile)
      }]
    ])
    checks.instances = { localOnlyEntries: true, studioOnlyEntries: true, independentInstances: true }
  })

  if (ports) {
    await step('i30-ports-scope', 'Read the real listeners for two same-name worktrees through their own port panel', async () => {
      assert.ok(checks.instances)
      await ports.start()
      await episode('ports-scope-handoff', [
        ['Read the Local standalone Explorer listener', () => ports.inspect('Local Windows')],
        ['Open Studio Explorer and read only its listener', async () => {
          await topTab(studioPanelId).click(waits)
          await ports.inspect(hostName)
        }],
        ['Return to the mixed Workspace and focus its Local Chat', async () => {
          await topTab(workspaceId).click(waits)
          await usage.select('local')
          await ports.inspect('Local Windows')
        }],
        ['Focus Studio without closing the mixed Workspace', async () => {
          await usage.select(studioHost)
          await ports.inspect(hostName, true)
        }]
      ])
      checks.portsScope = { standaloneUsesItsRoot: true, mixedUsesSelectedChat: true, unrelatedListenerExcluded: true }
    })
    await step('i30-ports-worktree', 'Use the scoped port panel to open the original Studio worktree', async () => {
      assert.ok(checks.portsScope)
      await episode('ports-to-native-worktree', [
        ['Open the owning worktree through the scoped panel', async () => {
          await ports.handoff(hostName)
          await preview().waitFor({ ...waits, state: 'hidden' })
          await poll(
            () => browser().evaluate(() => {
              const state = window.__store.getState()
              return [state.activeWorktreeId, state.activeWorkspaceExecutionHostId]
            }),
            ([id, host]) => id === remoteWorkspace && host === studioHost,
            'The worktree handoff did not retain its Studio binding'
          )
        }],
        ['Return to the mixed Workspace and the same Studio Chat', async () => {
          await enterPreview()
          await usage.scope(studioHost)
          assert.equal(await activeObject().getAttribute('data-workspace-preview-object'), workspaceId)
        }]
      ])
      await topTab(localPanelId).click(waits)
      checks.portsHandoff = { originalHost: true, originalWorktree: true, workspaceContinues: true }
    })
  }

  await step('i24-open-original-local', 'Open the shared filename in its Local editor and read the Local document', async () => {
    assert.ok(checks.instances)
    await openOriginal('local', localWorkspace, localText, null)
    checks.localEditor = { originalWorktree: true, localBytesVisible: true }
  })

  if (usage) {
    await step('i27-usage-follows-chat', 'Switch between same-title chats and show their different usage owners', async () => {
      assert.ok(checks.localEditor)
      await enterPreview()
      await usage.standalone()
      await topTab(workspaceId).click(waits)
      await episode('usage-follows-chat', [
        ['Focus the Studio chat', () => usage.select(studioHost)],
        ['Focus the Local chat', () => usage.select('local')]
      ])
      checks.usageFocus = { bothChatHostsNamed: true, standaloneHasNoChatUsage: true }
    })
    await step('i28-accounts-handoff', 'Open the owning host’s Accounts page and return to the same Workspace', async () => {
      assert.ok(checks.usageFocus)
      await episode('usage-accounts-handoff', [
        ['Open Local Accounts with the status bar keyboard action', () => usage.openAccounts('local')],
        ['Focus the Studio chat', () => usage.select(studioHost)],
        ['Open the Studio Accounts page and return to the same Chat', () => usage.openAccounts(studioHost)]
      ])
      await topTab(localPanelId).click(waits)
      checks.usageSettings = { localAccountHost: true, studioAccountHost: true, workspaceRetained: true }
    })
    try {
      await step('i28-populated-usage', 'Inspect a 37% local quota fixture and its account action at narrow width', async () => {
        assert.ok(checks.usageSettings)
        await topTab(workspaceId).click(waits)
        await usage.select('local')
        await setSize(600, 460)
        await usage.showUsageFixture()
        checks.usageFixture = { host: 'Local Windows', provider: 'Codex', usedPercent: 37, fixture: true }
      })
    } finally {
      await usage.clearUsageFixture()
      await setSize(1280, 800)
      await topTab(localPanelId).click(waits)
    }
  }

  await step('i24-open-original-studio', 'Open the same filename in the Studio editor and read the Studio document', async () => {
    assert.ok(checks.localEditor)
    if (!usage) await enterPreview()
    await expectView('local', 'handoff', originalFile)
    await topTab(studioPanelId).click(waits)
    await expectView(studioHost, 'handoff-note', originalFile)
    await openOriginal(studioHost, remoteWorkspace, studioText, environmentId)
    checks.studioEditor = { originalWorktree: true, pairedOwner: true, studioBytesVisible: true }
  })

  await step('i25-move-same-explorer', 'Move Studio into Workspace and back with its selection, scroll, and input focus', async () => {
    assert.ok(checks.studioEditor)
    await enterPreview()
    await expectView(studioHost, 'handoff-note', originalFile)
    const top = () => list(studioHost).evaluate(node => node.scrollTop)
    await filter(studioHost).fill('review-', waits)
    await file(studioHost, selectedReview).click(waits)
    await list(studioHost).hover(waits)
    await browser().mouse.wheel(0, 118)
    const before = await poll(top, value => value > 450, 'The long list did not scroll')
    await episode('explorer-placement-and-scroll', [
      ['Move the selected folder into the existing mixed Workspace', async () => {
        await placement(studioHost, true)
        await expectView(studioHost, 'review-', selectedReview)
        assert.equal(await activeObject().getAttribute('data-workspace-preview-object'), workspaceId)
        assert.equal(await readPanelId(studioHost), studioPanelId)
        await poll(top, value => Math.abs(value - before) <= 2, 'The embedded list did not restore its scroll')
        assert.equal(await preview().locator('[data-workspace-preview-session]:visible').count(), 2)
      }],
      ['Return it to the original top-level tab', async () => {
        await placement(studioHost, false)
        await expectView(studioHost, 'review-', selectedReview)
        assert.equal(await readPanelId(studioHost), studioPanelId)
        await poll(top, value => Math.abs(value - before) <= 2, 'The detached list did not restore its scroll')
      }],
      ['Embed again for the narrow and recovery flow', () => placement(studioHost, true)]
    ])
    checks.move = { samePanel: true, sameSelection: true, filterFocusRestored: true, scrollRetained: true, standalonePositionRetained: true }
  })

  await step('i25-narrow-workspace', 'Keep Explorer bound to Studio while switching to a usable Local Chat at 600 × 460', async () => {
    assert.ok(checks.move)
    await setSize(600, 460)
    await browser().emulateMedia({ reducedMotion: 'reduce' })
    await button('Switch pane', '切换窗格').click(waits)
    await browser().getByRole('menuitemradio').filter({ has: browser().getByText(localHostLabel) }).click(waits)
    await composer('local').waitFor(waits)
    await pane(studioHost).waitFor({ ...waits, state: 'hidden' })
    await expectView(studioHost, 'review-', selectedReview)
    assert.equal(await panel(studioHost).locator('[data-workspace-preview-scope]').innerText(), 'handoff')
    if (usage) {
      await filter(studioHost).focus()
      await usage.scope('local')
      checks.usageNarrow = { focusInStudioExplorer: true, localChatUsageRetained: true }
    }
    const widths = await browser().evaluate(() => ({
      viewport: innerWidth,
      workspace: document.querySelector('[data-workspace-preview-chat-layout]').getBoundingClientRect().width,
      explorer: document.querySelector('[data-workspace-preview-explorer]').getBoundingClientRect().width
    }))
    assert.ok(widths.viewport === 600 && widths.workspace >= 320 && widths.explorer > 0)
    checks.narrow = { ...widths, focusChangedWithoutRebinding: true, reducedMotion: true }
  })

  if (ports) {
    let shown
    await step('i32-resource-scope', 'Check the client’s resource totals and PTYs with a narrow mixed Workspace', async () => {
      assert.ok(checks.narrow)
      await episode('local-resource-scope', [
        ['Open Resource Manager beside the Local Chat', async () => { await ports.resources() }],
        ['Select Studio while preserving the embedded Explorer', async () => {
          await button('Switch pane', '切换窗格').click(waits)
          await browser().getByRole('menuitemradio').filter({
            has: browser().getByText(hostName, { exact: true })
          }).click(waits)
          await usage.scope(studioHost)
        }],
        ['Check the same local summary and local PTY labels while Studio is selected', async () => {
          shown = await ports.resources(true)
        }]
      ])
      checks.resources = { localSummaryAcrossHostFocus: true, localPtyTab: true, compactViewport: true, sampleForLayout: true }
    })
    if (shown) {
      await ports.close(shown)
      await button('Switch pane', '切换窗格').click(waits)
      await browser().getByRole('menuitemradio').filter({ has: browser().getByText(localHostLabel) }).click(waits)
    }
  }

  await step('i25-two-instance-return', 'Switch to the Local tab and resume its independent filter and selected file', async () => {
    assert.ok(checks.narrow)
    await setSize(1280, 800)
    await browser().emulateMedia({ reducedMotion: 'no-preference' })
    await topTab(localPanelId).click(waits)
    await expectView('local', 'handoff', originalFile)
    await topTab(workspaceId).click(waits)
    await expectView(studioHost, 'review-', selectedReview)
    storedLayout = await poll(readLayout, layout => layout?.version === 3 && layout.activeId === workspaceId &&
      layout.objects.find(item => item.id === studioPanelId)?.selectedPath === selectedReview,
      'The v3 profile did not persist both Explorer references')
    assert.deepEqual(
      storedLayout.objects.filter(item => item.kind === 'explorer').map(item =>
        [item.executionHostId, item.worktreeId, item.attachedTo, item.directory]),
      [[studioHost, remoteWorkspace, workspaceId, 'handoff'], ['local', localWorkspace, null, 'handoff']]
    )
    const local = storedLayout.objects.find(item => item.id === localPanelId)
    const studio = storedLayout.objects.find(item => item.id === studioPanelId)
    assert.equal(local.pairingRevision, null)
    assert.ok(Number.isFinite(studio.pairingRevision))
    assert.notEqual(local.root, studio.root)
    checks.persisted = { version: 3, originalRootsKept: true, worktreesAndPairingKept: true }
  })

  await step('i26-cold-explorer', 'Restart the desktop only and restore the embedded Studio Explorer and selected file', async () => {
    assert.ok(checks.persisted)
    const pid = desktop().app.process().pid
    const identity = await studioRuntimeIdentity()
    await restartDesktop()
    assert.notEqual(desktop().app.process().pid, pid)
    assert.equal(await studioRuntimeIdentity(), identity)
    await expectView(studioHost, 'review-', selectedReview)
    assert.equal(await panel(studioHost).getAttribute('data-presentation'), 'embedded')
    assert.equal(await readPanelId(studioHost), studioPanelId)
    assert.deepEqual(await readLayout(), storedLayout)
    await showPicker()
    await pick(hostName)
    await expectView(studioHost, 'review-', selectedReview)
    assert.equal(await readPanelId(studioHost), studioPanelId)
    checks.cold = { newClient: true, sameRuntime: true, sameLayoutAndSelection: true, sameScopeReused: true }
  })

  await step('i26-explorer-outage', 'Stop Studio and verify only its file listing waits while Local remains editable', async () => {
    assert.ok(checks.cold)
    await usage?.select(studioHost)
    await episode('explorer-source-outage', [
      ['Stop only the isolated Studio Runtime', stopStudio],
      ['Wait for the Explorer reconnect action', async () => {
        await reconnect().waitFor(waits)
        assert.equal(await list(studioHost).count(), 0)
        assert.equal(await filter(studioHost).count(), 0)
        await usage?.disconnected()
        await ports?.disconnected()
      }],
      ['Continue typing in Local while Studio is disconnected', async () => {
        localOfflineDraft = 'Local continues during Explorer outage.'
        await composer('local').fill(localOfflineDraft, waits)
        assert.equal(await composer('local').innerText(), localOfflineDraft)
        await usage?.scope('local')
        await topTab(localPanelId).click(waits)
        await expectView('local', 'handoff', originalFile)
        await topTab(workspaceId).click(waits)
        await reconnect().waitFor(waits)
      }]
    ])
    fs.writeFileSync(path.join(studioRoot, 'handoff', 'review-after-outage.md'), '# Newly available\n')
    await ports?.replaceStudio()
    checks.outage = { studioFilesHidden: true, localDraftEditable: true, localExplorerUsable: true }
  })

  await step('i26-explorer-reconnect', 'Reconnect the original Studio Host and read a file added while it was stopped', async () => {
    assert.ok(checks.outage)
    let trigger = 'Explorer reconnect'
    await episode('explorer-source-recovery', [
      ['Restart Studio using the same profile', restartStudio],
      ['Use the visible reconnect control when still offered', async () => {
        try {
          await reconnect().click({ timeout: 3000 })
        } catch (error) {
          if (error.name !== 'TimeoutError') throw error
          trigger = 'automatic reconnect'
        }
        await expectView(studioHost, 'review-', selectedReview)
        await file(studioHost, 'review-after-outage.md').waitFor(waits)
        assert.equal(await composer('local').innerText(), localOfflineDraft)
      }]
    ])
    assert.equal(await readPanelId(studioHost), studioPanelId)
    checks.recovered = { trigger, newDirectoryRead: true, selectionKept: true, localDraftKept: true }
  })

  if (usage) {
    await step('i29-usage-recovers', 'Read the original Studio usage after recovery and switch back to the Local usage', async () => {
      assert.ok(checks.recovered)
      await episode('usage-after-reconnect', [
        ['Focus the recovered Studio chat', () => usage.select(studioHost)],
        ['Check that the local usage owner is still independent', () => usage.select('local')],
        ['Leave Studio selected for pairing withdrawal', () => usage.select(studioHost)]
      ])
      checks.usageReconnect = { sameRuntimeRead: true, localUsageDuringOutage: true, offlineCaption: true }
    })
  }

  if (ports) {
    await step('i31-ports-recovery', 'Rescan the reconnected Studio worktree and read its replacement listener', async () => {
      assert.ok(checks.recovered)
      await usage.select(studioHost)
      await ports.inspect(hostName, true)
      checks.portsRecovery = { freshListenerShown: true, stoppedListenerExcluded: true, offlineReceiptSuppressed: true }
    })
    await browser().keyboard.press('Escape')
  }

  await step('i26-explorer-revoked', 'Withdraw the Studio pairing and reopen the original Workspace with the retired listing redacted', async () => {
    assert.ok(checks.recovered)
    await removeStudioPairing()
    await panel(studioHost).getByText(caption(
      'The original host for this Explorer is unavailable.', '此资源管理器的原主机已不可用。'
    ), { exact: true }).waitFor(waits)
    assert.equal(await filter(studioHost).count(), 0)
    assert.equal(await list(studioHost).count(), 0)
    assert.equal(await panel(studioHost).locator('[data-workspace-preview-scope]').getAttribute('title'), null)
    assert.equal(await panel(studioHost).getByText(hostName, { exact: true }).count(), 0)
    assert.equal(await reconnect().count(), 0)
    assert.equal(await composer('local').innerText(), localOfflineDraft)
    await usage?.revoked()
    await ports?.revoked()
    checks.revoked = { cachedRowsAndPathHidden: true, reconnectAbsent: true, localDraftKept: true }
  })

  await step('i26-remove-explorer', 'Remove the obsolete Explorer and check that the Workspace and Local Explorer remain intact', async () => {
    assert.ok(checks.revoked)
    await usage?.select('local')
    await panel(studioHost).getByRole('button', {
      name: caption('Remove Explorer', '移除资源管理器'), exact: true
    }).click(waits)
    await panel(studioHost).waitFor({ ...waits, state: 'hidden' })
    assert.equal(await activeObject().getAttribute('data-workspace-preview-object'), workspaceId)
    await browser().waitForFunction(() =>
      document.activeElement?.closest('[data-native-chat-composer-scope]')?.closest('[data-execution-host=local]') != null,
      null, waits)
    await poll(readLayout, layout => layout?.objects.some(item => item.id === localPanelId) &&
      !layout.objects.some(item => item.id === studioPanelId), 'The layout did not acknowledge removal')
    assert.ok(fs.existsSync(path.join(studioRoot, 'handoff', originalFile)))
    await topTab(localPanelId).click(waits)
    await expectView('local', 'handoff', originalFile)
    checks.removed = { onlyRetiredPanelRemoved: true, diskFileKept: true, otherExplorerKept: true, localComposerFocused: true }
  })

  write('workspace-explorer-continuity-checks.json', checks)
}

module.exports = { seedExplorerFolders, observeExplorer }
