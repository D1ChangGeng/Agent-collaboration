const assert = require('node:assert/strict')

function observeUsage({ browser, caption, waits, preview, workspaceId, composer, studioHost, hostName }) {
  const bar = () => browser().locator('[data-orca-status-bar] .status-bar-usage-cluster')
  const setup = host => host === 'local'
    ? caption('Set up usage on Local Windows', '在 Local Windows 设置用量')
    : caption(`Set up usage on ${hostName}`, `在 ${hostName} 设置用量`)
  const usage = host => host === 'local'
    ? caption('Usage on Local Windows', 'Local Windows 的用量')
    : caption(`Usage on ${hostName}`, `${hostName} 的用量`)
  const setupButton = host => bar().getByRole('button', { name: setup(host), exact: true })
    .or(bar().getByRole('button', { name: usage(host), exact: true }))
  const sameWorkspace = async () => assert.equal(
    await preview().locator('[data-workspace-preview-object]').getAttribute('data-workspace-preview-object'),
    workspaceId
  )
  const scope = host => setupButton(host).waitFor(waits)
  let usageFixture

  return {
    scope,
    async select(host) {
      await composer(host).click(waits)
      await scope(host)
      await sameWorkspace()
    },
    async standalone() {
      await bar().waitFor({ ...waits, state: 'attached' })
      await browser().waitForFunction(() =>
        document.querySelector('[data-orca-status-bar] .status-bar-usage-cluster')?.textContent.trim() === '',
        null, waits)
    },
    async openAccounts(host) {
      await setupButton(host).press('Enter', waits)
      const hostPicker = browser().getByRole('combobox', {
        name: caption('Host', '主机'), exact: true
      }).first()
      const label = host === 'local' ? 'Local Windows' : hostName
      await hostPicker.filter({ hasText: label }).waitFor(waits)
      assert.equal(await hostPicker.innerText(), label)
      await browser().getByRole('button', { name: /^(Back to app|返回应用|回到应用)$/i }).click(waits)
      await scope(host)
      await sameWorkspace()
    },
    async nativeEditor(host) {
      await bar().waitFor(waits)
      if (host === studioHost) {
        await bar().getByRole('button', {
          name: caption(`No usage on ${hostName}`, `${hostName} 上没有用量`), exact: true
        }).waitFor(waits)
      }
      assert.equal(await setupButton(host).count(), 0)
    },
    async showUsageFixture() {
      usageFixture = await browser().evaluate(() => {
        const store = window.__store
        const { rateLimits, statusBarItems, detectedAgentIds, usagePercentageDisplay } = store.getState()
        store.setState({
          statusBarItems: [...new Set([...statusBarItems, 'codex'])],
          detectedAgentIds: [...new Set([...(detectedAgentIds ?? []), 'codex'])],
          usagePercentageDisplay: 'used',
          rateLimits: {
            ...rateLimits,
            codex: {
              provider: 'codex',
              session: { usedPercent: 37, windowMinutes: 300, resetsAt: null, resetDescription: null },
              weekly: null,
              updatedAt: Date.now(),
              error: null,
              status: 'ok'
            }
          }
        })
        return { rateLimits, statusBarItems, detectedAgentIds, usagePercentageDisplay }
      })
      await bar().getByRole('button', { name: usage('local'), exact: true })
        .filter({ hasText: '37%' }).click(waits)
      const menu = browser().getByRole('menu').filter({ hasText: usage('local') })
      await menu.getByRole('menuitem', {
        name: caption('Manage Accounts…', '管理账户…'), exact: true
      }).waitFor(waits)
      await menu.getByText('37%', { exact: true }).first().waitFor(waits)
    },
    async clearUsageFixture() {
      if (!usageFixture) return
      await browser().keyboard.press('Escape')
      await browser().evaluate(previous => window.__store.setState(previous), usageFixture)
      usageFixture = undefined
    },
    async disconnected() {
      const text = caption(`${hostName} offline`, `${hostName} 已离线`)
      const notice = bar().getByRole('status').filter({ hasText: text })
      await notice.waitFor(waits)
      assert.equal(await notice.innerText(), text)
      assert.equal(await bar().getByRole('button').count(), 0)
    },
    async revoked() {
      const text = caption('Chat usage unavailable', '聊天用量不可用')
      const notice = bar().getByRole('status').filter({ hasText: text })
      await notice.waitFor(waits)
      assert.equal(await notice.innerText(), text)
      assert.doesNotMatch(await bar().innerText(), /Studio/)
      assert.equal(await bar().getByRole('button').count(), 0)
    }
  }
}

module.exports = { observeUsage }
