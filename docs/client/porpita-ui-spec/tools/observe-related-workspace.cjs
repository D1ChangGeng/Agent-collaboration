const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { seedTranscript } = require('./observe-session-history.cjs')

const historyTitle = 'Review the workspace handoff'
const historyQuery = 'workspace handoff'

function seed({ home, repo, mode }) {
  if (mode === 'index') {
    seedTranscript({
      home, repo, id: '019f1000-1111-7222-8333-444444444462', clock: '22',
      prompt: historyTitle, reply: 'The handoff belongs to the original project.'
    })
  }
  if (mode === 'explorer') {
    fs.writeFileSync(path.join(repo, 'release-checklist.md'), 'The release draft stays here.\n')
  }
}

async function observe(context) {
  const { page, win, app, button, step, episode, write, repo, folder, baseline, mode } = context
  const waits = { timeout: 20000 }
  const buttonNamed = name => page.getByRole('button', {name}).first()
  const readWorkspace = () => page.evaluate(() => {
    const state = window.__store.getState()
    const worktree = state.activeWorktreeId
    return {
      worktree,
      activeGroup: state.activeGroupIdByWorktree[worktree],
      layout: state.layoutByWorktree[worktree],
      tabs: (state.unifiedTabsByWorktree[worktree] ?? []).map(({ id, contentType, label }) =>
        ({ id, contentType, label }))
    }
  })
  const activateSidebarWorktree = async (worktree) => {
    const id = await page.evaluate(value => CSS.escape(value), worktree)
    await page.locator(`[data-worktree-id=${id}]`).first().click(waits)
    await page.waitForFunction(id => window.__store.getState().activeWorktreeId === id, worktree, waits)
  }
  const addProject = async (projectPath, name, kind = 'git') => {
    await app.evaluate(({ dialog }, location) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [location] })
    }, projectPath)
    await button(/^(Add project|添加项目)$/i).click(waits)
    await button(/Browse folder|浏览文件夹/i).click(waits)
    if (kind === 'folder') {
      await page.getByRole('dialog').getByRole('button', { name: /^(Open as Folder|作为文件夹打开)$/i })
        .click(waits)
    }
    await page.getByText(name, { exact: true }).first().waitFor(waits)
    const handle = await page.waitForFunction(({ name, kind }) => {
      const state = window.__store.getState()
      const project = state.repos.find(row => row.displayName === name)
      return project && (project.kind ?? 'git') === kind && state.worktreesByRepo[project.id]?.[0]?.id
    }, { name, kind }, waits)
    const worktree = await handle.jsonValue()
    await handle.dispose()
    await activateSidebarWorktree(worktree)
    return worktree
  }
  const clearCards = async () => {
    for (const id of ['chat-ui-here-corner-heading', 'codex-shared-settings-notice-heading']) {
      const card = page.locator(`[aria-labelledby="${id}"]`)
      if (await card.isVisible()) await card.getByRole('button', { name: /^(Dismiss|关闭)$/i }).click(waits)
    }
    const setup = button(/^(Dismiss setup scripts|关闭安装脚本)$/i)
    if (await setup.isVisible()) await setup.click(waits)
  }
  const openDock = async (tab) => {
    const target = buttonNamed(tab)
    if (!(await target.isVisible())) {
      await buttonNamed(/^(Toggle right sidebar|切换右侧边栏|显示\/隐藏右侧边栏)$/i).click(waits)
    }
    await target.click(waits)
  }
  const openPalette = async () => {
    const trigger = page.locator('[data-contextual-tour-target=sidebar-navigation] > button').first()
    await page.locator('[cmdk-input]').waitFor({ state: 'hidden', ...waits })
    if (!(await trigger.isVisible())) {
      await page.locator('[data-workspace-sidebar-toggle=left][aria-expanded=false]:visible').first()
        .click(waits)
    }
    await trigger.click(waits)
    await page.locator('[cmdk-input]').waitFor(waits)
  }
  const resize = async (width, height) => {
    await win.evaluate((window, size) => window.setContentSize(...size), [width, height])
    await page.waitForFunction(([width, height]) => innerWidth === width && innerHeight === height,
      [width, height], waits)
  }
  const firstWorktree = await addProject(repo, 'UI-spec-sample')
  await clearCards()
  if (mode === 'index') {
    const field = page.locator('[cmdk-input]')
    const openChats = button(/^(Open chats|已打开的聊天)$/i)
    const historyButton = page.locator('[data-slot=command-dialog-content]').getByRole('button', {
      name: /^(Search session history|搜索会话历史)$/i
    })
    const dockSearch = page.getByRole('textbox', { name: /^(Search sessions|搜索会话)$/i })
    const result = page.locator('.ai-vault-session-row').filter({
      has: page.getByText(historyTitle, { exact: true })
    })
    await step('i6-palette', 'Search for a closed conversation in Open chats', async () => {
      await openPalette()
      await openChats.click(waits)
      await field.fill(historyQuery)
      await page.getByText(/^(No open chats match|没有匹配的已打开聊天)/i).first()
        .waitFor({ timeout: 2500 }).catch(() => {})
      assert.equal(await page.locator('[data-content-type=agent-session]').count(), 0)
      assert.equal(await historyButton.count(), baseline ? 0 : 1)
    })
    if (baseline) return
    await step('i6-hand-off', 'Use the keyboard to carry the query into Vault without opening a chat', async () => {
      const before = await readWorkspace()
      await episode('query-to-history', [
        ['focus Search session history and press Enter', async () => {
          await historyButton.focus()
          await page.keyboard.press('Enter')
          await field.waitFor({state:'hidden',...waits})
        }],
        ['wait for the initial history scan and matching Vault row', () => result.waitFor({ timeout: 45000 })]
      ])
      assert.equal(await dockSearch.inputValue(), historyQuery)
      assert.equal(await dockSearch.evaluate(element => element === document.activeElement), true)
      assert.equal((await readWorkspace()).worktree, before.worktree)
      assert.deepEqual((await readWorkspace()).tabs, before.tabs)
    })
    await step('i6-narrow', 'Transfer a different query from a narrow command palette', async () => {
      await resize(600, 420)
      await page.emulateMedia({ reducedMotion:'reduce' })
      await openPalette()
      await field.fill('task:unmatched')
      await historyButton.click(waits)
      await dockSearch.waitFor(waits)
      assert.equal(await dockSearch.inputValue(), 'task:unmatched')
      assert.equal(await dockSearch.evaluate(element => element === document.activeElement), true)
    })
    await step('i6-empty-query', 'Open session history with an empty jump query and browse it', async () => {
      await resize(1280, 800)
      await openPalette()
      assert.equal(await field.inputValue(), '')
      await historyButton.click(waits)
      await dockSearch.waitFor(waits)
      assert.equal(await dockSearch.inputValue(), '')
      await result.waitFor(waits)
    })
    await step('i6-dock-unavailable', 'Open the jump palette from Skills while the workspace Dock is unavailable', async () => {
      await button(/^(Skills|技能)(\s.*)?$/i).click(waits)
      await page.waitForFunction(() => window.__store.getState().activeView === 'skills', null, waits)
      await openPalette()
      assert.equal(await historyButton.count(), 0)
      await field.press('Escape')
      await field.waitFor({ state: 'hidden', ...waits })
      assert.equal(await page.evaluate(() => window.__store.getState().activeView), 'skills')
    })
    write('index.json', {
      queryTransferred: true, searchFocused: true, originalTabsRetained: true,
      emptyQueryClears: true, actionRequiresVisibleDockHost: true
    })
  } else if (mode === 'split') {
    await observeSplit({ ...context, readWorkspace, firstWorktree, waits, clearCards })
  } else if (mode === 'explorer') {
    await observeExplorer({ ...context, readWorkspace, firstWorktree, waits, openDock, addProject, activateSidebarWorktree, clearCards })
  }
}

