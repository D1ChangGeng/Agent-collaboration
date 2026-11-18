const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const title = 'Review the workspace handoff'
const closedId = '019f1000-1111-7222-8333-444444444441'
const originalId = '019f1000-1111-7222-8333-444444444442'
const terminalResumeId = '019f1000-1111-7222-8333-444444444443'

function seedTranscript({ home, repo, id, clock, reply, prompt = title }) {
  const dir = path.join(home, '.codex', 'sessions', '2026', '09', '04')
  fs.mkdirSync(dir, { recursive: true })
    const timestamp = `2026-09-04T12:00:${clock}.000Z`
    const file = path.join(dir, `rollout-2026-09-04T12-00-${clock}-${id}.jsonl`)
    const records = [
      { type: 'session_meta', payload: {
        id, timestamp, cwd: repo, originator: 'codex_cli_rs', source: 'cli', history_mode: 'paginated'
      } },
      { type: 'response_item', payload: {
        type: 'message', role: 'user', id: 'input', content: [{ type: 'input_text', text: prompt }]
      } },
      { type: 'event_msg', payload: {
        type: 'item_completed', thread_id: id, turn_id: 'turn-0', completed_at_ms: Date.parse(timestamp),
        item: { type: 'UserMessage', id: 'user-0', content: [{ type: 'text', text: prompt }] }
      } },
      { type: 'response_item', payload: {
        type: 'message', role: 'assistant', id: 'answer-0', content: [{ type: 'output_text', text: reply }]
      } },
      { type: 'event_msg', payload: {
        type: 'item_completed', thread_id: id, turn_id: 'turn-0', completed_at_ms: Date.parse(timestamp),
        item: { type: 'AgentMessage', id: 'answer-0', content: [{ type: 'Text', text: reply }] }
      } }
    ]
    fs.writeFileSync(file, records.map((record, ordinal) => JSON.stringify({ timestamp, ordinal, ...record })).join('\n') + '\n')
  return file
}

function seed({ home, repo }) {
  const transcript = (id, clock, reply, prompt) =>
    seedTranscript({ home, repo, id, clock, reply, prompt })
  return {
    original: transcript(originalId, '02', 'This conversation belongs to the existing terminal.'),
    closed: transcript(closedId, '01', 'This conversation can be reopened from history.'),
    terminalResume: transcript(terminalResumeId, '00', 'This conversation is available in Terminal.', 'Review the terminal checklist')
  }
}

