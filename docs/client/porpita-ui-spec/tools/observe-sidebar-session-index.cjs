const assert = require('node:assert/strict')
const { seedTranscript } = require('./observe-session-history.cjs')

const fixtureReply = 'The retained build transcript is ready for follow-up.'
const historySearch = page => page.getByRole('textbox', { name: /^(Search sessions|搜索会话)$/i }).first()
const historyRow = (page, text = fixtureReply) =>
  page.locator('.ai-vault-session-row:visible').filter({ hasText: text })
const dockToggle = page => page.locator('[data-workspace-sidebar-toggle=right]:visible').first()

function seed({ home, repo, title }) {
  seedTranscript({
    home, repo, prompt: title, reply: fixtureReply, clock: '03',
    id: '019f1000-1111-7222-8333-444444444444'
  })
}

async function resumeFixture({ page, button, waits }) {
  const search = historySearch(page)
  const agents = button(/^(智能体|Agents)(?:\s|$)/i)
  if (!(await search.isVisible())) {
    if (!(await agents.isVisible())) await dockToggle(page).click(waits)
    await agents.click(waits)
  }
  await search.waitFor(waits)
  const row = historyRow(page)
  await row.getByTestId('ai-vault-session-more-actions').click(waits)
  await page.getByRole('menuitem', { name: /^(Resume in New Chat|在新聊天中恢复)$/i }).click(waits)
  const trust = button(/^(信任仓库|Trust repository)$/i)
  await trust.waitFor({ timeout: 3500 }).then(() => trust.click(waits), error => {
    if (error.name !== 'TimeoutError') throw error
  })
  await page.locator('[data-native-chat-root=true]:visible').getByText(fixtureReply, { exact: true }).waitFor(waits)
  if (await search.isVisible()) await dockToggle(page).click(waits)
}

async function observeEmpty({ page, step, appButton, caption, waits }) {
  const sessions = appButton('Sessions', '会话')
  await step('i15-empty', 'Distinguish an empty local directory and retain access to past conversations', async () => {
    await sessions.click(waits)
    const directory = page.locator('[data-session-index]')
    await directory.getByText(caption('No open chats', '没有打开的聊天'), { exact: true })
      .waitFor(waits)
    await appButton('Search history', '搜索历史会话').waitFor(waits)
    assert.equal(await directory.getByRole('option').count(), 0)
  })
  if (await sessions.getAttribute('aria-pressed') === 'true') await sessions.click(waits)
}

