const assert = require('node:assert/strict')

const toggles = '[data-workspace-sidebar-toggle]'
const leftSidebar = '[data-worktree-sidebar-layout]'
const rightSidebar = '[data-right-sidebar-layout]'
const viewport = '[data-workbench-viewport]'
const trustChoice = /^(让智能体询问|Let agents ask)$/i

module.exports = async function observe({ page, win, app, click, button, step, write, delay, repo, phase }) {
  const size = (width, height) => win.evaluate((w, dimensions) => w.setContentSize(...dimensions), [width, height])
  const wait = (check, data) => page.waitForFunction(check, data, { timeout: 10000 })
  if (phase === 'trust') {
    await step('i2-trust-narrow', 'Resize the real startup trust dialog to 600×400; hit-test both actions and verify its modal state', async () => {
      await size(600, 400)
      const dialog = page.getByRole('dialog').filter({ has: button(trustChoice) })
      await dialog.waitFor({ timeout: 12000 })
      const data = await dialog.evaluate(el => {
        const actions = [...el.querySelectorAll('button')].map(button => {
          const r = button.getBoundingClientRect()
          const target = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)
          return { label: button.textContent, hit: target?.closest('button') === button }
        })
        const hidden = selector => [...document.querySelectorAll(selector)].map(node => !node.getClientRects().length)
        return {
          security: document.body.hasAttribute('data-notifications-suppressed'),
          size: [innerWidth, innerHeight], actions,
          toast: hidden('[data-sonner-toaster]'),
          notificationStack: hidden('[data-notification-card-stack]'),
          liveToasts: document.querySelectorAll('[data-sonner-toast]').length
        }
      })
      write('trust-measurement.json', data)
      assert.deepEqual(data.size, [600, 400])
      assert.equal(data.security, true)
      assert.equal(data.actions.length, 2)
      assert.ok(data.actions.every(action => action.hit))
      assert.ok(data.toast.length && data.toast.every(Boolean))
      assert.ok(data.notificationStack.every(Boolean))
      await page.keyboard.press('Escape')
      await dialog.waitFor({ state: 'visible' })
    })
    await step('i2-trust-answer', 'Choose Let agents ask with the keyboard and verify the blocking overlay closes', async () => {
      const choice = button(trustChoice)
      await choice.focus()
      await page.keyboard.press('Enter')
      await choice.waitFor({ state: 'hidden' })
      await wait(() => !document.body.hasAttribute('data-notifications-suppressed'))
      await size(1280, 800)
    })
    return
  }

  if (phase === 'core') {
    const settings = async () => {
      await click(/^(设置|Settings)$/i)
      const general = page.locator('section[data-settings-section=general]')
      await general.waitFor({ timeout: 10000 })
      return general
    }
    let general
    const status = label => general.getByText(label, { exact: true }).first()
    const connected = /^(已连接|Connected)$/
    const disconnected = /^(未连接|Disconnected)$/
    await step('i2-core-start', 'Start the bundled local Core in an isolated installed profile', async () => {
      general = await settings()
      await general.getByRole('button', { name: /启动本地服务|Start local service/i }).click()
      await status(connected).waitFor({ timeout: 105000 })
    })
    if (!general || !await status(connected).isVisible()) return
    await step('i2-core-disconnect', 'Disconnect the configured service and observe Settings', async () => {
      await general.getByRole('button', { name: /^(断开|Disconnect)$/i }).click()
      await status(disconnected).waitFor({ timeout: 12000 })
    })
    await step('i2-core-reconnect', 'Reconnect the same local Core and observe the Settings status', async () => {
      const reconnect = general.getByRole('button', { name: /^(重新连接|Reconnect)$/i }).first()
      await reconnect.click()
      const immediate = await status(connected).waitFor({ timeout: 10000 }).then(() => true, () => false)
      if (!immediate) {
        await click(/返回应用|Back to app/i)
        general = await settings()
        await status(connected).waitFor({ timeout: 10000 })
      }
      write('core-recovery-measurement.json', { immediate, connectedAfterReopen: !immediate, transport: 'same Windows host, managed local service', performed: 'start, disconnect, reconnect' })
    })
    const disconnect = general.getByRole('button', { name: /^(断开|Disconnect)$/i })
    if (await disconnect.isVisible()) {
      await disconnect.click()
      await status(disconnected).waitFor({ timeout: 15000 })
    }
    return
  }

  const measurements = []
  async function measure(label, expected) {
    const data = await page.evaluate(({ left, right, center, toggle }) => {
      const width = selector => Math.round(document.querySelector(selector)?.getBoundingClientRect().width ?? 0)
      return {
        viewport: innerWidth, left: width(left), center: width(center), right: width(right),
        focus: document.activeElement?.matches(toggle) ? document.activeElement.dataset.workspaceSidebarToggle : null,
        terminals: [...document.querySelectorAll('.xterm')].filter(node => node.getClientRects().length).length,
        terminalWidths: [...document.querySelectorAll('.xterm')].map(node=>Math.round(node.getBoundingClientRect().width)).filter(Boolean)
      }
    }, { left: leftSidebar, right: rightSidebar, center: viewport, toggle: toggles })
    measurements.push({ label, ...data })
    write('layout-measurements.json', measurements)
    assert.equal(data.viewport, expected.width)
    assert.equal(data.left > 0, expected.left)
    assert.equal(data.right > 0, expected.right)
    assert.ok(data.center >= 320, 'workbench must retain 320 CSS px')
    assert.ok(Math.abs(data.center + data.left + data.right - data.viewport) <= 2)
    if (expected.focus) assert.equal(data.focus, expected.focus)
  }
  async function settledResize(width, height) {
    await size(width, height)
    await wait(w => innerWidth === w, width)
    await delay(300)
  }
  await step('i2-split-wide', 'Split the current terminal via Split Terminal Right and measure both docks', async () => {
    await settledResize(1280, 800)
    await button(/^(新标签页|New tab)$/i).waitFor({ timeout: 12000 })
    await click(/向右拆分终端|Split Terminal Right/i)
    await wait(() => [...document.querySelectorAll('.xterm')].filter(node => node.getClientRects().length).length >= 2)
    await measure('split wide', { width: 1280, left: true, right: true })
  })
  await step('i2-split-820', 'Narrow the native window with two visible terminal panes and both sidebars', async () => {
    await settledResize(820, 580)
    await measure('split 820', { width: 820, left: true, right: true })
  })
  await step('i2-split-600', 'Focus the Explorer, then resize to the native minimum and check focus recovery', async () => {
    const findFiles = page.locator('[data-explorer-query-input=files]')
    await findFiles.fill('notes')
    await settledResize(600, 400)
    await measure('split 600, left preferred', { width: 600, left: true, right: false, focus: 'right' })
    assert.equal(await findFiles.isVisible(), false)
  })
  await step('i2-split-600-right', 'Use Enter on the visible right toggle, switching sides at minimum width', async () => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.locator(toggles+'[aria-expanded="false"][data-workspace-sidebar-toggle="right"]').focus()
    await page.keyboard.press('Enter')
    await delay(250)
    await measure('split 600, right preferred and reduced motion', { width: 600, left: false, right: true, focus: 'right' })
    assert.equal(await page.locator('[data-explorer-query-input=files]').inputValue(), 'notes')
  })
  await step('i2-split-restored', 'Return to wide size, verify saved widths and two terminal panes', async () => {
    await settledResize(1280, 800)
    await measure('split wide restored', { width: 1280, left: true, right: true })
    assert.equal(measurements.at(-1).left, measurements[0].left)
    assert.equal(measurements.at(-1).right, measurements[0].right)
    assert.equal(measurements.at(-1).terminals, measurements[0].terminals)
    await page.emulateMedia({ reducedMotion: 'no-preference' })
  })
  await step('i2-help', 'Open the Porpita Help menu and verify the internal release and support labels', async () => {
    await click(/^(帮助|Help)$/i)
    const menu = page.getByRole('menu')
    await menu.getByText(/^(交付记录|Delivery record)$/i).waitFor()
    await menu.getByText(/^(报告问题|Report an issue)$/i).waitFor()
    assert.equal(await menu.getByText(/^(Discord|X|Check for Updates|检查更新)$/i).count(), 0)
  })
  await page.keyboard.press('Escape')
  await step('i2-split-820-side', 'Move the Dock activity bar to the side and resize to 820px', async () => {
    await page.locator(rightSidebar+' .right-sidebar-activity-strip').first().click({ button: 'right' })
    await page.getByRole('menuitemradio', { name: /^(边|侧边|侧面|侧栏|Side)$/i }).first().click()
    await settledResize(820, 580)
    await measure('split 820, side activity bar', { width: 820, left: true, right: true })
    assert.ok(measurements.at(-1).right >= 260)
  })
  await settledResize(1280, 800)
  await step('i2-project-scope', 'Add a second local Git project through the real folder intake and inspect its Source Control', async () => {
    await app.evaluate(({ dialog }, folder) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [folder] })
    }, repo)
    await click(/^(添加项目|Add project)$/i)
    await click(/浏览文件夹|Browse folder/i)
    await page.getByText('UI-spec-sample', { exact: true }).first().waitFor({ timeout: 12000 })
    const changes = button(/^(源代码管理|源代码控制|Source Control)/i)
    await changes.waitFor({ timeout: 9000 })
    await changes.click()
    await page.getByText('notes.md', { exact: true }).last().waitFor({ timeout: 9000 })
  })
  await step('i2-project-return', 'Switch between the local Git project and the previous folder workspace', async () => {
    const activeCard = page.locator('[data-worktree-id]:has([data-worktree-card-active])').first()
    const gitWorkspace = await activeCard.getAttribute('data-worktree-id')
    assert.ok(gitWorkspace)
    const other = page.locator('[data-worktree-id]').filter({ has: page.getByText('~', { exact: true }) }).first()
    await other.click()
    await wait(previous => {
      const card = document.querySelector('[data-worktree-id]:has([data-worktree-card-active])')
      return card && card.getAttribute('data-worktree-id') !== previous
    }, gitWorkspace)
    const escapedId = await page.evaluate(value => CSS.escape(value), gitWorkspace)
    await page.locator(`[data-worktree-id=${escapedId}]`).first().click()
    await wait(previous => {
      const card = document.querySelector('[data-worktree-id]:has([data-worktree-card-active])')
      return card?.getAttribute('data-worktree-id') === previous
    }, gitWorkspace)
    await page.getByText('notes.md', { exact: true }).last().waitFor({ timeout: 9000 })
  })
  await step('i2-chat-open', 'Open the native Codex Chat from the current desktop build', async () => {
    await click(/^(设置|Settings)$/i)
    await click(/^(聊天界面|Chat UI)$/i)
    const enable = page.locator('section[data-settings-section=chat]').getByRole('button', { name: /^(开启|Enable|Turn on)$/i }).first()
    if (await enable.isVisible()) await enable.click()
    await click(/返回应用|Back to app/i)
    await click(/^(新标签页|New tab)$/i)
    const row = page.getByRole('menuitem').filter({ hasText: /^Codex(?:\s|$)/ }).first()
    const nested = row.getByRole('button', { name: /Codex.*(?:Chat|聊天)|(?:Chat|聊天).*Codex/i }).first()
    const explicit = page.getByRole('menuitem', { name: /Codex.*(?:Chat|聊天)|(?:Chat|聊天).*Codex/i }).first()
    if (await explicit.isVisible()) await explicit.click()
    else if (await nested.isVisible()) await nested.click()
    else await row.click()
    const submenu = page.getByRole('menuitem', { name: /^聊天$|^Chat UI$|Open in Chat|在聊天中打开/i }).first()
    if (await submenu.isVisible()) await submenu.click()
    if (await button(trustChoice).isVisible()) await click(trustChoice)
    await page.locator('[data-native-chat-root=true]').first().waitFor({ timeout: 12000 })
  })
  if (await page.locator('[data-native-chat-root=true]').first().isVisible()) {
    await step('i2-chat-narrow', 'Verify the original Native Chat remains visible at the 600×400 workbench size', async () => {
      await settledResize(600, 400)
      const chat = page.locator('[data-native-chat-root=true]').first()
      const box = await chat.boundingBox()
      const composer = chat.locator('[contenteditable=true],textarea').first()
      const composerBox = await composer.boundingBox()
      write('chat-measurement.json', { width: box?.width, composerWidth: composerBox?.width, size: [600, 400], scope: 'native empty Chat, no model calls' })
      assert.ok(box?.width >= 300)
      assert.ok(composerBox?.width >= 160)
    })
    await step('i2-chat-terminal-split', 'Use the native Chat pane action to create a sibling terminal in the same worktree', async () => {
      await settledResize(1280, 800)
      await page.locator('[data-contextual-tour-target=chat-pane-split-target]').click({ timeout: 10000 })
      await wait(() => {
        const visible = selector => [...document.querySelectorAll(selector)].some(node => node.getClientRects().length)
        return visible('[data-native-chat-root=true]') && visible('.xterm')
      })
    })
  }
}
