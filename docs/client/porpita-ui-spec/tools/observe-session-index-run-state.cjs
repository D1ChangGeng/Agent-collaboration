const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

function configure({ temporary, source, env }) {
  assert.equal(process.platform, 'win32', 'Run this renderer replay with the Windows Codex fixture')
  const fixtures = path.join(temporary, 'codex-fixture')
  fs.mkdirSync(fixtures)
  const script = path.join(source, 'src/main/codex/__fixtures__/codex-app-server-scripted-cli.mjs')
  assert.ok(fs.existsSync(script))
  const command = path.join(fixtures, 'codex.cmd')
  const ack = path.join(fixtures, 'step-ack')
  fs.writeFileSync(command, [
    '@echo off',
    `set "ORCA_CODEX_CONTRACT_ACK_PATH=${ack}"`,
    `"${process.execPath}" "${script}" %*`, ''
  ].join('\r\n'))
  const inheritedSearchPath = env.PATH ?? env.Path ?? ''
  delete env.Path
  env.PATH = fixtures + path.delimiter + inheritedSearchPath
  env.ORCA_CODEX_CONTRACT_ACK_PATH = ack
  return { ack }
}

async function observe({ page, win, app, step, episode, write, repo, button, locale, fixtures }) {
  const title = 'Check release status'
  const prompt = 'Show the fixture response'
  const waits = { timeout: 22000 }
  const directory = page.locator('[data-session-index]')
  const row = directory.getByRole('option').filter({ hasText: title })
  const collaboration = page.locator('[data-session-index-collaboration]')
  const composer = page.locator('[data-native-chat-composer-scope] [contenteditable=true]:visible').first()
  const approvalCard = page.locator('[data-native-chat-approval-card=true]:visible').first()
  const code = (en, zh) => locale === 'zh' ? zh : en
  const states = {}

  await app.evaluate(({ dialog }, fixture) => {
    dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [fixture] })
  }, repo)
  await button(/^(Add project|添加项目)$/i).click(waits)
  await button(/Browse folder|浏览文件夹/i).click(waits)
  await page.getByText('UI-spec-sample', { exact: true }).first().waitFor(waits)
  await page.locator('[data-worktree-card-surface]').first().click(waits)
  const enableChat = button(/^(Use Chat UI|使用聊天界面|使用聊天 UI|使用 Chat UI|启用聊天界面)$/i)
  if (await enableChat.waitFor({ timeout: 4500 }).then(() => true, () => false)) {
    await enableChat.click(waits)
  }
  const isChatDefault = () =>
    page.evaluate(() => window.__store.getState().settings?.agentDefaultSurface === 'chat')
  await page.waitForFunction(() =>
    window.__store.getState().settings?.agentDefaultSurface === 'chat', null, { timeout: 1800 })
    .catch(() => {})
  if (!(await isChatDefault())) {
    await button(/^(Settings|设置)$/i).click(waits)
    await button(/^(Chat UI|聊天界面)$/i).click(waits)
    await page.locator('section[data-settings-section=chat]').getByRole('button', { name: /^(Turn on|开启|启用)$/i }).click(waits)
    await button(/返回应用|Back to app/i).click(waits)
  }
  await page.waitForFunction(() =>
    window.__store.getState().settings?.agentDefaultSurface === 'chat', null, waits)
  await button(/^(New tab|新标签页)$/i).click(waits)
  const provider = page.getByRole('menuitem').filter({ hasText: /^Codex(?:\s|$)/ }).first()
  const nested = provider.getByRole('button', { name: /Codex.*(?:Chat|聊天)|(?:Chat|聊天).*Codex/i }).first()
  const explicit = page.getByRole('menuitem', { name: /Codex.*(?:Chat|聊天)|(?:Chat|聊天).*Codex/i }).first()
  const chat = page.getByRole('menuitem', { name: /^(聊天|聊天界面|Chat UI|Open in Chat|在聊天中打开)$/i }).first()
  await provider.hover(waits)
  if (await chat.waitFor({ timeout: 900 }).then(() => true, () => false)) await chat.click(waits)
  else if (await nested.isVisible()) await nested.click(waits)
  else if (await explicit.isVisible()) await explicit.click(waits)
  else await provider.click(waits)
  const trust = button(/^(信任仓库|Trust repository)$|让智能体询问|Let agents ask|Ask in agent/i)
  if (await trust.waitFor({ timeout: 1800 }).then(() => true, () => false)) await trust.click(waits)
  await composer.waitFor({ timeout: 8000 }).catch(async error => {
    const surface = (await page.locator('body').innerText()).split('\n').filter(Boolean).slice(-45)
    throw new Error(`Could not open the scripted Native Chat: ${surface.join(' · ')}`, { cause: error })
  })
  const tab = page.locator('[data-tab-id]:visible').filter({ hasText: /Codex/i }).first()
  await tab.dblclick(waits)
  const rename = page.locator('[data-tab-rename-input=true]:visible')
  await rename.fill(title, waits)
  await rename.press('Enter')
  for (const id of ['chat-ui-here-corner-heading', 'codex-shared-settings-notice-heading', 'chat-ui-switched-note-heading']) {
    const notice = page.locator(`[aria-labelledby="${id}"]`)
    if (await notice.isVisible()) {
      await notice.getByRole('button', { name: /^(Dismiss|关闭|忽略|不再显示)$/i }).click(waits)
    }
  }
  await button(/^(Sessions|会话)$/i).click(waits)
  await row.waitFor(waits)
  const dockToggle = page.locator('[data-workspace-sidebar-toggle=right][aria-expanded=true]:visible').first()
  if (await dockToggle.isVisible()) await dockToggle.click(waits)
  const setup = button(/^(Dismiss setup scripts|关闭安装脚本)$/i)
  if (await setup.isVisible()) await setup.click(waits)

  await step('i19-running', 'Observe the original Native Chat publish a working state while its scripted provider waits', async () => {
    await composer.fill(prompt, waits)
    await composer.press('Enter')
    await row.getByRole('img', { name: code('Working', '工作中'), exact: true }).waitFor(waits)
    await page.getByText(/Guest codex/).first().waitFor(waits)
    assert.equal(await approvalCard.isVisible(), false)
    states.working = { originalRow: true, providerTurnStarted: true }
  })

  await step('i19-needs-attention', 'Keep the same row and switch its live state to Needs attention for a pending approval', async () => {
    await win.evaluate(w => w.setContentSize(820, 540))
    await page.waitForFunction(() => innerWidth === 820 && innerHeight === 540, null, waits)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await episode('running-to-attention', [
      ['release the scripted provider at the actual tool prompt', () => fs.writeFileSync(fixtures.ack, 'continue\n')],
      ['wait for the native session status and original prompt', async () => {
        await row.getByRole('img', { name: code('Needs attention', '需要关注'), exact: true }).waitFor(waits)
        await approvalCard.getByText('pwd', { exact: true }).waitFor(waits)
      }]
    ])
    assert.equal(await row.getByRole('img', { name: code('Working', '工作中'), exact: true }).count(), 0)
    const notice = page.locator('[aria-labelledby=codex-shared-settings-notice-heading]')
    if (await notice.isVisible()) {
      await notice.getByRole('button', { name: /^(Dismiss|关闭|忽略|不再显示)$/i }).click(waits)
    }
    states.attention = { approvalShownInNativeChat: true, noWorkingIndicator: true, reducedMotion: true }
  })

  await step('i19-collaboration', 'Inspect the original collaboration panel’s actual connection label from the session directory', async () => {
    await collaboration.press('Enter', waits)
    const dialog = page.getByRole('dialog', { name: new RegExp(`^${code('Collaboration', '协作消息')}`) })
    await dialog.waitFor(waits)
    await dialog.getByRole('status').filter({ hasText: /^(Not connected|Disconnected|未连接)$/i }).first().waitFor(waits)
    assert.equal(await dialog.getByRole('button', { name: /^(Start local collaboration|启动本地协作服务)$/i }).isVisible(), true)
    states.collaboration = { existingDialog: true, connectionNotConfigured: true }
  })

  await step('i19-collaboration-return', 'Escape restores the sidebar trigger and preserves the original agent state', async () => {
    await page.keyboard.press('Escape')
    await page.getByRole('dialog').waitFor({ ...waits, state: 'hidden' })
    await page.waitForFunction(() =>
      document.activeElement?.hasAttribute('data-session-index-collaboration') === true,
    null, waits)
    await row.getByRole('img', { name: code('Needs attention', '需要关注'), exact: true }).waitFor(waits)
    states.return = { sidebarFocus: true, pendingApprovalPreserved: true }
  })
  write('session-run-state-checks.json', states)
}

module.exports = { configure, observe }
