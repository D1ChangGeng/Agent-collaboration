const assert = require('node:assert/strict')

const localHostLabel = /^(Local Windows|Local Linux|Local Mac)$/
const studioDraft = 'Studio draft · 继续检查'
const localDraft = 'Local draft · 保留草稿'

async function observe({
  page, win, button, step, episode, write, waits, locale, title, hostName, localReply,
  remoteReply, localRow, assertHistoryRows, selectedChat, poll, localWorkspace,
  remoteWorkspace, studioChat, environmentId, restartStudio, stopStudio
}) {
  const host = `runtime:${encodeURIComponent(environmentId)}`
  const caption = (en, zh) => locale === 'zh' ? zh : en
  const directory = page.locator('[data-session-index]')
  const search = directory.getByRole('combobox', { name: caption('Find an open chat', '查找已打开的聊天') })
  const filters = directory.getByRole('button', { name: caption('Session filters', '会话筛选'), exact: true })
  const sessions = button(caption('Sessions', '会话'))
  const rows = directory.getByRole('option')
  const sameTitle = rows.filter({ has: page.getByText(title, { exact: true }) })
  const studioMatch = sameTitle.filter({ has: page.getByText(hostName, { exact: true }) })
  const localMatch = sameTitle.filter({ has: page.getByText(localHostLabel) })
  const reconnect = directory.getByRole('button', { name: caption('Reconnect', '重新连接'), exact: true })
  const unverified = studioMatch.getByText(caption('Host connection unconfirmed', '主机连接未确认'), { exact: true })
  const connectionNotice = directory.getByText(caption(
    `Could not confirm a connection to ${hostName}.`, `无法确认与 ${hostName} 的连接。`
  ), { exact: true })
  const transcripts = page.locator('[data-native-chat-root=true]:visible')
  const composer = page.locator('[data-native-chat-composer-scope] [contenteditable=true]:visible').first()
  const allHosts = caption('All hosts', '所有主机')
  let localChat
  let originalTabs
  const checks = {
    scope: {
      topology: 'Two isolated runtime profiles on the same Windows machine',
      fixture: 'Same provider session ID and title; different transcripts and worktrees',
      verification: 'Actual adopted chat IDs, input focus and unsent drafts',
      limits: 'No multi-machine latency, no shared raw worktree key, no account-backed model requests'
    }
  }

  const inventory = () => page.evaluate(({ local, studio }) => {
    const state = window.__store.getState()
    return [local, studio].map(worktreeId =>
      (state.unifiedTabsByWorktree[worktreeId] ?? [])
        .filter(tab => tab.contentType === 'agent-session')
        .map(({ id, entityId, executionHostId }) => [id, entityId, executionHostId])
    )
  }, { local: localWorkspace, studio: remoteWorkspace })

  const chooseDirectoryHost = async (name) => {
    await filters.click(waits)
    const menu = page.getByRole('menu')
    await menu.getByRole('menuitemradio', { name, exact: true }).click(waits)
    await menu.waitFor({ state: 'hidden', ...waits })
  }
  const assertOwnedChat = async (owner, tabId, sessionId, expectedReply, expectedDraft) => {
    await poll(selectedChat, active => active.id === tabId && active.activeHost === owner,
      'The directory did not activate the intended host and tab')
    const active = await selectedChat()
    assert.equal(active.contentType, 'agent-session')
    assert.equal(active.tabHost, owner)
    assert.equal(active.sessionId, sessionId)
    await transcripts.getByText(expectedReply, { exact: true }).waitFor(waits)
    assert.equal(await transcripts.getByText(
      owner === 'local' ? remoteReply : localReply, { exact: true }
    ).count(), 0)
    await page.waitForFunction(() => {
      const focused = document.activeElement
      return focused?.closest('[data-native-chat-composer-scope]') &&
        focused.closest('[data-native-chat-root=true]')?.getClientRects().length
    }, null, { ...waits, timeout: 6500 }).catch(async error => {
      const focus = await page.evaluate(() => ({
        role: document.activeElement?.getAttribute('role'),
        label: document.activeElement?.getAttribute('aria-label'),
        composer: Boolean(document.activeElement?.closest('[data-native-chat-composer-scope]')),
        chat: Boolean(document.activeElement?.closest('[data-native-chat-root=true]'))
      }))
      throw new Error(`${error.message} ${JSON.stringify(focus)}`, { cause: error })
    })
    assert.equal(await composer.innerText(), expectedDraft)
    assert.deepEqual(await inventory(), originalTabs)
    assert.equal(await search.inputValue(), title)
  }
  const assertStudio = () => assertOwnedChat(host, studioChat.id, studioChat.entityId, remoteReply, studioDraft)
  const assertLocal = () => assertOwnedChat('local', localChat.id, localChat.sessionId, localReply, localDraft)

  await step('i20-local-resume', 'Resume the Local history row before comparing the two open sessions', async () => {
    assert.ok(studioChat, 'Studio must already be open through the original Vault action')
    const escaped = await page.evaluate(id => CSS.escape(id), localWorkspace)
    const worktree = page.locator(`[data-worktree-id=${escaped}] [data-worktree-card-surface]`).first()
    await worktree.click(waits)
    await poll(selectedChat, state => state.workspaceId === localWorkspace, 'The local worktree did not open')
    await assertHistoryRows()
    await localRow.getByTestId('ai-vault-session-more-actions').click(waits)
    await page.getByRole('menuitem', { name: caption('Resume in New Chat', '在新聊天中恢复'), exact: true }).click(waits)
    const trust = button(/^(信任仓库|Trust repository)$/i)
    if (await trust.waitFor({ timeout: 3500 }).then(() => true, () => false)) {
      await trust.click(waits)
    }
    await transcripts.getByText(localReply, { exact: true }).waitFor(waits)
    assert.equal(await transcripts.getByText(remoteReply, { exact: true }).count(), 0)
    localChat = await poll(selectedChat, state => state.workspaceId === localWorkspace &&
      state.contentType === 'agent-session', 'The adopted local chat was not selected')
    assert.equal(localChat.tabHost, 'local')
    await composer.fill(localDraft, waits)
    originalTabs = await inventory()
    assert.deepEqual(originalTabs, [
      [[localChat.id, localChat.sessionId, 'local']],
      [[studioChat.id, studioChat.entityId, host]]
    ])
    const dockToggle = page.locator('[data-workspace-sidebar-toggle=right][aria-expanded=true]:visible').first()
    if (await dockToggle.isVisible()) {
      await dockToggle.click(waits)
    }
    checks.adoptedBoth = { localTranscript: true, pairedTranscript: true, nativeTabsPerOwner: [1, 1] }
  })

  await step('i20-directory-hosts', 'Inspect the Local and Studio host chips for identical titles in a compact window', async () => {
    assert.ok(localChat)
    await sessions.click(waits)
    await search.waitFor(waits)
    await chooseDirectoryHost(allHosts)
    await search.fill(title, waits)
    await win.evaluate(w => w.setContentSize(860, 520))
    await page.waitForFunction(() => innerWidth === 860 && innerHeight === 520, null, waits)
    await studioMatch.waitFor(waits)
    await localMatch.waitFor(waits)
    assert.equal(await sameTitle.count(), 2)
    for (const [row, label] of [[studioMatch, hostName], [localMatch, localHostLabel]]) {
      assert.equal(await row.isEnabled(), true)
      const chip = row.getByText(label, { exact: true })
      assert.equal(await chip.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true)
    }
    checks.ownerChips = { exactTitleMatches: 2, distinctReadableHostLabels: true, viewport: '860×520' }
  })

  await step('i20-owner-routing', 'Filter the same query by each Host and open the original focused chat', async () => {
    assert.ok(localChat)
    await win.evaluate(w => w.setContentSize(1280, 800))
    await episode('directory-host-routing', [
      ['filter to Studio', async () => {
        await chooseDirectoryHost(hostName)
        await studioMatch.waitFor(waits)
        assert.equal(await localMatch.count(), 0)
      }],
      ['open Studio with Enter and verify owner, original input and draft', async () => {
        await search.press('Enter', waits)
        await assertStudio()
      }],
      ['filter to Local and activate its result', async () => {
        await chooseDirectoryHost(localHostLabel)
        await localMatch.waitFor(waits)
        assert.equal(await studioMatch.count(), 0)
        await localMatch.click(waits)
        await assertLocal()
      }],
      ['return to All hosts with the original query', () => chooseDirectoryHost(allHosts)]
    ])
    assert.equal(await search.inputValue(), title)
    checks.routedBoth = { queryPreserved: true, nativeTabIdsPreserved: true, originalInputsFocused: true, draftsPreserved: true }
  })

  await step('i20-directory-offline', 'Keep the Local match available while Studio is offline', async () => {
    await chooseDirectoryHost(allHosts)
    await stopStudio()
    await unverified.waitFor(waits)
    assert.equal(await studioMatch.isEnabled(), false)
    assert.equal(await localMatch.isEnabled(), true)
    await localMatch.click(waits)
    await assertLocal()
    checks.offline = { studioDisabled: true, localStillOperable: true, queryPreserved: true }
  })

  await step('i20-reconnect-offer', 'Select Studio and inspect the scoped reconnect action', async () => {
    await chooseDirectoryHost(hostName)
    await connectionNotice.waitFor(waits)
    await reconnect.waitFor(waits)
    assert.equal(await studioMatch.isEnabled(), false)
    assert.equal(await localMatch.count(), 0)
    assert.equal(await search.inputValue(), title)
    checks.scopedReconnect = true
  })

  await step('i20-directory-reconnect', 'Recover Studio and reopen the same paired chat', async () => {
    let recovery = 'explicit reconnect'
    await episode('directory-host-reconnect', [
      ['restart the same Studio Runtime', restartStudio],
      ['use Reconnect if contact has not already returned', async () => {
        try {
          await reconnect.click({ timeout: 2500 })
        } catch (error) {
          if (error.name !== 'TimeoutError' || !(await studioMatch.isEnabled())) throw error
          recovery = 'automatic reconnect'
        }
        await poll(() => studioMatch.isEnabled(), Boolean, 'Studio did not become selectable again')
      }],
      ['reopen Studio with Enter and check original input and draft', async () => {
        assert.equal(await localMatch.count(), 0)
        assert.equal(await search.inputValue(), title)
        if (recovery === 'explicit reconnect') {
          await page.waitForFunction(() =>
            document.activeElement?.closest('[data-session-index]') &&
            document.activeElement?.getAttribute('role') === 'combobox', null, waits)
        }
        await search.press('ArrowDown', waits)
        await page.waitForFunction(() =>
          Boolean(document.querySelector('[data-session-index] [cmdk-item][aria-selected=true]:not([aria-disabled=true])')),
        null, waits)
        await search.press('Enter', waits)
        await assertStudio()
      }]
    ])
    checks.reconnected = { contact: recovery, sameTab: true, sameDraft: true, scopePreserved: true, queryPreserved: true }
  })

  write('session-index-host-checks.json', checks)
}

module.exports = { observe, studioDraft }
