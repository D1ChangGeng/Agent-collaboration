const assert = require('node:assert/strict')
const { seedTranscript } = require('./observe-session-history.cjs')

const title = 'Follow up on the release checklist'
const body = 'The saved release notes are ready for review.'

function seed({ home, repo }) {
  return seedTranscript({
    home, repo, prompt: title, reply: body, clock: '06',
    id: '019f1000-1111-7222-8333-444444444456'
  })
}

async function observe({ page, step, episode, write, waits, caption, appButton, changeSize, secondChat, b, ownerB }) {
  const directory = page.locator('[data-session-index]')
  const history = directory.locator('[data-session-index-history]')
  const historySearch = history.getByRole('textbox', { name: caption('Search sessions', '搜索会话'), exact: true })
  const filters = appButton('Session filters', '会话筛选')
  const records = history.locator('.ai-vault-session-row:visible')
  const row = records.filter({ hasText: title })
  const original = records.filter({ hasText: secondChat })
  const mode = async (en, zh) => {
    await filters.click(waits)
    const menu = page.getByRole('menu')
    await menu.getByRole('menuitemradio', { name: caption(en, zh), exact: true }).click(waits)
    await menu.waitFor({ ...waits, state: 'hidden' })
  }
  const proof = {}
  const chatTabs = () => page.evaluate(owner => (
    (window.__store.getState().unifiedTabsByWorktree[owner] ?? [])
      .filter(tab => tab.contentType === 'agent-session')
      .map(tab => ({ id: tab.id, sessionId: tab.entityId }))
  ), ownerB)
  const initial = await chatTabs()
  assert.ok(initial.some(tab => tab.id === b.id))
  await step('i18-history-mode', 'Use the left sidebar to browse history without an open pane', async () => {
    const rightToggle = page.locator('[data-workspace-sidebar-toggle=right]:visible').first()
    if (await rightToggle.getAttribute('aria-expanded') === 'true') await rightToggle.click(waits)
    await changeSize(860, 580)
    await mode('Unopened history', '未打开的历史会话')
    await historySearch.waitFor(waits)
    assert.equal(await historySearch.inputValue(), secondChat.split(' · ')[0])
    await historySearch.fill('', waits)
    await row.waitFor(waits)
    assert.equal(await original.count(), 0)
    const notices = history.getByRole('button', { name: caption('Scan notices', '扫描提示'), exact: true })
    const noticesExercised = await notices.isVisible()
    if (noticesExercised) {
      await notices.click(waits)
      await history.getByTestId('ai-vault-scan-notices').waitFor(waits)
      await notices.click(waits)
      await history.getByTestId('ai-vault-scan-notices').waitFor({ ...waits, state: 'hidden' })
    }
    const rowsRoom = await row.evaluate(element => {
      const pane = element.closest('.scrollbar-sleek')
      const action = element.querySelector('[data-testid=ai-vault-session-more-actions]')
      const bound = pane?.getBoundingClientRect()
      const rect = action?.getBoundingClientRect()
      return bound && rect && rect.top >= bound.top && rect.bottom <= bound.bottom
    })
    assert.equal(rowsRoom, true)
    assert.deepEqual(await chatTabs(), initial)
    proof.scan = { actualHistory: true, openedRowExcluded: true, noImplicitOpen: true, actionFits: true, noticesExercised }
  })
  await step('i18-native-resume', 'Resume the selected saved transcript using the native Vault command', async () => {
    const newChat = page.getByRole('menuitem', { name: /^(Resume in New Chat|在新聊天中恢复)$/i })
    const transcript = page.locator('[data-native-chat-root=true]:visible').getByText(body, { exact: true })
    await episode('unopened-to-chat', [
      ['open the saved row’s existing action menu', () => row.getByTestId('ai-vault-session-more-actions').click(waits)],
      ['restore in a new Chat tab', () => newChat.click(waits)],
      ['read the original transcript in Native Chat', () => transcript.waitFor(waits)]
    ])
    await page.waitForFunction(() =>
      Boolean(document.activeElement?.closest('[data-native-chat-composer-scope]')), null, waits)
    const next = await chatTabs()
    assert.equal(next.length, initial.length + 1)
    assert.ok(initial.every(tab => next.some(entry => tab.id === entry.id && tab.sessionId === entry.sessionId)))
    await row.waitFor({ ...waits, state: 'hidden' })
    proof.resume = { transcriptDisplayed: true, oneNewTab: true, originalTabsRetained: true, removedFromUnopened: true }
  })
  await step('i18-directory-return', 'Return from history mode and keep the approved open-chat filters', async () => {
    await mode('Open chats', '已打开的聊天')
    const input = directory.locator('[cmdk-input]')
    await input.waitFor(waits)
    assert.equal(await input.inputValue(), secondChat.split(' · ')[0])
    assert.equal(await filters.getAttribute('data-session-index-scope'), 'workspace')
    await directory.getByRole('option').filter({ hasText: secondChat }).waitFor(waits)
    proof.openView = { queryPreserved: true, locationPreserved: true }
  })
  write('unopened-history-checks.json', proof)
}

module.exports = { seed, observe }