async function observe({
  page, step, episode, write, waits, caption, appButton, activeTab, exitPreview, preview, composer,
  readObjects, changeSize, firstChat, secondChat, extraChat, extraTab, ownerA, ownerB, a, b
}) {
  const directory = page.locator('[data-session-index]')
  const search = directory.locator('[cmdk-input]')
  const rows = directory.getByRole('option')
  const sessionRow = title => rows.filter({ has: page.getByText(title, { exact: true }) })
  const sessions = appButton('Sessions', '会话')
  const filters = appButton('Session filters', '会话筛选')
  const history = appButton('Search history', '搜索历史会话')
  const chosenWorkspace = (await readObjects()).activeId
  const query = secondChat.split(' · ')[0]
  const record = { workspaceFixture: { separateProjects: ownerA !== ownerB, paneCount: 2 } }
  const chooseOption = async (en, zh) => {
    await filters.click(waits)
    const menu = page.getByRole('menu')
    await menu.getByRole('menuitemradio', { name: caption(en, zh), exact: true }).click(waits)
    await menu.waitFor({ state: 'hidden', ...waits })
  }
  const knownTabs = () => page.evaluate(([a, b]) => {
    const state = window.__store.getState()
    return [a, b].map(owner => state.unifiedTabsByWorktree[owner]
      .filter(tab => tab.contentType === 'agent-session').map(tab => [tab.id, tab.entityId]))
  }, [ownerA, ownerB])
  const before = await knownTabs()
  const assertWorkspace = async () => {
    await preview.waitFor(waits)
    assert.equal((await readObjects()).activeId, chosenWorkspace)
    assert.equal(await activeTab(), firstChat)
    await page.waitForFunction(title => {
      const pane = document.activeElement?.closest('[data-workspace-preview-session]')
      return pane?.innerText.includes(title) &&
        document.activeElement?.closest('[data-native-chat-composer-scope]') !== null
    }, secondChat, waits)
    assert.equal(await composer(secondChat).innerText(), 'Build draft B')
    assert.equal(await composer(firstChat).innerText(), 'Checklist draft A')
    assert.deepEqual(await knownTabs(), before)
    assert.deepEqual((await readObjects()).objects[0].sessions.map(ref => ref.tabId), [a.id, b.id])
  }
  await step('i15-directory', 'Open the desktop Sessions sidebar and read the actual chat origins and destinations', async () => {
    await exitPreview()
    await sessions.click(waits)
    await search.waitFor(waits)
    assert.equal(await sessions.getAttribute('aria-pressed'), 'true')
    await sessionRow(extraChat).waitFor(waits)
    assert.equal(await rows.count(), 3)
    const aRow = await sessionRow(firstChat).innerText()
    const bRow = await sessionRow(secondChat).innerText()
    assert.match(aRow, /UI-spec-sample/)
    assert.match(bRow, /UI-spec-folder/)
    assert.match(bRow, /Codex/)
    assert.ok(bRow.includes(caption('Open in', '中打开')))
    assert.ok(bRow.includes(firstChat))
    record.directory = { rows: 3, localProjects: 2, workspaceDestinationVisible: true }
  })
  await step('i15-native-target', 'Choose a live conversation outside a Workspace and reach its original worktree composer', async () => {
    await search.fill(extraChat.split(' · ')[0], waits)
    await sessionRow(extraChat).waitFor(waits)
    await sessionRow(extraChat).click(waits)
    await page.waitForFunction(tabId => {
      const state = window.__store.getState()
      const owner = state.activeWorktreeId
      const overlay = document.activeElement?.closest('[data-structured-agent-session-overlay-tab-id]')
      return state.groupsByWorktree[owner]?.some(group => group.activeTabId === tabId) &&
        overlay?.getAttribute('data-structured-agent-session-overlay-tab-id') === tabId &&
        Boolean(document.activeElement?.closest('[data-native-chat-composer-scope]'))
    }, extraTab.id, waits)
    assert.equal(await preview.isVisible(), false)
    assert.equal(await sessions.getAttribute('aria-pressed'), 'true')
    assert.deepEqual(await knownTabs(), before)
    record.worktreeTarget = { originalComposerFocused: true, noAdditionalTab: true }
  })
  await step('i15-keyboard-route', 'Search by title and use the keyboard to return to the same Workspace pane', async () => {
    await search.fill(query, waits)
    await sessionRow(secondChat).waitFor(waits)
    await episode('directory-to-workspace', [
      ['confirm the filtered chat with Enter', () => search.press('Enter', waits)],
      ['check the original Workspace, pane and composer', assertWorkspace]
    ])
    record.workspaceTarget = { sameWorkspace: true, samePanes: true, draftsPreserved: true, composerFocused: true }
  })
  await step('i16-current-worktree', 'Return to Sessions and narrow the query to the active local worktree', async () => {
    await exitPreview()
    await search.waitFor(waits)
    assert.equal(await search.inputValue(), query)
    await search.fill('', waits)
    await chooseOption('Current worktree', '当前工作树')
    await sessionRow(secondChat).waitFor(waits)
    assert.equal(await sessionRow(firstChat).count(), 0)
    assert.equal(await rows.count(), 2)
    record.worktreeScope = { matches: 2, querySurvivedReturn: true }
  })
  await step('i16-project-menu', 'Inspect available location and grouping choices with the keyboard at 640px', async () => {
    await changeSize(640, 520)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await filters.focus()
    await filters.press('Enter', waits)
    const menu = page.getByRole('menu')
    await menu.waitFor(waits)
    for (const name of [
      caption('Current worktree', '当前工作树'), caption('In open workspaces', '已打开的工作空间'),
      caption('Project', '项目')
    ]) await menu.getByRole('menuitemradio', { name, exact: true }).waitFor(waits)
    const checked = menu.getByRole('menuitemradio', { name: caption('Current worktree', '当前工作树') })
    assert.equal(await checked.getAttribute('aria-checked'), 'true')
    const bounds = await menu.boundingBox()
    assert.ok(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 641 && bounds.y + bounds.height <= 521)
  })
  await step('i16-scoped-projects', 'Show only chats in open workspaces, grouped by their two actual projects', async () => {
    await page.keyboard.press('Escape')
    await page.getByRole('menu').waitFor({ state: 'hidden', ...waits })
    await page.waitForFunction(() => document.activeElement?.hasAttribute('data-session-index-scope'), null, waits)
    await chooseOption('In open workspaces', '已打开的工作空间')
    await filters.press('Enter', waits)
    const menu = page.getByRole('menu')
    await menu.waitFor(waits)
    await page.keyboard.press('End')
    await page.waitForFunction(name => document.activeElement?.textContent === name,
      caption('Project', '项目'), waits)
    await page.keyboard.press('Enter')
    await menu.waitFor({ state: 'hidden', ...waits })
    await sessionRow(firstChat).waitFor(waits)
    await sessionRow(secondChat).waitFor(waits)
    assert.equal(await sessionRow(extraChat).count(), 0)
    assert.deepEqual((await directory.locator('[cmdk-group-heading]').allInnerTexts()).sort(),
      ['UI-spec-folder', 'UI-spec-sample'])
    assert.equal(await search.isVisible(), true)
    assert.equal(await history.isVisible(), true)
    const geometry = await directory.locator('[cmdk-list]').evaluate(list => {
      const viewport = list.getBoundingClientRect()
      const rowBounds = [...list.querySelectorAll('[cmdk-item]')].map(row => row.getBoundingClientRect())
      return {
        completeRows: rowBounds.filter(rect =>
          rect.height > 0 && rect.top >= viewport.top && rect.bottom <= viewport.bottom).length,
        listBounds: [viewport.top, viewport.bottom],
        rowBounds: rowBounds.map(rect => [rect.top, rect.bottom]),
        scrollTop: list.scrollTop
      }
    })
    assert.ok(geometry.completeRows >= 2, `640×520 result geometry ${JSON.stringify(geometry)}`)
    assert.ok((await sessionRow(secondChat).locator('div[title]').first().getAttribute('title')).includes(secondChat))
    record.workspaceScope = { matches: 2, projects: 2, geometry, escapeRestoredTriggerFocus: true, reducedMotion: true }
  })
  await step('i16-short-navigation', 'Scroll global navigation independently at the 600×400 desktop minimum', async () => {
    await changeSize(600, 400)
    const nav = page.locator('[data-contextual-tour-target=sidebar-navigation]')
    await nav.hover(waits)
    await page.mouse.wheel(0, 350)
    await page.waitForFunction(() =>
      document.querySelector('[data-contextual-tour-target=sidebar-navigation]')?.scrollTop > 0,
    null, waits)
    assert.equal(await search.isVisible(), true)
    assert.equal(await filters.isVisible(), true)
    const listHeight = await directory.locator('[cmdk-list]').evaluate(list => list.clientHeight)
    assert.ok(listHeight >= 75)
    record.minimumWindow = { navigationScrolled: true, listHeight, filterAndSearchVisible: true }
  })
  await step('i16-no-results', 'Show the filter-and-query empty state with history still reachable', async () => {
    await changeSize(640, 520)
    await search.fill('No visible session matches this', waits)
    await directory.getByRole('status').waitFor(waits)
    assert.equal(await rows.count(), 0)
    assert.equal(await history.isEnabled(), true)
  })
  await step('i17-history-search', 'Send the directory query to the live Vault scanner and find the retained transcript', async () => {
    await changeSize(1100, 680)
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await search.fill(query, waits)
    await history.click(waits)
    const vault = historySearch(page)
    await vault.waitFor(waits)
    await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label')?.match(/Search sessions|搜索会话/i), null, waits)
    assert.equal(await vault.inputValue(), query)
    const jump = historyRow(page, query).getByTestId('ai-vault-session-jump-original-pane')
    const retry = page.getByRole('button', { name: /^(Try again|重试|再试一次)$/i }).first()
    let retries = 0
    for (let attempt = 0; attempt < 10; attempt++) {
      if (await jump.waitFor({ timeout: 1500 }).then(() => true, () => false)) break
      if (await retry.isVisible() && await retry.isEnabled()) {
        await retry.click(waits)
        retries++
      }
    }
    await jump.waitFor(waits).catch(async error => {
      const rows = await page.locator('.ai-vault-session-row:visible').allInnerTexts()
      throw new Error(`${error.message}\nHistory rows: ${rows.join(' / ')}`, { cause: error })
    })
    assert.equal(await jump.isEnabled(), true)
    assert.equal(await search.inputValue(), query)
    assert.equal(await vault.inputValue(), query)
    record.historySearch = { queryTransferred: true, searchFocused: true, retainedTranscript: true, retries }
  })
  await step('i17-original-workspace', 'Open the original pane from history and keep the workspace and both drafts', async () => {
    const jump = historyRow(page, query).getByTestId('ai-vault-session-jump-original-pane')
    await episode('history-to-workspace', [
      ['click the actual Vault original pane action', () => jump.click(waits)],
      ['check the same Workspace, panes and drafts', assertWorkspace]
    ])
    record.historyReturn = { sameWorkspace: true, samePanes: true, noDuplicateChat: true, focusedOriginalComposer: true }
  })
  await step('i17-return-directory', 'Return to the worktree with the prior query, filter and grouping', async () => {
    await exitPreview()
    await search.waitFor(waits)
    assert.equal(await search.inputValue(), query)
    assert.equal(await filters.getAttribute('data-session-index-scope'), 'workspace')
    assert.deepEqual(await directory.locator('[cmdk-group]:not([hidden]) [cmdk-group-heading]').allInnerTexts(),
      ['UI-spec-folder'])
    assert.equal(await rows.count(), 1)
    record.returnDirectory = { query: true, scope: true, grouping: true }
  })
  write('session-index-checks.json', record)
}

module.exports = { seed, resumeFixture, observeEmpty, observe }
