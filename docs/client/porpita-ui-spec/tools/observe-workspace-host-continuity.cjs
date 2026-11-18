const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const localHostLabel = /^(Local Windows|Local Linux|Local Mac)$/
const workspaceChatTitle = 'Shared release review'
const originalLocalDraft = 'Workspace Local · 本机草稿'
const workspaceStudioDraft = 'Workspace Studio · 配对草稿'
const offlineLocalDraft = 'Local stays editable · 本机仍可继续'
const acknowledgeTip = /^(Got it|知道了)$/i

async function observe({
  page, win, app, step, episode, write, waits, locale, title, hostName, localReply,
  remoteReply, localRow, assertHistoryRows, selectedChat, poll, localWorkspace,
  remoteWorkspace, studioChat, studioDraft, environmentId, userData, restartWorkspaceDesktop,
  restartStudio, stopStudio, workspaceExplorerContinuity, workspaceUsageContinuity, workspacePortsContinuity,
  studioRoot, localRoot, workspacePortsFocused
}) {
  const studioHost = `runtime:${encodeURIComponent(environmentId)}`
  const caption = (en, zh) => locale === 'zh' ? zh : en
  const button = (name) => page.getByRole('button', { name, exact: true }).first()
  const preview = () => page.locator('[data-workspace-preview]')
  const pane = (host) => preview().locator(
    `[data-workspace-preview-session][data-execution-host=${JSON.stringify(host)}]`
  )
  const composer = (host) => pane(host).locator('[data-native-chat-composer-scope] [contenteditable=true]').first()
  const split = () => preview().locator('[data-preview-split]')
  const reconnect = () => pane(studioHost).getByRole('button', { name: caption('Reconnect', '重新连接'), exact: true })
  const hostNotice = () => pane(studioHost).locator('[data-notice-kind=host]:visible')
  const selectedWorkspace = (layout) => layout?.objects.find(object =>
    object.kind === 'workspace' && object.id === layout.activeId
  )
  const layoutFile = path.join(userData, 'porpita-workspaces.json')
  const readLayout = () => page.evaluate(() => window.api.ui.readPorpitaWorkspaceLayout())
  const check = {
    boundary: {
      topology: 'Two isolated Runtime profiles on one Windows machine',
      fixture: 'Same Provider history ID and title; distinct Native Chat sessions',
      network: 'Loopback paired transport',
      input: 'Unsent drafts only'
    }
  }
  let localChat
  let workspaceId
  let savedLayout
  let pairingRevision

  async function setSize(width, height) {
    for (let attempt = 0; attempt < 3; attempt++) {
      await win.evaluate((window, size) => window.setContentSize(...size), [width, height])
      try {
        await page.waitForFunction(
          ([w, h]) => innerWidth === w && innerHeight === h,
          [width, height], { timeout: 4000 }
        )
        return
      } catch (error) {
        if (attempt === 2) throw error
      }
    }
  }

  async function enterPreview() {
    const entry = button(caption('Workspaces (preview)', '工作空间（预览）'))
    const sidebar = page.locator('[data-workspace-sidebar-toggle=left][aria-expanded=false]:visible').first()
    if (!(await entry.isVisible()) && await sidebar.isVisible()) await sidebar.click(waits)
    try {
      await entry.click(workspaceExplorerContinuity ? { ...waits, timeout: 6500 } : waits)
    } catch {
      const tip = page.getByRole('dialog').getByRole('button', { name: acknowledgeTip }).first()
      if (await tip.isVisible()) await tip.click(waits)
      await entry.click(waits).catch(async error => {
        const view = await page.evaluate(() => window.__store?.getState().activeView)
        const dialogs = await page.getByRole('dialog').allTextContents()
        throw new Error(`Workspace entry unavailable from ${view}. Visible dialog: ${dialogs.join(' · ')}\n${error.message}`, { cause: error })
      })
    }
    await preview().waitFor(waits)
  }

  async function dismissColdStartTip() {
    const dialog = page.getByRole('dialog').first()
    if (!(await dialog.waitFor({ timeout: 5000 }).then(() => true, () => false))) return
    const gotIt = dialog.getByRole('button', { name: acknowledgeTip }).first()
    const dismiss = dialog.getByRole('button', {
      name: /^(Close|关闭|Later|稍后|Skip|跳过|Cancel|取消|Dismiss|忽略)$/i
    }).first()
    if (await gotIt.isVisible()) await gotIt.click(waits)
    else if (await dismiss.isVisible()) await dismiss.click(waits)
    else await page.keyboard.press('Escape')
    await dialog.waitFor({ ...waits, state: 'hidden' })
  }

  async function pickSession(label, add) {
    if (add) {
      await button(caption('Add session', '添加会话')).click(waits)
    } else {
      await button(caption('New work object', '新建工作对象')).click(waits)
      await page.getByRole('menuitem', { name: caption('New workspace', '新建工作空间'), exact: true }).click(waits)
    }
    const picker = page.getByRole('dialog', { name: caption('Choose a session', '选择会话'), exact: true })
    await picker.locator('[cmdk-input]').fill(workspaceChatTitle, waits)
    const sameTitle = picker.getByRole('option').filter({ has: page.getByText(workspaceChatTitle, { exact: true }) })
    await sameTitle.filter({ has: page.getByText(localHostLabel) }).waitFor(waits)
    await sameTitle.filter({ has: page.getByText(hostName, { exact: true }) }).waitFor(waits).catch(async error => {
      const stateFacts = await page.evaluate(({ owner, worktree, tab, conversation }) => {
        const state = window.__store.getState()
        const host = state.runtimeEnvironments.find(item => item.id === owner)
        const status = state.runtimeStatusByEnvironmentId.get(owner)
        const hostId = `runtime:${encodeURIComponent(owner)}`
        const native = (state.unifiedTabsByWorktree[worktree] ?? []).find(item => item.id === tab)
        return {
          knownWorktree: Boolean(state.getKnownWorktreeById(worktree, hostId)),
          publishedWorktreeHosts: Object.values(state.worktreesByRepo).flat()
            .filter(item => item.id === worktree)
            .map(item => [item.hostId ?? null, Boolean(item.runtimeOwnerEnvironmentId)]),
          catalogued: Boolean(host),
          retired: state.removedRuntimeEnvironmentIds.has(owner),
          contact: status?.contact?.verdict ?? null,
          remoteStatusPresent: Boolean(status?.status),
          remoteTabPresent: Boolean(native),
          remoteTabOwnerMatches: native?.executionHostId === hostId,
          remoteGroupPresent: (state.groupsByWorktree[worktree] ?? []).some(group => group.id === native?.groupId),
          nativeSessionMatches: Object.values(state.unifiedTabsByWorktree).flat()
            .filter(item => item.contentType === 'agent-session' && item.entityId === conversation).length
        }
      }, { owner: environmentId, worktree: remoteWorkspace, tab: studioChat.id, conversation: studioChat.entityId })
      write('workspace-picker-diagnostics.json', stateFacts)
      throw new Error(`Studio was not offered: ${JSON.stringify(stateFacts)}\n${error.message}`, { cause: error })
    })
    assert.equal(await sameTitle.count(), 2)
    await sameTitle.filter({ has: page.getByText(label, { exact: true }) }).click(waits)
    await picker.waitFor({ ...waits, state: 'hidden' })
  }

  async function assertPane(host, reply, otherReply, expectedDraft) {
    const region = pane(host)
    await region.waitFor(waits)
    await region.getByText(reply, { exact: true }).waitFor(waits)
    assert.equal(await region.getByText(otherReply, { exact: true }).count(), 0)
    if (expectedDraft !== undefined) {
      await poll(
        () => composer(host).innerText(waits),
        actual => actual === expectedDraft,
        `The draft in ${host === 'local' ? 'Local' : 'Studio'} did not match`
      )
    }
  }

  async function assertFocus(host) {
    await page.waitForFunction(owner => {
      const active = document.activeElement
      const pane = active?.closest('[data-workspace-preview-session]')
      return pane?.getAttribute('data-execution-host') === owner &&
        pane.getAttribute('data-focused') === 'true' &&
        Boolean(active.closest('[data-native-chat-composer-scope]'))
    }, host, waits)
  }

  async function studioRuntimeIdentity() {
    const result = await page.evaluate(selector =>
      window.api.runtimeEnvironments.call({ selector, method: 'status.get', params: {} }), environmentId)
    assert.ok(result.ok && result.result?.runtimeId, 'The paired Studio runtime identity could not be read')
    return result.result.runtimeId
  }

  async function nameChat(tabId) {
    const escaped = await page.evaluate(id => CSS.escape(id), tabId)
    const tab = page.locator(`[data-tab-id=${escaped}]:visible`).first()
    await tab.dblclick(waits)
    const rename = page.locator('[data-tab-rename-input=true]:visible')
    await rename.fill(workspaceChatTitle, waits)
    await rename.press('Enter')
    await tab.getByText(workspaceChatTitle, { exact: true }).waitFor(waits)
  }

  async function removeStudioPairing() {
    await button(caption('Return to worktree', '返回工作树')).click(waits)
    await preview().waitFor({ ...waits, state: 'hidden' })
    await button(/^(Settings|设置)$/i).click(waits)
    await button(/^(Remote (Porpita|Orca) Servers|远程 (Porpita|Orca) 服务器)$/i).click(waits)
    const server = page.locator(`[data-settings-section=${JSON.stringify(environmentId)}]`)
    await server.getByText(hostName, { exact: true }).waitFor(waits)
    await server.getByRole('button', {
      name: caption(`More actions for ${hostName}`, `${hostName} 的更多操作`),
      exact: true
    }).click(waits)
    await page.getByRole('menuitem', { name: caption('Remove…', '移除…'), exact: true }).click(waits)
    const confirmation = page.getByRole('dialog', { name: caption('Remove Server', '删除服务器'), exact: true })
    await confirmation.getByText(hostName, { exact: true }).waitFor(waits)
    await confirmation.getByRole('button', { name: caption('Remove', '移除'), exact: true }).click(waits)
    await confirmation.waitFor({ ...waits, state: 'hidden' })
    await server.waitFor({ ...waits, state: 'hidden' })
    await button(/^(Back to app|返回应用|回到应用)$/i).click(waits)
    await enterPreview()
  }

  if (workspacePortsFocused) {
    const { observeFixedPorts } = require('./observe-workspace-ports-continuity.cjs')
    await observeFixedPorts({
      browser: () => page, caption, waits, step, episode, write, preview, enterPreview, setSize,
      desktopApp: () => app,
      selectedChat, poll, localWorkspace, remoteWorkspace, studioHost, hostName, localRoot, studioRoot,
      stopStudio, restartStudio, removeStudioPairing
    })
    return
  }

  await step('i21-resume-local-chat', 'Resume the Local Vault result and verify the two original Native Chat identities', async () => {
    assert.ok(studioChat && localWorkspace && remoteWorkspace, 'Both original worktrees are required')
    await nameChat(studioChat.id)
    const escaped = await page.evaluate(id => CSS.escape(id), localWorkspace)
    await page.locator(`[data-worktree-id=${escaped}] [data-worktree-card-surface]`).first().click(waits)
    await poll(selectedChat, active => active.workspaceId === localWorkspace, 'The Local worktree was not selected')
    await assertHistoryRows()
    await localRow.getByTestId('ai-vault-session-more-actions').click(waits)
    await page.getByRole('menuitem', { name: caption('Resume in New Chat', '在新聊天中恢复'), exact: true }).click(waits)
    const trust = button(/^(信任仓库|Trust repository)$/i)
    if (await trust.waitFor({ timeout: 3500 }).then(() => true, () => false)) {
      await trust.click(waits)
    }
    const native = page.locator('[data-native-chat-root=true]:visible')
    await native.getByText(localReply, { exact: true }).waitFor(waits)
    assert.equal(await native.getByText(remoteReply, { exact: true }).count(), 0)
    localChat = await poll(selectedChat, active => active.workspaceId === localWorkspace &&
      active.contentType === 'agent-session', 'The Local Native Chat did not become active')
    assert.equal(localChat.tabHost, 'local')
    assert.notEqual(localChat.id, studioChat.id, 'The fixture must use distinct original tab IDs')
    assert.notEqual(localChat.sessionId, studioChat.entityId, 'The fixture must use distinct Native Chat IDs')
    await nameChat(localChat.id)
    await native.locator('[data-native-chat-composer-scope] [contenteditable=true]').first().fill(originalLocalDraft, waits)
    const dock = page.locator('[data-workspace-sidebar-toggle=right][aria-expanded=true]:visible').first()
    if (await dock.isVisible()) await dock.click(waits)
    const sessions = button(caption('Sessions', '会话'))
    if (await sessions.getAttribute('aria-pressed') !== 'true') await sessions.click(waits)
    const directory = page.locator('[data-session-index]')
    const studio = directory.getByRole('option')
      .filter({ has: page.getByText(workspaceChatTitle, { exact: true }) })
      .filter({ has: page.getByText(hostName, { exact: true }) })
    await studio.waitFor(waits)
    if (!(await studio.isEnabled())) {
      await directory.getByRole('button', { name: caption('Session filters', '会话筛选'), exact: true }).click(waits)
      await page.getByRole('menuitemradio', { name: hostName, exact: true }).click(waits)
      await directory.getByRole('button', { name: caption('Reconnect', '重新连接'), exact: true }).click(waits)
      await poll(() => studio.isEnabled(), Boolean, 'The directory could not confirm the original Studio source')
    }
    check.originals = { distinctNativeSessionIds: true, distinctNativeTabIds: true }
  })

  await step('i21-mixed-workspace', 'Pick the same chat title twice using the distinct Host badges and keep both drafts independent', async () => {
    assert.ok(localChat, 'The Local Chat was not adopted')
    await setSize(1280, 800)
    await enterPreview()
    await episode('workspace-host-composition', [
      ['Choose the Local title from the Workspace picker', () => pickSession(localHostLabel, false)],
      ['Add the same title from Studio', () => pickSession(hostName, true)],
      ['Check independent owner content and update only the Studio draft', async () => {
        await assertPane('local', localReply, remoteReply, originalLocalDraft)
        await assertPane(studioHost, remoteReply, localReply, studioDraft)
        await composer(studioHost).fill(workspaceStudioDraft, waits)
        await assertFocus(studioHost)
        assert.equal(await composer('local').innerText(), originalLocalDraft)
      }]
    ])
    assert.equal(await split().getAttribute('data-preview-split'), 'side-by-side')
    assert.equal(await preview().locator('[data-workspace-preview-session]:visible').count(), 2)
    await pane('local').getByText(localHostLabel).first().waitFor(waits)
    await pane(studioHost).getByText(hostName, { exact: true }).first().waitFor(waits)
    assert.equal(await pane('local').getAttribute('data-workspace-preview-session'), localChat.id)
    assert.equal(await pane(studioHost).getAttribute('data-workspace-preview-session'), studioChat.id)
    workspaceId = await preview().locator('[data-workspace-preview-object]').getAttribute('data-workspace-preview-object')
    assert.ok(workspaceId, 'The combined workspace did not have an identity')
    check.mixed = { sameTitleHostsDistinguished: true, originalTranscripts: true, separateDrafts: true }
  })

  if (workspaceExplorerContinuity) {
    const { observeExplorer } = require('./observe-workspace-explorer-continuity.cjs')
    return observeExplorer({
      desktop: () => ({ page, app }),
      step, episode, write, waits, caption, hostName, studioHost, localHostLabel, workspaceChatTitle,
      workspaceId, localWorkspace, remoteWorkspace, environmentId, preview, pane, composer,
      enterPreview, setSize, poll, readLayout, studioRuntimeIdentity, restartStudio, stopStudio,
      removeStudioPairing, studioRoot, localRoot, workspaceUsageContinuity, workspacePortsContinuity,
      restartDesktop: async () => {
        ;({ app, page, win } = await restartWorkspaceDesktop())
        await page.waitForFunction(() => window.__store?.getState().activeView === 'terminal', null, waits)
        await dismissColdStartTip()
        await enterPreview()
      }
    })
  }

  await step('i21-reopen-from-directory', 'Find the composed Studio Chat in the directory and return to its original Workspace Pane', async () => {
    assert.ok(workspaceId, 'The combined workspace was not created')
    await button(caption('Return to worktree', '返回工作树')).click(waits)
    await preview().waitFor({ ...waits, state: 'hidden' })
    const sessions = button(caption('Sessions', '会话'))
    await sessions.waitFor(waits)
    if (await sessions.getAttribute('aria-pressed') !== 'true') await sessions.click(waits)
    const directory = page.locator('[data-session-index]')
    await directory.locator('[cmdk-input]').fill(workspaceChatTitle, waits)
    const studio = directory.getByRole('option')
      .filter({ has: page.getByText(workspaceChatTitle, { exact: true }) })
      .filter({ has: page.getByText(hostName, { exact: true }) })
    await studio.click(waits)
    await assertPane(studioHost, remoteReply, localReply, workspaceStudioDraft)
    await assertFocus(studioHost)
    assert.equal(await preview().locator('[data-workspace-preview-object]').getAttribute('data-workspace-preview-object'), workspaceId)
    check.directory = { sameWorkspace: true, studioComposerFocused: true }
  })

  await step('i21-short-pane', 'Switch between the original Hosts at 600 × 460 with reduced motion', async () => {
    assert.ok(workspaceId, 'The combined workspace was not created')
    await episode('workspace-host-short-switch', [
      ['Narrow the preview while Studio is focused', async () => {
        await setSize(600, 460)
        await page.emulateMedia({ reducedMotion: 'reduce' })
        await pane('local').waitFor({ ...waits, state: 'hidden' })
        await assertPane(studioHost, remoteReply, localReply, workspaceStudioDraft)
        assert.equal(await split().getAttribute('data-preview-split'), 'focused')
      }],
      ['Choose Local from the same-title pane menu', async () => {
        await button(caption('Switch pane', '切换窗格')).click(waits)
        const localChoice = page.getByRole('menuitemradio').filter({ hasText: workspaceChatTitle })
          .filter({ has: page.getByText(localHostLabel) })
        await localChoice.click(waits)
        await pane(studioHost).waitFor({ ...waits, state: 'hidden' })
        await assertPane('local', localReply, remoteReply, originalLocalDraft)
        await assertFocus('local')
      }]
    ])
    assert.equal(await preview().locator('[data-workspace-preview-session]:visible').count(), 1)
    check.short = { hostChangedWithSameWorkspace: true, onlySelectedPaneVisible: true, localComposerFocused: true }
  })

  await step('i22-save-qualified-layout', 'Persist Host, pairing, focus, and splitter ratio through the real preview', async () => {
    assert.ok(workspaceId, 'The combined workspace was not created')
    await setSize(1280, 800)
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    const divider = preview().getByRole('separator')
    await divider.waitFor(waits)
    await divider.press('ArrowRight', waits)
    assert.equal(await divider.getAttribute('aria-valuenow'), '55')
    await composer(studioHost).click(waits)
    await assertFocus(studioHost)
    pairingRevision = await page.evaluate(selector => {
      const owner = window.__store.getState().runtimeEnvironments.find(environment => environment.id === selector)
      return owner?.pairingRevision ?? owner?.createdAt
    }, environmentId)
    assert.ok(Number.isFinite(pairingRevision), 'The paired binding has no finite catalog revision')
    const expectedRefs = [
      { executionHostId: 'local', pairingRevision: null, worktreeId: localWorkspace, conversationId: localChat.sessionId, tabId: localChat.id },
      { executionHostId: studioHost, pairingRevision, worktreeId: remoteWorkspace, conversationId: studioChat.entityId, tabId: studioChat.id }
    ]
    const expectedFocus = JSON.stringify([studioHost, pairingRevision, remoteWorkspace, studioChat.entityId])
    savedLayout = await poll(readLayout, layout => {
      const workspace = selectedWorkspace(layout)
      return layout?.version === 3 && workspace?.id === workspaceId &&
        workspace.ratio === 0.55 && workspace.focusedSession === expectedFocus
    }, 'The workspace profile did not acknowledge size and focus after the edits')
    assert.deepEqual(selectedWorkspace(savedLayout).sessions, expectedRefs)
    assert.deepEqual(JSON.parse(fs.readFileSync(layoutFile, 'utf8')), savedLayout)
    check.saved = { version: savedLayout.version, sourceQualifiedRefs: true, hostQualifiedFocus: true, ratio: 0.55, diskMatches: true }
  })

  await step('i22-cold-mixed-restore', 'Close and relaunch only desktop, then reopen the same Host-qualified Workspace', async () => {
    assert.ok(savedLayout, 'A workspace profile was not saved')
    const desktopPid = app.process().pid
    const studioRuntime = await studioRuntimeIdentity()
    ;({ app, page, win } = await restartWorkspaceDesktop())
    assert.notEqual(app.process().pid, desktopPid)
    await page.waitForFunction(() => window.__store?.getState().activeView === 'terminal', null, waits)
    await dismissColdStartTip()
    await enterPreview()
    await assertPane('local', localReply, remoteReply, originalLocalDraft)
    await assertPane(studioHost, remoteReply, localReply, workspaceStudioDraft)
    assert.equal(await preview().locator('[data-workspace-preview-object]').getAttribute('data-workspace-preview-object'), workspaceId)
    assert.equal(await preview().getByRole('separator').getAttribute('aria-valuenow'), '55')
    assert.equal(await pane(studioHost).getAttribute('data-focused'), 'true')
    assert.equal(await pane('local').getAttribute('data-focused'), 'false')
    assert.equal(await studioRuntimeIdentity(), studioRuntime, 'Studio should stay running when the desktop relaunches')
    assert.deepEqual(await readLayout(), savedLayout)
    check.cold = { desktopProcessChanged: true, studioProcessKept: true, workspaceKept: true, qualifiedFocusKept: true, originalDraftsKept: true }
  })

  await step('i23-studio-outage', 'Stop Studio while the composed Workspace is open and keep working in Local', async () => {
    assert.ok(savedLayout, 'A workspace profile was not saved')
    assert.ok(check.cold, 'The Workspace must reopen before testing outage')
    await episode('workspace-host-outage', [
      ['Stop the isolated Studio Runtime', stopStudio],
      ['Wait for the targeted reconnect button', async () => {
        await reconnect().waitFor(waits).catch(async error => {
          const observation = await page.evaluate(selector => {
            const entry = window.__store.getState().runtimeStatusByEnvironmentId.get(selector)
            return {
              contact: entry?.contact?.verdict ?? null,
              transport: entry?.snapshot?.transport ?? null,
              verification: entry?.snapshot?.verification ?? null
            }
          }, environmentId)
          write('workspace-outage-diagnostics.json', { ...observation, notice: await hostNotice().allTextContents() })
          throw error
        })
      }]
    ])
    assert.equal(await reconnect().isEnabled(), true)
    assert.equal(await pane('local').getByRole('button', { name: caption('Reconnect', '重新连接'), exact: true }).count(), 0)
    await assertPane('local', localReply, remoteReply, originalLocalDraft)
    await composer('local').fill(offlineLocalDraft, waits)
    await assertFocus('local')
    assert.equal(await composer('local').innerText(), offlineLocalDraft)
    assert.equal(await preview().locator('[data-workspace-preview-object]').getAttribute('data-workspace-preview-object'), workspaceId)
    const durable = await readLayout()
    assert.deepEqual(selectedWorkspace(durable).sessions, selectedWorkspace(savedLayout).sessions)
    check.offline = { onlyStudioOfferedReconnect: true, localComposerEditable: true, layoutSlotsKept: true }
  })

  await step('i23-studio-reconnect', 'Recover Studio in place and verify both drafts and the saved split', async () => {
    assert.ok(check.offline, 'Studio must be stopped with the mixed Workspace visible')
    let recovery = 'pane reconnect'
    await episode('workspace-host-recovery', [
      ['Restart the same isolated Studio Runtime', restartStudio],
      ['Use the Studio pane Reconnect action when it is still offered', async () => {
        try {
          await reconnect().click({ timeout: 3000 })
        } catch (error) {
          if (error.name !== 'TimeoutError') throw error
          recovery = 'automatic reconnect'
        }
        await reconnect().waitFor({ ...waits, state: 'hidden' })
        await hostNotice().waitFor({ ...waits, state: 'hidden' })
      }],
      ['Review the original Studio draft and the Local offline edit', async () => {
        await assertPane(studioHost, remoteReply, localReply, workspaceStudioDraft)
        await assertPane('local', localReply, remoteReply, offlineLocalDraft)
        await composer(studioHost).click(waits)
        await assertFocus(studioHost)
      }]
    ])
    assert.equal(await preview().getByRole('separator').getAttribute('aria-valuenow'), '55')
    assert.deepEqual(selectedWorkspace(await readLayout()).sessions, selectedWorkspace(savedLayout).sessions)
    check.recovered = { trigger: recovery, studioDraftKept: true, localEditKept: true, originalWorkspaceKept: true }
  })

  await step('i23-pairing-removed', 'Remove the isolated Studio pairing in Settings and reopen the saved Workspace', async () => {
    assert.ok(check.recovered, 'Studio must recover before testing removal')
    await removeStudioPairing()
    await pane(studioHost).getByText(caption(
      'This session is unavailable in its original worktree.',
      '原工作树中的会话目前不可用。'
    ), { exact: true }).waitFor(waits)
    assert.equal(await composer(studioHost).count(), 0)
    assert.equal(await pane(studioHost).getByText(remoteReply, { exact: true }).count(), 0)
    assert.deepEqual(selectedWorkspace(await readLayout()).sessions, selectedWorkspace(savedLayout).sessions)
    await assertPane('local', localReply, remoteReply, offlineLocalDraft)
    check.retired = { catalogEntryRemoved: true, savedUnavailableSlotKept: true, remoteTranscriptHidden: true, localDraftKept: true }
  })

  await step('i23-remove-stale-reference', 'Remove the unavailable reference from the same Workspace and leave Local in focus', async () => {
    assert.ok(check.retired, 'The Studio pairing was not visibly removed')
    await pane(studioHost).getByRole('button', {
      name: caption('Remove pane from workspace', '从工作空间移除窗格'),
      exact: true
    }).click(waits)
    await pane(studioHost).waitFor({ ...waits, state: 'hidden' })
    await assertPane('local', localReply, remoteReply, offlineLocalDraft)
    await assertFocus('local')
    const remaining = await poll(readLayout, layout => {
      const workspace = selectedWorkspace(layout)
      return workspace?.id === workspaceId && workspace.sessions.length === 1
    }, 'The same Workspace did not save the removal of its unavailable pane')
    assert.deepEqual(selectedWorkspace(remaining).sessions, [selectedWorkspace(savedLayout).sessions[0]])
    assert.equal(selectedWorkspace(remaining).focusedSession,
      JSON.stringify(['local', null, localWorkspace, localChat.sessionId]))
    check.removed = { onlyLocalReferenceRemains: true, sameWorkspace: true, localInputFocus: true }
  })

  write('workspace-host-continuity-checks.json', check)
}

module.exports = { observe }