async function observeSplit({page, win, step, episode, write, readWorkspace, waits, baseline}) {
  const newTab = page.getByRole('button',{name:/^(New tab|新标签页)$/i}).first()
  const join = page.locator('.tab-group-split-resize-handle:visible').first()
  const semantic = page.getByRole('separator', {name:/^(Resize split panes|调整分屏大小)$/i})
  let original
  await step('i7-split', 'Place two actual terminal tabs in separate content panes', async () => {
    await newTab.click(waits)
    await page.getByRole('menuitem',{name:/New Terminal|新建终端|新终端|Blank Terminal|空白终端/i}).first().click(waits)
    await page.waitForFunction(() => {
      const state = window.__store.getState()
      return (state.unifiedTabsByWorktree[state.activeWorktreeId] ?? []).filter(
        tab => tab.contentType === 'terminal'
      ).length >= 2
    }, null, waits)
    const state = await readWorkspace()
    const terminalTabs = state.tabs.filter(tab => tab.contentType === 'terminal')
    assert.equal(terminalTabs.length, 2)
    const tabId = await page.evaluate(value => CSS.escape(value), terminalTabs[1].id)
    await page.locator(`[data-testid=sortable-tab][data-tab-id=${tabId}]`).click({button:'right',...waits})
    const splitMenu = page.getByRole('menuitem',{name:/^Move Tab to Split$|^将标签页移至拆分$/i}).first()
    await splitMenu.hover(waits)
    await page.getByRole('menuitem',{name:/^(Right|向右|右侧|右)$/i}).first().click(waits)
    await join.waitFor(waits)
    original = await readWorkspace()
    assert.equal(original.layout.type, 'split')
    assert.equal(await semantic.count(), baseline ? 0 : 1)
  })
  if (baseline) return
  const ratio = () => readWorkspace().then(state => state.layout.ratio ?? 0.5)
  const dividerX = () => join.boundingBox().then(rect => rect.x)
  await step('i7-keyboard', 'Adjust the split by keyboard while keeping the active content', async () => {
    await semantic.focus()
    await semantic.press('ArrowRight')
    await semantic.press('ArrowRight')
    assert.ok(Math.abs(await ratio() - 0.6) < 0.0001)
    assert.equal(await semantic.getAttribute('aria-valuenow'), '60')
    assert.equal(await semantic.evaluate(element=>element === document.activeElement), true)
    const state = await readWorkspace()
    assert.equal(state.activeGroup, original.activeGroup)
    assert.deepEqual(state.tabs, original.tabs)
  })
  await step('i7-cancel', 'Preview a pointer resize and cancel back to the committed ratio', async () => {
    const rect = await join.boundingBox()
    const x = rect.x + rect.width / 2
    const y = rect.y + rect.height / 2
    await episode('cancel-split-resize', [
      ['drag the divider to preview a new width', async () => {
        await page.mouse.move(x, y)
        await page.mouse.down()
        await page.mouse.move(x - 130, y, { steps: 8 })
        assert.ok(await dividerX() < rect.x - 65)
        assert.ok(Math.abs(await ratio() - 0.6) < 0.0001)
      }],
      ['press Escape while holding the pointer, then release', async () => {
        await page.keyboard.press('Escape')
        await page.mouse.up()
        assert.ok(Math.abs(await dividerX() - rect.x) < 2)
        assert.ok(Math.abs(await ratio() - 0.6) < 0.0001)
      }]
    ])
  })
  await step('i7-narrow', 'Change a split in a narrow window with reduced motion', async () => {
    await win.evaluate(w=>w.setContentSize(820,520))
    await page.emulateMedia({reducedMotion:'reduce'})
    await semantic.focus()
    await semantic.press('Home')
    assert.equal(await semantic.getAttribute('aria-valuenow'), '15')
    await semantic.press('End')
    assert.equal(await semantic.getAttribute('aria-valuenow'), '85')
    await semantic.press('ArrowLeft')
    assert.equal(await semantic.getAttribute('aria-valuenow'), '80')
    assert.deepEqual((await readWorkspace()).tabs, original.tabs)
  })
  write('split.json',{sameTabs:true, keyboardResize:true, cancelledDrag:true, boundedAriaValue:true})
}