async function observe({
  page, win, app, click, button, step, episode, write, repo, fixtures, baseline
}) {
  const waits = { timeout: 20000 }
  const rows = page.locator('.ai-vault-session-row:visible')
  const original = rows.filter({ hasText: 'This conversation belongs to the existing terminal.' })
  const closed = rows.filter({ hasText: 'This conversation can be reopened from history.' })
  const closedTerminal = rows.filter({ hasText: 'This conversation is available in Terminal.' })
  const search = page.getByRole('textbox', { name: /^(Search sessions|搜索会话)$/i }).first()
  const jump = original.getByTestId('ai-vault-session-jump-original-pane')
  const resume = closed.getByTestId('ai-vault-session-resume')
  const chatRoot = page.locator('[data-native-chat-root=true]:visible')
  const chatJump = closed.getByTestId('ai-vault-session-jump-original-pane')
  const composer = page.locator('[data-native-chat-composer-scope] [contenteditable=true]:visible').first()
  const tabControl = id => page.locator(`[data-tab-id="${id}"]:visible`).first()
  const snapshot = () => page.evaluate(() => {
    const state = window.__store.getState()
    const id = state.activeWorktreeId
    const tab = state.activeTabIdByWorktree[id]
    return {
      owner: id,
      tab,
      leaf: state.terminalLayoutsByTabId[tab]?.activeLeafId ?? null,
      terminalTabs: state.tabsByWorktree[id]?.length ?? 0,
      chatTabs: (state.unifiedTabsByWorktree[id] ?? [])
        .filter(tab => tab.contentType === 'agent-session')
        .map(tab => ({ id: tab.id, entityId: tab.entityId })),
      terminalFocused: Boolean(document.activeElement?.closest('.xterm')),
      composerFocused: Boolean(document.activeElement?.closest('[data-native-chat-composer-scope]'))
    }
  })
  const waitForTerminalFocus = target => page.waitForFunction(({ tab, leaf }) => {
    const store = window.__store.getState()
    return store.activeTabId === tab &&
      store.terminalLayoutsByTabId[tab]?.activeLeafId === leaf &&
      document.activeElement?.closest('.pane')?.getAttribute('data-leaf-id') === leaf
  }, target, waits)
  const openHistory = async () => {
    if (!(await search.isVisible())) {
      if (!(await button(/^(智能体|Agents)(?:\s|$)/i).isVisible())) {
        await click(/(?:toggle|show|显示|切换).*(?:dock|right sidebar|侧边栏|侧栏)|(?:right sidebar|右侧边栏)/i)
      }
      await click(/^(智能体|Agents)(?:\s|$)/i)
    }
    await search.waitFor(waits)
  }
  const dismissCards = async () => {
    for (const id of ['chat-ui-here-corner-heading', 'codex-shared-settings-notice-heading']) {
      const card = page.locator(`[aria-labelledby="${id}"]`)
      if (await card.isVisible()) {
        await card.getByRole('button', { name: /^(Dismiss|关闭|忽略|不再显示)$/i }).click(waits)
      }
    }
    const setup = button(/^(Dismiss setup scripts|关闭安装脚本)$/i)
    if (await setup.isVisible()) await setup.click(waits)
  }
  // This repository contains only the files written by the replay harness.
  const trustFixture = async () => {
    const trust = button(/^(信任仓库|Trust repository)$/i)
    await trust.waitFor({ timeout: 3500 }).then(() => trust.click(waits), error => {
      if (error.name !== 'TimeoutError') throw error
    })
  }
  const readTerminal = (owner) => {
    const store = window.__store.getState()
    const tab = store.activeTabIdByWorktree[owner]
    return window.__paneManagers?.get(tab)?.getActivePane()?.serializeAddon?.serialize?.() ?? ''
  }
  const state = {}
  let terminal, publishStatus
  await step('i4-history', 'Read two same-title Codex transcripts through the actual history scanner', async () => {
    await app.evaluate(({ dialog }, fixture) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [fixture] })
    }, repo)
    await click(/^(添加项目|Add project)$/i)
    await click(/浏览文件夹|Browse folder/i)
    await page.getByText('UI-spec-sample', { exact: true }).first().waitFor(waits)
    await page.locator('.pane .xterm:visible').first().waitFor(waits)
    terminal = await snapshot()
    assert.ok(terminal.tab && terminal.leaf)
    const { owner, tab, leaf } = terminal
    publishStatus = (sessionId, transcript) => page.evaluate(
      ({ owner, tab, leaf, sessionId, transcript, title }) => {
        // Only the provider status signal is supplied; terminal, pane, files and scan are real.
        const state = window.__store.getState()
        const paneKey = `${tab}:${leaf}`
        state.removeAgentStatus(paneKey)
        state.setAgentStatus(
          paneKey,
          { state: 'waiting', prompt: title, agentType: 'codex' },
          'Codex',
          undefined,
          { worktreeId: owner, tabId: tab, connectionId: null },
          sessionId ? { providerSession: { key: 'session_id', id: sessionId, transcriptPath: transcript } } : undefined
        )
      },
      { owner, tab, leaf, sessionId, transcript, title }
    )
    await publishStatus(originalId, fixtures.original)
    await dismissCards()
    await openHistory()
    await original.waitFor(waits)
    await closed.waitFor(waits)
    assert.equal(await rows.filter({ hasText: title }).count(), 2)
    state.rowsFound = 2
    state.restingOriginal = {
      jump: await jump.count() > 0,
      resume: await original.getByTestId('ai-vault-session-resume').count() > 0,
      jumpClickable: (await jump.count()) > 0 && await jump.evaluate(el =>
        getComputedStyle(el).pointerEvents !== 'none' &&
        getComputedStyle(el.parentElement).opacity !== '0')
    }
  })
  if (!publishStatus) throw new Error('History fixture did not initialize')
  if (baseline) {
    write('history.json', state)
    return
  }
  await step('i4-actions', 'Compare navigation and recovery with pointer away from the rows', async () => {
    await search.focus()
    for (const control of [jump, resume]) {
      await control.waitFor(waits)
      assert.equal(await control.isEnabled(), true)
      assert.equal(await control.evaluate(el => getComputedStyle(el).opacity), '1')
    }
    assert.equal(await original.getByTestId('ai-vault-session-resume').count(), 0)
    assert.equal(await closed.getByTestId('ai-vault-session-jump-original-pane').count(), 0)
    assert.equal(await original.locator('[draggable="true"]').count(), 0)
    // A title match whose live entry is missing its confirmed identity cannot become a jump.
    await publishStatus()
    await jump.waitFor({ state: 'detached', ...waits })
    await publishStatus(originalId, fixtures.original)
    await jump.waitFor(waits)
  })
  await step('i4-read-history', 'Expand the closed row to read its transcript before choosing Resume', async () => {
    await closed.getByTestId('ai-vault-session-toggle-details').click(waits)
    assert.equal(await closed.getByTestId('ai-vault-session-toggle-details').getAttribute('aria-expanded'), 'true')
    assert.equal((await snapshot()).terminalTabs, terminal.terminalTabs)
    state.readWithoutLaunching = true
  })
  await step('i4-original', 'Use Enter on Jump to Original Pane and return to its exact terminal input', async () => {
    const toggle = closed.getByTestId('ai-vault-session-toggle-details')
    await toggle.press('Space', waits)
    assert.equal(await toggle.getAttribute('aria-expanded'), 'false')
    await episode('return-to-terminal', [
      ['focus the history row action', () => jump.focus()],
      ['activate the original pane with Enter', async () => {
        await page.keyboard.press('Enter')
        await waitForTerminalFocus({ tab: terminal.tab, leaf: terminal.leaf })
      }]
    ])
    const result = await snapshot()
    assert.equal(result.owner, terminal.owner)
    assert.equal(result.tab, terminal.tab)
    assert.equal(result.leaf, terminal.leaf)
    assert.equal(result.terminalTabs, terminal.terminalTabs)
    state.originalPane = { sameTab: true, sameLeaf: true, noDuplicateTab: true, inputFocused: true }
  })
  await step('i4-search', 'Find the same-title records through the Vault search field', async () => {
    await search.fill(title)
    await original.waitFor(waits)
    await closed.waitFor(waits)
    await page.waitForFunction(() =>
      document.querySelectorAll('.ai-vault-session-row').length === 2, null, waits)
    assert.equal((await snapshot()).terminalTabs, terminal.terminalTabs)
    state.searchFoundTwo = true
  })
  await step('i4-compact', 'Inspect both history actions at 860×520 with reduced motion', async () => {
    await search.press('Escape', waits)
    await win.evaluate(w => w.setContentSize(860, 520))
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await openHistory()
    for (const control of [jump, resume]) {
      await control.waitFor(waits)
      const fits = await control.evaluate(el => {
        const rect = el.getBoundingClientRect()
        return rect.left >= 0 && rect.right <= innerWidth && rect.top >= 0 && rect.bottom <= innerHeight
      })
      assert.equal(fits, true)
    }
  })
  let restoredChat
  await step('i4-resume-chat', 'Continue the closed Codex transcript in Native Chat with the original history', async () => {
    await win.evaluate(w => w.setContentSize(1280, 800))
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await openHistory()
    await closed.getByTestId('ai-vault-session-more-actions').click(waits)
    const resumeChat = page.getByRole('menuitem', { name: /^(Resume in New Chat|在新聊天中恢复)$/i })
    await resumeChat.click(waits)
    await trustFixture()
    await chatRoot.first().waitFor(waits)
    const text = chatRoot.getByText(
      'This conversation can be reopened from history.', { exact: true }
    )
    await text.waitFor(waits).catch(async error => {
      throw new Error(`${error.message}\n${(await chatRoot.first().innerText()).slice(-900)}`)
    })
    const after = await snapshot()
    assert.equal(after.chatTabs.length, 1)
    assert.equal(after.owner, terminal.owner)
    restoredChat = after.chatTabs[0]
    state.resumeChat = { openedTabs: 1, transcriptVisible: true }
  })
  await step('i4-chat-original', 'Return to the recovered Native Chat by clicking its history action', async () => {
    assert.ok(restoredChat)
    const draft = 'Unsent draft · 待继续'
    await composer.fill(draft)
    await tabControl(terminal.tab).click(waits)
    await openHistory()
    await chatJump.waitFor(waits)
    await episode('return-to-chat', [
      ['click Jump to Original Pane on the Chat history row', () => chatJump.click(waits)],
      ['wait for the original composer', () => page.waitForFunction(() =>
        document.activeElement?.closest('[data-native-chat-composer-scope]') != null, null, waits)]
    ])
    assert.equal(await composer.innerText(), draft)
    assert.deepEqual((await snapshot()).chatTabs, [restoredChat])
    state.originalChat = { sameTab: true, sameSession: true, inputFocused: true, draftPreserved: true }
  })
  const dialog = page.getByRole('dialog', { name: /^(Agent Session History|智能体会话历史)$/i })
  const pickerSearch = dialog.getByRole('textbox', { name: /^(Search sessions|搜索会话)$/i })
  await step('i4-resume-picker', 'Open /resume with a search on the recovered Native Chat', async () => {
    await composer.fill(`/resume ${title}`)
    await composer.press('Enter', waits)
    await pickerSearch.waitFor(waits)
    assert.equal(await pickerSearch.inputValue(), title)
    assert.equal(await pickerSearch.evaluate(element => element === document.activeElement), true)
    await dialog.locator('.ai-vault-session-row').filter({
      hasText: 'This conversation can be reopened from history.'
    }).waitFor(waits)
  })
  await step('i4-resume-picker-return', 'Select the original conversation and return to its composer', async () => {
    assert.ok(restoredChat)
    const selected = dialog.locator('.ai-vault-session-row[data-selected=true]')
    if (!(await selected.innerText()).includes('This conversation can be reopened from history.')) {
      await pickerSearch.press('ArrowDown', waits)
    }
    assert.match(await selected.innerText(), /This conversation can be reopened from history\./)
    await pickerSearch.press('Enter', waits)
    await dialog.waitFor({ state: 'hidden', ...waits })
    await page.waitForFunction(() =>
      document.activeElement?.closest('[data-native-chat-composer-scope]') != null, null, waits)
    assert.deepEqual((await snapshot()).chatTabs, [restoredChat])
    state.resumePicker = { sameTab: true, inputFocused: true }
  })
  await step('i4-resume-terminal', 'Resume the unopened terminal history in its worktree', async () => {
    await openHistory()
    const resumeCli = closedTerminal.getByTestId('ai-vault-session-resume')
    await resumeCli.dblclick(waits)
    await trustFixture()
    await page.waitForFunction(({ owner, count, tab }) => {
      const state = window.__store.getState()
      return state.activeWorktreeId === owner &&
        state.activeTabIdByWorktree[owner] !== tab &&
        state.tabsByWorktree[owner]?.length === count + 1
    }, { owner: terminal.owner, count: terminal.terminalTabs, tab: terminal.tab }, waits)
    await page.locator('.pane:visible .xterm').first().waitFor(waits)
    assert.equal((await snapshot()).terminalTabs, terminal.terminalTabs + 1)
    state.resumeTerminal = { launchedTabs: 1, output: (await page.evaluate(readTerminal, terminal.owner))
      .includes('This conversation is available in Terminal.') ? 'transcript visible' : 'launch verified' }
  })
  write('history.json', state)
}

module.exports = { seed, seedTranscript, observe }
