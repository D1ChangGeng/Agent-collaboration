const assert = require('node:assert/strict')

module.exports = async function observeSessionSearch({
  page, win, app, click, button, step, episode, write, repo, folder, baseline, locale
}) {
  const palette = page.getByRole('dialog').filter({ has: page.locator('[cmdk-input]') })
  const input = palette.locator('[cmdk-input]')
  const scope = palette.getByRole('button', {name: /^(Open chats|已打开的聊天)$/})
  const composer = page.locator('[data-native-chat-composer-scope] [contenteditable=true]:visible').first()
  const sameTitle = 'Review · 交付检查'
  const nameQuery = locale === 'zh' ? '交付检查' : 'Review'
  const waits = {timeout: 16000}
  const snapshot = () => page.evaluate(() => {
    const state = window.__store?.getState()
    if (!state) throw new Error('VITE_EXPOSE_STORE=true is required for navigation assertions')
    const groupId = state.activeGroupIdByWorktree[state.activeWorktreeId]
    const activeGroup = state.groupsByWorktree[state.activeWorktreeId]?.find(group => group.id === groupId)
    const tabs = Object.values(state.unifiedTabsByWorktree).flat().filter(tab => tab.contentType === 'agent-session')
    const activeTab = tabs.find(tab => tab.id === activeGroup?.activeTabId)
    return {
      tabId: activeTab?.id ?? null,
      owner: state.activeWorktreeId,
      groupId,
      count: tabs.length,
      composerFocused: document.activeElement?.closest('[data-native-chat-composer-scope]') != null
    }
  })
  const waitForTab = (expected) => page.waitForFunction(({owner, groupId, tabId}) => {
    const state = window.__store?.getState()
    return state?.activeWorktreeId === owner &&
      state.activeGroupIdByWorktree[owner] === groupId &&
      state.groupsByWorktree[owner]?.some(group => group.id === groupId && group.activeTabId === tabId) &&
      document.activeElement?.closest('[data-native-chat-composer-scope]') != null
  }, expected, waits)
  async function openPalette() {
    await page.locator('[data-contextual-tour-target=sidebar-navigation] button').first().click(waits)
    await input.waitFor(waits)
  }
  async function launchChat() {
    const newTab = button(/^(新标签页|New tab)$/i)
    await newTab.click(waits)
    const row = page.getByRole('menuitem').filter({ hasText: /^Codex(?:\s|$)/ }).first()
    await row.waitFor(waits)
    const nested = row.getByRole('button',{name:/Codex.*(?:Chat|聊天)|(?:Chat|聊天).*Codex/i}).first()
    const explicit = page.getByRole('menuitem',{name:/Codex.*(?:Chat|聊天)|(?:Chat|聊天).*Codex/i}).first()
    if (await explicit.isVisible()) await explicit.click()
    else if (await nested.isVisible()) await nested.click()
    else await row.click()
    const submenu = page.getByRole('menuitem',{name:/^聊天$|^Chat UI$|Open in Chat|在聊天中打开/i}).first()
    if (await submenu.isVisible()) await submenu.click()
    const trust = button(/让智能体询问|Let agents ask|Ask in agent/i)
    if (await trust.isVisible()) await trust.click()
    try {
      await page.locator('[data-native-chat-root=true]:visible').first().waitFor(waits)
    } catch (error) {
      const visibleState = (await page.locator('body').innerText()).slice(-4000)
      throw new Error(`Native Chat did not open after selecting Codex.\n${visibleState.split('\n').filter(Boolean).slice(-14).join(' · ')}`, {cause:error})
    }
    const observed = await snapshot()
    assert.ok(observed.tabId && observed.groupId && observed.owner)
    return observed
  }
  async function addProject(path, name) {
    await app.evaluate(({dialog}, fixture) => {
      dialog.showOpenDialog = async () => ({canceled:false,filePaths:[fixture]})
    }, path)
    await click(/^(添加项目|Add project)$/i)
    await click(/浏览文件夹|Browse folder/i)
    await page.getByText(name,{exact:true}).first().waitFor(waits)
    const target = await page.evaluate((projectName) => {
      const state = window.__store?.getState()
      const location = state?.repos.find(repo => repo.displayName === projectName)
      return location ? state.worktreesByRepo?.[location.id]?.[0]?.id : null
    },name)
    if (target) {
      const escape = await page.evaluate(value=>CSS.escape(value),target)
      await page.locator(`[data-worktree-id=${escape}]`).first().click(waits)
    }
  }
  async function enableChatUi() {
    if (await page.evaluate(() => window.__store?.getState().settings?.agentDefaultSurface === 'chat')) return
    await click(/^(设置|Settings)$/i)
    await click(/^(聊天界面|Chat UI)$/i)
    const enable = page.locator('section[data-settings-section=chat]').getByRole('button',{name:/^(Turn on|开启|启用)$/i})
    await enable.click(waits)
    await click(/返回应用|Back to app/i)
    await page.waitForFunction(() => window.__store?.getState().settings?.agentDefaultSurface === 'chat', null, waits)
  }
  async function renameChat(tabId) {
    const escape = await page.evaluate(value => CSS.escape(value), tabId)
    const tab = page.locator(`[data-tab-id=${escape}]:visible`).first()
    await tab.dblclick(waits)
    const name = page.locator('[data-tab-rename-input=true]')
    await name.fill(sameTitle)
    await name.press('Enter')
    await tab.getByText(sameTitle, {exact:true}).waitFor(waits)
  }

  if (baseline) {
    await openPalette()
    await page.keyboard.press('Escape')
  }
  if (!baseline) await step('i3-empty', 'Open sidebar search before any chat is opened', async () => {
    await openPalette()
    await scope.focus()
    await page.keyboard.press('Space')
    await palette.getByText(locale === 'zh' ? '没有已打开的聊天' : 'No open chats', {exact:true}).waitFor(waits)
    assert.equal(await scope.getAttribute('aria-pressed'), 'true')
    assert.equal(await input.evaluate(element => element === document.activeElement), true)
  })
  if (await palette.isVisible()) {
    await page.keyboard.press('Escape')
    await palette.waitFor({state:'hidden'})
  }
  let folderChat, projectChat
  await step('i3-populate', 'Open and name two real Native Chats in different local worktrees', async () => {
    const useChatUi = button(/^(Use Chat UI|使用聊天界面|使用聊天 UI|使用 Chat UI|启用聊天界面)$/i)
    if (await useChatUi.isVisible()) await useChatUi.click()
    await enableChatUi()
    await addProject(folder, 'UI-spec-folder')
    folderChat = await launchChat()
    await renameChat(folderChat.tabId)
    await composer.fill('Draft in first project · 草稿一')
    await addProject(repo, 'UI-spec-sample')
    await page.waitForFunction(owner => window.__store?.getState().activeWorktreeId !== owner, folderChat.owner, waits)
    projectChat = await launchChat()
    assert.notEqual(projectChat.owner, folderChat.owner)
    assert.notEqual(projectChat.tabId, folderChat.tabId)
    await renameChat(projectChat.tabId)
    await composer.fill('Draft in Git project · 草稿二')
    assert.equal((await snapshot()).count, 2)
  })
  assert.ok(folderChat && projectChat)
  const matching = palette.locator('[cmdk-item]').filter({
    has:page.locator('[data-slot=palette-open-tab-title]').filter({hasText:'Review'})
  })
  const gitRow = matching.filter({hasText:'UI-spec-sample'})
  const folderRow = matching.filter({hasText:'UI-spec-folder'})
  await step('i3-same-name', 'Inspect two equal chat names and their distinct visible origin', async () => {
    await openPalette()
    await input.fill(nameQuery)
    if (!baseline) {
      await scope.click()
      await palette.locator('[data-content-type=agent-session]').nth(1).waitFor(waits)
      assert.equal(await scope.getAttribute('aria-pressed'),'true')
      assert.equal(await input.inputValue(), nameQuery)
    }
    await matching.nth(1).waitFor(waits)
    assert.equal(await matching.count(), 2)
    assert.equal(await gitRow.count(), 1)
    assert.equal(await folderRow.count(), 1)
  })
  if (baseline) return

  await step('i3-continue-episode', 'Select by pointer, return by keyboard, and revisit the same original Chat', async () => {
    const observations = []
    await episode('continue-open-chat', [
      ['select the folder result by pointer', async () => {
        await folderRow.click()
        await palette.waitFor({state:'hidden'})
        await waitForTab(folderChat)
        assert.equal((await composer.innerText()).trim(), 'Draft in first project · 草稿一')
        observations.push(await snapshot())
      }],
      ['reopen sidebar search and focus the existing Git Chat by Enter', async () => {
        await openPalette()
        assert.equal(await scope.getAttribute('aria-pressed'),'false')
        await scope.click()
        await input.fill('UI-spec-sample')
        await gitRow.waitFor(waits)
        await input.press('Enter')
        await palette.waitFor({state:'hidden'})
        await waitForTab(projectChat)
        assert.equal((await composer.innerText()).trim(), 'Draft in Git project · 草稿二')
        observations.push(await snapshot())
      }],
      ['repeat the lookup of the active chat', async () => {
        await openPalette()
        await scope.click()
        await input.fill('UI-spec-sample')
        await gitRow.waitFor(waits)
        await gitRow.click()
        await palette.waitFor({state:'hidden'})
        await waitForTab(projectChat)
        assert.equal((await composer.innerText()).trim(), 'Draft in Git project · 草稿二')
        observations.push(await snapshot())
      }]
    ])
    assert.ok(observations.every(({count})=>count===2))
    write('navigation.json', {
      sameTitle,
      steps: observations.map(({owner, tabId, groupId, count, composerFocused}) => ({
        origin: owner === folderChat.owner ? 'first Git project' : 'second Git project',
        originalTab: tabId === (owner === folderChat.owner ? folderChat.tabId : projectChat.tabId),
        originalPane: groupId === (owner === folderChat.owner ? folderChat.groupId : projectChat.groupId),
        count, composerFocused
      }))
    })
  })
  await step('i3-no-match', 'Check a task-style URL stays inside chat search and preserves the current work', async () => {
    await openPalette()
    await scope.click()
    await input.fill('https://github.com/example/project/issues/42')
    await palette.getByText(locale === 'zh' ? '没有匹配的聊天' : 'No open chats match',{exact:true}).waitFor(waits)
    assert.equal(await palette.getByRole('option').count(),0)
    await input.press('Enter')
    assert.equal(await palette.isVisible(),true)
    assert.equal((await snapshot()).tabId,projectChat.tabId)
  })
  await step('i3-exact-title', 'Find both original chats with an exact copied title containing a separator', async () => {
    await input.fill(sameTitle)
    await matching.nth(1).waitFor(waits)
    assert.equal(await matching.count(),2)
    assert.equal(await palette.getByRole('option').count(),2)
  })
  await step('i3-compact', 'Keep the filtered rows readable at 600x400 with reduced motion', async () => {
    await win.evaluate(window => window.setContentSize(600,400))
    await page.emulateMedia({reducedMotion:'reduce'})
    await input.fill(nameQuery)
    await matching.nth(1).waitFor(waits)
    const rects = await matching.evaluateAll(elements => elements.map(element => {
      const bounds = element.getBoundingClientRect()
      return [bounds.x,bounds.right,bounds.y,bounds.bottom]
    }))
    assert.ok(rects.every(([left,right,top,bottom])=>left>=0 && right<=600 && top>=0 && bottom<=400))
  })
  await step('i3-general', 'Restore the same query in general search and use Escape to return to the draft', async () => {
    await scope.click()
    assert.equal(await input.inputValue(),nameQuery)
    assert.equal(await scope.getAttribute('aria-pressed'),'false')
    await input.fill('Terminal')
    await palette.locator('[data-content-type=terminal]').first().waitFor(waits)
    await page.keyboard.press('Escape')
    await palette.waitFor({state:'hidden'})
    assert.equal((await snapshot()).tabId, projectChat.tabId)
    assert.equal(await page.locator('[data-contextual-tour-target=sidebar-navigation] button').first().evaluate(
      element => element === document.activeElement
    ), true)
    assert.equal((await composer.innerText()).trim(), 'Draft in Git project · 草稿二')
  })
}
