const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const sessionIndexReplay = require('./observe-sidebar-session-index.cjs')
const unopenedReplay = require('./observe-session-index-unopened.cjs')

const firstChat = 'Release review · 发版核对'
const secondChat = 'Build triage · 构建排查'
const extraNames = [
  'Incident response · 运行排查与复盘记录',
  'Dependency audit · 依赖审查与版本升级',
  'Deployment verification · 部署验证记录'
]
const groupName = 'Release planning and production readiness · 发布计划与生产准备'
const documentText = 'The original scope contains the release checklist.'

function seed({ repo, folder, home, sidebarSessionIndex, sidebarHistory }) {
  const documents = path.join(repo, 'docs')
  fs.mkdirSync(documents)
  fs.writeFileSync(path.join(documents, 'release-checklist.md'), documentText + '\n')
  fs.writeFileSync(path.join(documents, 'build-notes.md'), '# Build notes\n')
  if (sidebarSessionIndex) {
    sessionIndexReplay.seed({ repo: folder, home, title: secondChat })
  }
  if (sidebarHistory) unopenedReplay.seed({ repo: folder, home })
}

async function observe({ page, win, app, button, step, episode, write, repo, folder, locale,
  continuity, sidebarSessionIndex, sidebarHistory, userData, restartWorkspaceDesktop }) {
  const waits = { timeout: 22000 }
  const zh = locale === 'zh'
  const caption = (en, cn) => zh ? cn : en
  const appButton = (en, cn) => page.getByRole('button', { name: caption(en, cn), exact: true }).first()
  const item = (en, cn) => page.getByRole('menuitem', { name: caption(en, cn), exact: true }).first()
  let preview = page.locator('[data-workspace-preview]')
  const sessionPane = (title) => preview.locator('[data-workspace-preview-session]:visible').filter({ has: page.getByText(title, { exact: true }) })
  const composer = (title) => sessionPane(title).locator('[data-native-chat-composer-scope] [contenteditable=true]').first()
  let legacyComposer = page.locator('[data-native-chat-composer-scope] [contenteditable=true]:visible').first()
  const workTab = (title) => preview.locator('[data-workspace-preview-tab]').filter({ hasText: title }).first()
  const activeTab = () => preview.locator('[data-workspace-preview-tab][aria-current=page]').innerText()
  let panel = preview.locator('[data-workspace-preview-explorer]')
  const changeSize = async (width, height) => {
    for (let attempt = 0; attempt < 3; attempt++) {
      await win.evaluate((window, size) => window.setContentSize(...size), [width, height])
      try {
        await page.waitForFunction(
          ([width, height]) => innerWidth === width && innerHeight === height, [width, height], { timeout: 4500 }
        )
        return
      } catch (error) {
        if (attempt === 2) {
          const measured = await page.evaluate(() => `${innerWidth}×${innerHeight}`)
          throw new Error(`Viewport ${width}×${height} did not settle (visible at ${measured})`, { cause: error })
        }
      }
    }
  }
  async function addProject(projectPath, name) {
    await app.evaluate(({ dialog }, location) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [location] })
    }, projectPath)
    await button(/^(Add project|添加项目)$/i).click(waits)
    await button(/Browse folder|浏览文件夹/i).click(waits)
    await page.getByText(name, { exact: true }).first().waitFor(waits)
    const handle = await page.waitForFunction(projectName => {
      const state = window.__store.getState()
      const row = state.repos.find(repo => repo.displayName === projectName)
      return row && state.worktreesByRepo[row.id]?.[0]?.id
    }, name, waits)
    const id = await handle.jsonValue()
    await handle.dispose()
    const escaped = await page.evaluate(value => CSS.escape(value), id)
    await page.locator(`[data-worktree-id=${escaped}]`).first().click(waits)
    await page.waitForFunction(id => window.__store.getState().activeWorktreeId === id, id, waits)
    const dismiss = button(/^(Dismiss setup scripts|关闭安装脚本)$/i)
    if (await dismiss.isVisible()) await dismiss.click(waits)
    return id
  }
  async function launchChat(title, launch = launchNewChat) {
    const before = await page.evaluate(() => {
      const state = window.__store.getState()
      return (state.unifiedTabsByWorktree[state.activeWorktreeId] ?? [])
        .filter(tab => tab.contentType === 'agent-session').map(tab => tab.id)
    })
    await launch()
    const trust = button(/让智能体询问|Let agents ask|Ask in agent/i)
    if (await trust.isVisible()) await trust.click(waits)
    const handle = await page.waitForFunction(old => {
      const state = window.__store.getState()
      const worktree = state.activeWorktreeId
      return (state.unifiedTabsByWorktree[worktree] ?? [])
        .find(tab => tab.contentType === 'agent-session' && !old.includes(tab.id))
    }, before, waits)
    const tab = await handle.jsonValue()
    await handle.dispose()
    await legacyComposer.waitFor(waits)
    const escaped = await page.evaluate(s => CSS.escape(s), tab.id)
    const root = page.locator(`[data-tab-id=${escaped}]:visible`).first()
    if (!(await root.getByText(title, { exact: true }).isVisible())) {
      await root.dblclick(waits)
      const input = page.locator('[data-tab-rename-input=true]:visible')
      await input.fill(title, waits)
      await input.press('Enter')
    }
    await root.getByText(title, { exact: true }).waitFor(waits)
    return { id: tab.id, worktreeId: tab.worktreeId, sessionId: tab.entityId }
  }
  async function launchNewChat() {
    await button(/^(New tab|新标签页)$/i).first().click(waits)
    const row = page.getByRole('menuitem').filter({ hasText: /^Codex(?:\s|$)/ }).first()
    await row.waitFor(waits)
    const nested = row.getByRole('button', { name: /Codex.*(?:Chat|聊天)|(?:Chat|聊天).*Codex/i }).first()
    const explicit = page.getByRole('menuitem', { name: /Codex.*(?:Chat|聊天)|(?:Chat|聊天).*Codex/i }).first()
    const submenu = page.getByRole('menuitem', { name: /^(聊天|聊天界面|Chat UI|Open in Chat|在聊天中打开)$/i }).first()
    await row.hover(waits)
    await submenu.waitFor({ timeout: 800 }).catch(() => {})
    if (await submenu.isVisible()) await submenu.click(waits)
    else if (await nested.isVisible()) await nested.click(waits)
    else if (await explicit.isVisible()) await explicit.click(waits)
    else await row.click(waits)
  }
  async function enterPreview() {
    const entry = appButton('Workspaces (preview)', '工作空间（预览）')
    const sidebar = page.locator('[data-workspace-sidebar-toggle=left][aria-expanded=false]:visible').first()
    if (!(await entry.isVisible()) && await sidebar.isVisible()) await sidebar.click(waits)
    try {
      await entry.click(waits)
    } catch (error) {
      const view = await page.evaluate(() => window.__store.getState().activeView)
      const overlays = await page.locator('[role=dialog]:visible,[role=alertdialog]:visible').allInnerTexts()
      const detail = overlays.map(text => text.split('\n').slice(0, 6).join(' · ')).join(' | ')
      throw new Error(`Cannot enter Workspace preview from ${view}. Visible dialogs: ${detail}\n${error.message}`, { cause: error })
    }
    await preview.waitFor(waits)
  }
  async function exitPreview() {
    await appButton('Return to worktree', '返回工作树').click(waits)
    await preview.waitFor({ ...waits, state: 'hidden' })
  }
  async function chooseSession(title, add = false) {
    if (add) {
      await appButton('Add session', '添加会话').click(waits)
    } else {
      await appButton('New work object', '新建工作对象').click(waits)
      await item('New workspace', '新建工作空间').click(waits)
    }
    const picker = page.getByRole('dialog', { name: caption('Choose a session', '选择会话') })
    await picker.locator('[cmdk-input]').fill(title.split(' · ')[0], waits)
    await picker.getByText(title, { exact: true }).click(waits)
    await picker.waitFor({ ...waits, state: 'hidden' })
  }
  async function openWork(title) {
    await appButton('Open work', '查找工作对象').click(waits)
    const search = page.getByRole('dialog', { name: caption('Open work', '查找工作对象') })
    await search.locator('[cmdk-input]').fill(title.split(' · ')[0], waits)
    await search.getByText(title, { exact: true }).click(waits)
    await search.waitFor({ ...waits, state: 'hidden' })
  }
  const readObjects = () => page.evaluate(async () =>
    window.api.ui.readPorpitaWorkspaceLayout
      ? await window.api.ui.readPorpitaWorkspaceLayout()
      : JSON.parse(localStorage.getItem('porpita-workspace-ui-spec-preview-v1'))
  )
  const dismissStartupDialog = async (owner) => {
    await page.waitForFunction(owner => window.__store?.getState().unifiedTabsByWorktree[owner]?.some(
      tab => tab.contentType === 'agent-session'
    ), owner, waits)
    const dialog = page.locator('[data-slot=dialog-content]:visible').first()
    await dialog.waitFor({ timeout: 5000 }).catch(() => {})
    if (await dialog.isVisible()) {
      const dismiss = dialog.getByRole('button', { name: /^(Close|关闭|Later|稍后|Skip|跳过|Cancel|取消|Dismiss|忽略)$/i }).first()
      if (await dismiss.isVisible()) await dismiss.click(waits)
      else await page.keyboard.press('Escape')
      await dialog.waitFor({ ...waits, state: 'hidden' })
    }
    if (await page.evaluate(() => window.__store.getState().activeView) !== 'terminal') {
      const escaped = await page.evaluate(id => CSS.escape(id), owner)
      await page.locator(`[data-worktree-id=${escaped}]:visible`).first().click(waits)
    }
  }
  const dismissNotice = async (id) => {
    const notice = page.locator(`[aria-labelledby="${id}"]`)
    if (await notice.isVisible()) {
      await notice.getByRole('button', { name: /^(Dismiss|关闭|忽略)$/i }).click(waits)
    }
  }
  const ownerA = await addProject(repo, 'UI-spec-sample')
  const enableChat = button(/^(Use Chat UI|使用聊天界面|使用聊天 UI|使用 Chat UI|启用聊天界面)$/i)
  await enableChat.waitFor({ timeout: 4500 }).catch(() => {})
  if (await enableChat.isVisible()) await enableChat.click(waits)
  const isChatDefault = () => page.evaluate(() => window.__store.getState().settings?.agentDefaultSurface === 'chat')
  await page.waitForFunction(() => window.__store.getState().settings?.agentDefaultSurface === 'chat', null, { timeout: 1800 }).catch(() => {})
  if (!(await isChatDefault())) {
    await button(/^(Settings|设置)$/i).click(waits)
    await button(/^(Chat UI|聊天界面)$/i).click(waits)
    await page.locator('section[data-settings-section=chat]').getByRole('button', { name: /^(Turn on|开启|启用)$/i }).click(waits)
    await button(/返回应用|Back to app/i).click(waits)
  }
  await page.waitForFunction(() => window.__store.getState().settings?.agentDefaultSurface === 'chat', null, waits)
  for (const id of ['codex-shared-settings-notice-heading', 'chat-ui-switched-note-heading']) {
    await dismissNotice(id)
  }
  if (sidebarSessionIndex) {
    await sessionIndexReplay.observeEmpty({ page, step, appButton, caption, waits })
  }
  const a = await launchChat(firstChat).catch(async error => {
    const snapshot = (await page.locator('body').innerText()).split('\n').filter(Boolean).slice(-25)
    throw new Error(`Native Chat setup did not complete: ${snapshot.join(' · ')}`, { cause: error })
  })
  await legacyComposer.fill('Checklist draft A', waits)
  const ownerB = await addProject(folder, 'UI-spec-folder')
  const b = await launchChat(secondChat,
    sidebarSessionIndex ? () => sessionIndexReplay.resumeFixture({ page, button, waits }) : undefined)
  await legacyComposer.fill('Build draft B', waits)
  const extraTabs = []
  for (const title of sidebarSessionIndex ? extraNames.slice(0, 1) : extraNames) {
    extraTabs.push(await launchChat(title))
  }
  if (sidebarSessionIndex) {
    const escaped = await page.evaluate(id => CSS.escape(id), b.id)
    await page.locator(`[data-tab-id=${escaped}]:visible`).first().click(waits)
    const notice = page.locator('[aria-labelledby=codex-shared-settings-notice-heading]')
    await notice.waitFor({ timeout: 1600 }).catch(() => {})
    await dismissNotice('codex-shared-settings-notice-heading')
  }
  await dismissNotice('chat-ui-switched-note-heading')
  assert.notEqual(ownerA, ownerB)
  await enterPreview()

  await step('i9-two-worktrees', 'Open two real local Native Chats side by side from separate worktrees', async () => {
    await chooseSession(firstChat)
    await chooseSession(secondChat, true)
    await composer(firstChat).waitFor(waits)
    await composer(secondChat).waitFor(waits)
    assert.match(await composer(firstChat).innerText(), /Checklist draft A/)
    assert.match(await composer(secondChat).innerText(), /Build draft B/)
    const { objects } = await readObjects()
    assert.deepEqual(objects[0].sessions.map(ref => [ref.tabId, ref.worktreeId, ref.conversationId]), [
      [a.id, ownerA, a.sessionId], [b.id, ownerB, b.sessionId]
    ])
  })
  if (sidebarSessionIndex) {
    await sessionIndexReplay.observe({
      page, step, episode, write, waits, caption, appButton, activeTab, exitPreview, preview, composer,
      readObjects, changeSize, firstChat, secondChat, extraChat: extraNames[0], extraTab: extraTabs[0],
      ownerA, ownerB, a, b
    })
    if (sidebarHistory) {
      await unopenedReplay.observe({ page, step, episode, write, waits, caption, appButton,
        changeSize, firstChat, secondChat, b, ownerB })
    }
    return
  }
  await step('i9-return-to-pane', 'Switch at 600px without moving either session and restore the split', async () => {
    await episode('workspace-pane-return', [
      ['Focus the left chat and adjust the divider', async () => {
        await composer(firstChat).click(waits)
        const divider = preview.getByRole('separator')
        await divider.focus()
        await divider.press('ArrowRight')
        assert.equal(await divider.getAttribute('aria-valuenow'), '55')
      }],
      ['Narrow to a single visible pane and choose the other chat', async () => {
        await changeSize(600, 460)
        await page.emulateMedia({ reducedMotion: 'reduce' })
        await appButton('Switch pane', '切换窗格').click(waits)
        await page.getByRole('menuitemradio', { name: /Build triage/ }).click(waits)
        assert.equal(await preview.locator('[data-workspace-preview-session]:visible').count(), 1)
        assert.match(await composer(secondChat).innerText(), /Build draft B/)
      }],
      ['Restore the wide split', async () => {
        await changeSize(1280, 800)
        await composer(firstChat).waitFor(waits)
        assert.equal(await preview.getByRole('separator').getAttribute('aria-valuenow'), '55')
      }]
    ])
  })
  await step('i9-pane-budget', 'Keep two panes readable near the split threshold', async () => {
    const divider = preview.getByRole('separator')
    await changeSize(692, 520)
    await divider.waitFor(waits)
    const measure = async () => preview.locator('[data-workspace-preview-session]:visible').evaluateAll(nodes =>
      nodes.map(node => Math.round(node.getBoundingClientRect().width))
    )
    assert.ok((await measure()).every(width => width >= 320))
    const previous = (await readObjects()).objects.find(object => object.kind === 'workspace').ratio
    assert.equal(previous, 0.55)
    write('pane-budget.json', { paneWidths: await measure(), savedRatio: previous })
    await changeSize(1280, 800)
    await page.waitForFunction(() => document.querySelector('[data-workspace-preview] [role=separator]')?.getAttribute('aria-valuenow') === '55', null, waits)
  })
  await step('i9-reopen', 'Close only the Workspace tab and reopen the same layout and drafts', async () => {
    const originalId = await workTab(firstChat).getAttribute('data-workspace-preview-tab')
    await appButton(`Close ${firstChat}`, `关闭 ${firstChat}`).click(waits)
    await workTab(firstChat).waitFor({ ...waits, state: 'hidden' })
    await openWork(firstChat)
    assert.equal(await workTab(firstChat).getAttribute('data-workspace-preview-tab'), originalId)
    assert.equal(await preview.getByRole('separator').getAttribute('aria-valuenow'), '55')
    assert.match(await composer(firstChat).innerText(), /Checklist draft A/)
    assert.match(await composer(secondChat).innerText(), /Build draft B/)
  })

  await step('i10-groups', 'Create a long-named group and move the active Workspace from the context menu', async () => {
    for (const title of extraNames) await chooseSession(title)
    await preview.locator('[data-workspace-preview-group]').click(waits)
    await item('New tab group…', '新建标签组…').click(waits)
    const dialog = page.getByRole('dialog', { name: caption('New tab group…', '新建标签组…') })
    await dialog.getByRole('textbox').fill(groupName, waits)
    await dialog.getByRole('button', { name: caption('Create group', '创建分组'), exact: true }).click(waits)
    await dialog.waitFor({ ...waits, state: 'hidden' })
    await openWork(firstChat)
    await workTab(firstChat).click({ button: 'right', ...waits })
    const move = item('Move to group', '移至分组')
    await move.hover(waits)
    await page.getByRole('menuitem', { name: groupName, exact: true }).click(waits)
    await workTab(firstChat).waitFor({ ...waits, state: 'hidden' })
    assert.equal(await activeTab(), extraNames.at(-1))
    await preview.locator('[data-workspace-preview-group]').focus()
    await page.keyboard.press('ArrowDown')
    const group = page.getByRole('menuitemradio', { name: groupName, exact: true })
    await group.waitFor(waits)
    await page.keyboard.press('End')
    await group.focus()
    await page.keyboard.press('Enter')
    await workTab(firstChat).waitFor(waits)
    assert.equal(await activeTab(), firstChat)
  })
  await step('i10-narrow-search', 'Find a hidden tab across all groups at 600px with window buttons clear', async () => {
    await changeSize(600, 460)
    await episode('find-hidden-work', [
      ['Find a workspace in a different group', async () => {
        await openWork(extraNames[0])
        assert.equal(await activeTab(), extraNames[0])
      }],
      ['Find the previous workspace again', () => openWork(firstChat)]
    ])
    const bounds = await preview.locator('[data-workspace-preview-group]').evaluate((node) => {
      const rect = node.getBoundingClientRect()
      const strip = node.parentElement.getBoundingClientRect()
      const controls = document.querySelector('.window-controls').getBoundingClientRect()
      const open = node.parentElement.querySelector('button[aria-label*="Open work"], button[aria-label*="查找工作对象"]')
      return { width: rect.width, stripWidth: strip.width, lookupRight: open.getBoundingClientRect().right, controlsLeft: controls.left }
    })
    assert.ok(bounds.width <= 132 && bounds.width <= bounds.stripWidth * 0.31 + 1)
    assert.ok(bounds.lookupRight <= bounds.controlsLeft)
    write('group-geometry.json', bounds)
  })
  await step('i10-layout-restore', 'Reload the isolated desktop renderer and restore the selected group and Workspace', async () => {
    await changeSize(1280, 800)
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 })
    await dismissStartupDialog(ownerA)
    await enterPreview()
    assert.equal(await activeTab(), firstChat)
    await composer(firstChat).waitFor(waits)
    await composer(secondChat).waitFor(waits)
    assert.equal(await preview.getByRole('separator').getAttribute('aria-valuenow'), '55')
  })
  await step('i11-fixed-scope', 'Open a standalone Explorer for the original worktree and find a real file', async () => {
    await exitPreview()
    const escaped = await page.evaluate(id => CSS.escape(id), ownerA)
    await page.locator(`[data-worktree-id=${escaped}]`).first().click(waits)
    await page.waitForFunction(id => window.__store.getState().activeWorktreeId === id, ownerA, waits)
    await enterPreview()
    await appButton('New work object', '新建工作对象').click(waits)
    await item('Open Explorer', '打开资源管理器').click(waits)
    const folders = page.getByRole('dialog', {
      name: caption('Choose a folder for Explorer', '选择资源管理器的目录'), exact: true
    })
    await folders.getByRole('option').filter({
      has: page.getByText('UI-spec-sample', { exact: true })
    }).click(waits)
    assert.equal(await panel.getAttribute('data-presentation'), 'standalone')
    const docs = panel.getByRole('option', { name: 'docs', exact: true })
    await docs.dblclick(waits)
    await panel.locator('[data-explorer-query-input=files]').fill('release', waits)
    await panel.getByRole('option', { name: 'release-checklist.md' }).click(waits)
    assert.equal(await panel.getByRole('option', { name: 'release-checklist.md' }).getAttribute('aria-selected'), 'true')
  })
  await step('i11-move-panel', 'Move the same Explorer into a Workspace and back while selecting the other worktree chat', async () => {
    const id = await panel.getAttribute('data-workspace-preview-explorer')
    const query = panel.locator('[data-explorer-query-input=files]')
    await episode('explorer-placement', [
      ['Move Explorer from its own tab into the Workspace', async () => {
        await appButton('Explorer placement', '资源管理器位置').click(waits)
        await item(`Move to ${firstChat}`, `移至 ${firstChat}`).click(waits)
        await panel.waitFor(waits)
        assert.equal(await panel.getAttribute('data-presentation'), 'embedded')
        assert.equal(await panel.getAttribute('data-workspace-preview-explorer'), id)
        const scope = panel.locator('[data-workspace-preview-scope]')
        assert.equal(await scope.innerText(), 'docs')
        assert.match(await scope.getAttribute('title'), /UI-spec-sample[/\\]docs$/i)
        await page.waitForFunction(() => document.activeElement?.matches(
          '[data-workspace-preview-explorer] [data-explorer-query-input=files]'
        ), null, waits)
      }],
      ['Focus the second project with Explorer still embedded', async () => {
        await composer(secondChat).click(waits)
        assert.equal(await query.inputValue(), 'release')
        assert.equal(await panel.getByRole('option', { name: 'release-checklist.md' }).getAttribute('aria-selected'), 'true')
      }]
    ])
  })
  await step('i11-detach', 'Return the same Explorer instance to its top-level tab', async () => {
    const id = await panel.getAttribute('data-workspace-preview-explorer')
    await appButton('Explorer placement', '资源管理器位置').click(waits)
    await item('Open as a tab', '作为标签打开').click(waits)
    assert.equal(await panel.getAttribute('data-presentation'), 'standalone')
    assert.equal(await panel.getAttribute('data-workspace-preview-explorer'), id)
    assert.equal(await panel.locator('[data-explorer-query-input=files]').inputValue(), 'release')
  })
  await step('i11-original-file', 'Open the file through its original worktree editor', async () => {
    await changeSize(820, 540)
    await panel.getByRole('option', { name: 'release-checklist.md' }).dblclick(waits)
    await preview.waitFor({ ...waits, state: 'hidden' })
    await page.getByText(documentText, { exact: true }).waitFor(waits)
    const owner = await page.evaluate(() => {
      const state = window.__store.getState()
      return state.openFiles.find(file => file.relativePath.replaceAll('\\', '/').endsWith('docs/release-checklist.md'))?.worktreeId
    })
    assert.equal(owner, ownerA)
  })

  if (!continuity) return

  const layoutFile = path.join(userData, 'porpita-workspaces.json')
  let savedLayout
  const toLegacyProfile = layout => ({
    ...layout,
    version: 1,
    objects: layout.objects.map(object => {
      if (object.kind === 'explorer') {
        const { executionHostId, pairingRevision, ...localExplorer } = object
        assert.deepEqual([executionHostId, pairingRevision], ['local', null])
        return localExplorer
      }
      const { focusedSession, sessions, ...rest } = object
      const focusedConversation = JSON.parse(focusedSession ?? 'null')?.[3]
      return {
        ...rest,
        sessions: sessions.map(({ worktreeId, tabId, conversationId }) =>
          ({ worktreeId, tabId, conversationId })),
        focusedTab: sessions.find(session => session.conversationId === focusedConversation)?.tabId ?? null
      }
    })
  })
  async function awaitLayout(predicate) {
    for (let tries = 0; tries < 45; tries++) {
      const record = await readObjects()
      if (record && predicate(record)) return record
      await new Promise(resolve => setTimeout(resolve, 65))
    }
    throw new Error('Desktop profile did not acknowledge the expected layout')
  }
  await step('i12-profile-save', 'Persist a Workspace with its two sessions and an embedded Explorer', async () => {
    await changeSize(1280, 800)
    await enterPreview()
    await appButton('Explorer placement', '资源管理器位置').click(waits)
    await item(`Move to ${firstChat}`, `移至 ${firstChat}`).click(waits)
    await panel.waitFor(waits)
    savedLayout = await awaitLayout(layout => {
      const workspace = layout.objects.find(object => object.id === layout.activeId)
      return workspace?.title === firstChat && workspace.ratio === 0.55 &&
        layout.objects.some(object => object.attachedTo === workspace.id && object.query === 'release')
    })
    assert.deepEqual(JSON.parse(fs.readFileSync(layoutFile, 'utf8')), savedLayout)
  })
  await step('i12-legacy-migration', 'Adopt the previous preview record the first time a desktop profile opens', async () => {
    assert.ok(savedLayout)
    const legacy = toLegacyProfile(savedLayout)
    await page.evaluate(layout => localStorage.setItem('porpita-workspace-ui-spec-preview-v1', JSON.stringify(layout)), legacy)
    fs.renameSync(layoutFile, layoutFile + '.trial-before-migration')
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 })
    await dismissStartupDialog(ownerA)
    await enterPreview()
    assert.equal(await activeTab(), firstChat)
    const migrated = await awaitLayout(layout => layout.activeId === savedLayout.activeId)
    assert.deepEqual(migrated, savedLayout)
    assert.ok(fs.existsSync(layoutFile))
  })
  await step('i22-v1-profile', 'Read a v1 local layout from the profile and write qualified references on the next split edit', async () => {
    assert.ok(savedLayout)
    const legacy = toLegacyProfile(savedLayout)
    fs.writeFileSync(layoutFile, JSON.stringify(legacy))
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 })
    await dismissStartupDialog(ownerA)
    await enterPreview()
    await composer(firstChat).waitFor(waits)
    const reopened = await awaitLayout(layout => layout.activeId === savedLayout.activeId)
    assert.deepEqual(reopened, savedLayout)
    assert.equal(JSON.parse(fs.readFileSync(layoutFile, 'utf8')).version, 1)
    const split = preview.getByRole('separator')
    await split.press('ArrowRight', waits)
    await page.waitForFunction(async () => {
      const layout = await window.api.ui.readPorpitaWorkspaceLayout()
      return layout?.objects.find(object => object.id === layout.activeId)?.ratio > 0.55
    }, null, waits)
    const updated = JSON.parse(fs.readFileSync(layoutFile, 'utf8'))
    assert.equal(updated.version, 3)
    assert.deepEqual(
      updated.objects.find(object => object.id === updated.activeId).sessions.map(
        ({ executionHostId, pairingRevision }) => [executionHostId, pairingRevision]
      ),
      [['local', null], ['local', null]]
    )
    await split.press('ArrowLeft', waits)
    await awaitLayout(layout => layout.objects.find(object => object.id === layout.activeId)?.ratio === 0.55)
  })
  await step('i12-cold-restore', 'Relaunch Electron and return to the same Workspaces and embedded file query', async () => {
    assert.ok(savedLayout)
    await page.evaluate(() => localStorage.removeItem('porpita-workspace-ui-spec-preview-v1'))
    ;({ page, app, win } = await restartWorkspaceDesktop())
    preview = page.locator('[data-workspace-preview]')
    panel = preview.locator('[data-workspace-preview-explorer]')
    legacyComposer = page.locator('[data-native-chat-composer-scope] [contenteditable=true]:visible').first()
    await dismissStartupDialog(ownerA)
    await enterPreview()
    assert.equal(await activeTab(), firstChat)
    assert.match(await composer(firstChat).innerText(), /Checklist draft A/)
    assert.match(await composer(secondChat).innerText(), /Build draft B/)
    assert.equal(await preview.getByRole('separator').getAttribute('aria-valuenow'), '55')
    await panel.getByRole('option', { name: 'release-checklist.md' }).waitFor(waits)
    assert.equal(await panel.getAttribute('data-presentation'), 'embedded')
    assert.equal(await panel.locator('[data-explorer-query-input=files]').inputValue(), 'release')
    assert.equal(await panel.getByRole('option',{name:'release-checklist.md'}).getAttribute('aria-selected'), 'true')
    assert.deepEqual(await readObjects(), savedLayout)
  })
  await step('i12-read-failure', 'Keep the saved data intact when the layout cannot be decoded', async () => {
    const unreadable = '{"version":99}'
    fs.writeFileSync(layoutFile, unreadable)
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 })
    await dismissStartupDialog(ownerA)
    await enterPreview()
    await preview.getByText(caption('Could not open saved workspaces.', '无法打开已保存的工作空间。'), { exact: true }).waitFor(waits)
    assert.equal(fs.readFileSync(layoutFile, 'utf8'), unreadable)
  })
  await step('i12-retry-layout', 'Retry loading the saved layout from the same entry', async () => {
    assert.ok(savedLayout)
    fs.writeFileSync(layoutFile, JSON.stringify(savedLayout))
    await preview.getByRole('button', { name: caption('Retry', '重试'), exact: true }).click(waits)
    await composer(firstChat).waitFor(waits)
    assert.equal(await activeTab(), firstChat)
    assert.equal(await panel.locator('[data-explorer-query-input=files]').inputValue(), 'release')
  })

  const search = () => page.locator('[data-contextual-tour-target=sidebar-navigation] > button').first()
  const palette = () => page.locator('[data-slot=command-dialog-content]:visible')
  async function searchOpenChat(title) {
    await search().click(waits)
    const field = palette().locator('[cmdk-input]')
    await field.waitFor(waits)
    const filter = palette().getByRole('button', { name: caption('Open chats', '已打开的聊天'), exact: true })
    if (await filter.getAttribute('aria-pressed') !== 'true') await filter.click(waits)
    await field.fill(title.split(' · ')[0], waits)
    const result = palette().locator('[data-content-type=agent-session]').filter({
      has: page.locator('[data-slot=palette-open-tab-title]').filter({ hasText: title.split(' · ')[0] })
    })
    await result.waitFor(waits)
    return { field, result }
  }
  await step('i13-location', 'Show the owning Workspace below a matching open Chat', async () => {
    await exitPreview()
    const { result } = await searchOpenChat(secondChat)
    assert.match(await result.locator('[data-workspace-palette-destination]').innerText(), /Release review/)
  })
  await step('i13-focus-chat', 'Enter the result and focus the original Chat inside its Workspace', async () => {
    const legacyOwner = await page.evaluate(() => window.__store.getState().activeWorktreeId)
    await episode('session-to-workspace', [
      ['Press Enter in the open-chat palette', () => page.keyboard.press('Enter')],
      ['Receive focus in the existing Workspace Chat', async () => {
        await preview.waitFor(waits)
        await composer(secondChat).waitFor(waits)
        await page.waitForFunction(() => document.activeElement?.closest('[data-workspace-preview-session][data-focused=true]') != null, null, waits).catch(async error => {
          const location = await page.evaluate(() => ({
            active: document.activeElement?.tagName,
            role: document.activeElement?.getAttribute('aria-label'),
            focusedPane: document.querySelector('[data-workspace-preview-session][data-focused=true]')?.innerText.split('\n')[0],
            overlay: document.querySelector('[role=dialog]')?.innerText.split('\n')[0]
          }))
          throw new Error(`Composer focus could not settle: ${JSON.stringify(location)}`, { cause: error })
        })
        assert.equal(await composer(secondChat).evaluate(node => node === document.activeElement), true)
      }]
    ])
    assert.equal(await activeTab(), firstChat)
    assert.match(await composer(secondChat).innerText(), /Build draft B/)
    assert.equal(await page.evaluate(() => window.__store.getState().activeWorktreeId), legacyOwner)
    const escaped = await page.evaluate(id => CSS.escape(id), b.id)
    assert.equal(await page.locator(`[data-structured-agent-session-overlay-tab-id="${escaped}"]`).count(), 0)
  })
  await step('i13-single-view', 'Return to the worktree surface and let the original view take over', async () => {
    const escaped = await page.evaluate(id => CSS.escape(id), b.id)
    const original = page.locator(`[data-structured-agent-session-overlay-tab-id="${escaped}"]`)
    await exitPreview()
    const worktree = await page.evaluate(id => CSS.escape(id), ownerB)
    await page.locator(`[data-worktree-id=${worktree}]:visible`).first().click(waits)
    await original.waitFor({ ...waits, state: 'attached' })
    assert.equal(await original.count(), 1)
    await enterPreview()
  })
  await step('i13-normal-fallback', 'Open a Chat whose Workspace has been closed using the ordinary Worktree route', async () => {
    if (!(await preview.isVisible())) await enterPreview()
    const title = extraNames[0]
    await openWork(title)
    await appButton(`Close ${title}`, `关闭 ${title}`).click(waits)
    await exitPreview()
    const worktree = await page.evaluate(id => CSS.escape(id), ownerA)
    await page.locator(`[data-worktree-id=${worktree}]:visible`).first().click(waits)
    const { result } = await searchOpenChat(title).catch(error => {
      throw new Error(`Search after closing the Workspace: ${error.message}`, { cause: error })
    })
    assert.equal(await result.locator('[data-workspace-palette-destination]').count(), 0)
    await result.click(waits)
    await page.waitForFunction(() => !document.querySelector('[data-slot=command-dialog-content][data-state=open]'), null, waits)
    assert.equal(await preview.count(), 0)
    assert.equal(await page.evaluate(() => window.__store.getState().activeWorktreeId), ownerB)
    await legacyComposer.waitFor(waits).catch(error => {
      throw new Error(`Return to original composer: ${error.message}`, { cause: error })
    })
    await enterPreview()
    await openWork(firstChat)
  })

  const groupButton = () => preview.locator('[data-workspace-preview-group]')
  async function dragWorkspace() {
    const source = await workTab(firstChat).boundingBox()
    const target = await groupButton().boundingBox()
    await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2)
    await page.mouse.down()
    await page.mouse.move(target.x + target.width / 2, target.y + target.height / 2, { steps: 14 })
    await page.locator('[data-workspace-preview-group][data-drop-target=true]').waitFor(waits)
    await page.mouse.up()
    await page.locator('[data-workspace-preview-move-heading]').waitFor(waits)
  }
  await step('i14-cancel-move', 'Cancel a drop after the destination menu opens and return focus to the source tab', async () => {
    if (!(await preview.isVisible())) await enterPreview()
    if (!(await workTab(firstChat).isVisible())) await openWork(firstChat)
    await changeSize(600, 460)
    const before = await readObjects()
    await episode('group-move-cancel', [
      ['Drag the tab to the group selector', dragWorkspace],
      ['Press Escape before choosing a destination', async () => {
        await page.keyboard.press('Escape')
        await page.locator('[data-workspace-preview-move-heading]').waitFor({ ...waits, state: 'hidden' })
      }]
    ])
    assert.deepEqual(await readObjects(), before)
    await workTab(firstChat).waitFor(waits)
    assert.equal(await workTab(firstChat).evaluate(node => node === document.activeElement), true)
  })
  await step('i14-move-to-group', 'Confirm another group and find the same workspace, drafts, and tool', async () => {
    const id = await workTab(firstChat).getAttribute('data-workspace-preview-tab')
    await dragWorkspace()
    const target = page.getByRole('menuitemradio', { name: caption('General', '通用'), exact: true })
    await target.click(waits)
    await workTab(firstChat).waitFor({ ...waits, state: 'hidden' })
    const after = await awaitLayout(layout => layout.objects.some(object => object.id === id && object.groupId === 'general'))
    assert.equal(after.objects.find(object => object.id === id).sessions.length, 2)
    await openWork(firstChat)
    assert.equal(await workTab(firstChat).getAttribute('data-workspace-preview-tab'), id)
    await changeSize(1280, 800)
    assert.match(await composer(secondChat).innerText(), /Build draft B/)
    await panel.getByRole('option', { name: 'release-checklist.md' }).waitFor(waits)
  })
}

module.exports = { seed, observe }