async function observeExplorer({page, win, step, episode, write, folder, readWorkspace, firstWorktree, waits, openDock, addProject, activateSidebarWorktree, clearCards, baseline}) {
  const explorer = /^(Explorer|资源管理器|文件浏览器)(?:\s|$)/i
  const history = /^(Agents|智能体)(?:\s|$)/i
  const input = page.locator('[data-explorer-query-input=files]:visible')
  const release = page.locator('[data-orca-explorer-shell]:visible')
    .getByText('release-checklist.md', {exact:true}).first()
  let secondWorktree
  await step('i8-filter', 'Find a real file by name in Explorer', async () => {
    await openDock(explorer)
    await input.fill('release-checklist', waits)
    await release.waitFor(waits)
    assert.equal((await readWorkspace()).worktree, firstWorktree)
  })
  await step('i8-dock-return', 'Switch to the history tool and back to Explorer', async () => {
    await episode('explorer-tool-return', [
      ['open the Agents history tool', () => openDock(history)],
      ['return to Explorer', () => openDock(explorer)]
    ])
    await input.waitFor(waits)
    assert.equal(await input.inputValue(), baseline ? '' : 'release-checklist')
    await release.waitFor(waits)
  })
  if (baseline) return
  await step('i8-other-worktree', 'Enter a different worktree and find its own file', async () => {
    secondWorktree = await addProject(folder, 'UI-spec-folder', 'folder')
    assert.notEqual(secondWorktree, firstWorktree)
    await clearCards()
    await openDock(explorer)
    await input.waitFor(waits)
    assert.equal(await input.inputValue(), '')
    await input.fill('notes.md', waits)
    await page.getByText('notes.md', {exact:true}).last().waitFor(waits)
  })
  await step('i8-worktree-return', 'Return to each worktree and recover its own search', async () => {
    await activateSidebarWorktree(firstWorktree)
    await input.waitFor(waits)
    assert.equal(await input.inputValue(), 'release-checklist')
    await release.waitFor(waits)
    await activateSidebarWorktree(secondWorktree)
    await input.waitFor(waits)
    assert.equal(await input.inputValue(), 'notes.md')
    await activateSidebarWorktree(firstWorktree)
    await input.waitFor(waits)
    assert.equal(await input.inputValue(), 'release-checklist')
  })
  await step('i8-open-original', 'Open the retained file result from the original worktree', async () => {
    await win.evaluate(w => w.setContentSize(820,540))
    await page.emulateMedia({ reducedMotion:'reduce' })
    await release.dblclick(waits)
    assert.equal((await readWorkspace()).worktree, firstWorktree)
    await page.waitForFunction(({ worktreeId }) => window.__store.getState().openFiles.some(
      file => file.relativePath === 'release-checklist.md' && file.worktreeId === worktreeId
    ), { worktreeId: firstWorktree }, waits)
    await page.getByText('The release draft stays here.', { exact: true }).waitFor(waits)
  })
  write('explorer.json', { queryAfterToolSwitch:true, independentWorktreeQueries:true, originalFileOpened:true })
}

module.exports = { seed, observe }
