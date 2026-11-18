const assert = require('node:assert/strict')
const fs = require('node:fs')

const label = 'Standalone SSH'
const workspace = 'Physical checkout'

function seed(profilePath, fixturePath) {
  const remote = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
  assert.match(remote.root, /^\/tmp\/porpita-ssh-review-[A-Za-z0-9]{8}$/)
  const profile = JSON.parse(fs.readFileSync(profilePath, 'utf8'))
  const targetId = 'ssh-ui-spec-standalone'
  const hostId = 'ssh:' + targetId
  const repoId = 'repo-ui-spec-standalone'
  const worktreeId = repoId + '::' + remote.worktreePath
  profile.sshTargets = [{
    id: targetId, label, host: '127.0.0.1', port: 1, username: 'fixture',
    configHost: '127.0.0.1', source: 'manual', generation: 1
  }]
  profile.sshTargetGenerationCounter = 1
  profile.repos = [{
    id: repoId, path: remote.repoPath, displayName: 'Physical Git fixture',
    kind: 'git', badgeColor: '#737373', addedAt: 1, connectionId: targetId
  }]
  profile.worktreeMeta = { [worktreeId]: { hostId, instanceId: 'physical-checkout-instance', displayName: workspace } }
  fs.writeFileSync(profilePath, JSON.stringify(profile))
  return { worktreeId, targetId }
}

async function observe({ page, win, step, write, fixtures, locale }) {
  const waits = { timeout: 22000 }
  const t = (en, zh) => locale === 'zh' ? zh : en
  const row = page.locator('[data-worktree-id=' + JSON.stringify(fixtures.worktreeId) + ']').first()
  const dialog = page.getByRole('dialog', { name: t('Remove “' + workspace + '” from Porpita?', '从 Porpita 移除「' + workspace + '」？'), exact: true })
  const settings = dialog.getByRole('button', { name: t('Open SSH settings', '打开 SSH 设置'), exact: true })
  const proof = {}
  const checkLayout = process.argv.includes('--space-ssh-check-layout')
  const verifyHeader = async (wrapped) => {
    await page.waitForFunction(wrapped => {
      const section = document.querySelector('[data-settings-section="ssh"]')
      const title = section?.querySelector('h2')?.getBoundingClientRect()
      const actions = [...(section?.querySelectorAll('button') ?? [])]
        .find(button => button.textContent.includes('~/.ssh/config'))?.getBoundingClientRect()
      return Boolean(title && actions && (actions.top >= title.bottom) === wrapped)
    }, wrapped, waits)
  }

  await step('i70-ssh-project-needs-host-service', 'Open the existing saved SSH workspace confirmation', async () => {
    await win.evaluate(window => window.setContentSize(760, 700))
    await page.waitForFunction(({ targetId, label }) =>
      window.__store.getState().sshTargetLabels.get(targetId) === label,
    { targetId: fixtures.targetId, label }, waits)
    await row.hover(waits)
    await page.keyboard.press('Control+Shift+Backspace')
    await dialog.waitFor(waits)
    assert.ok((await dialog.innerText()).includes(label))
    assert.equal(await dialog.getByRole('button', { name: /^Force Delete|^强制删除/ }).count(), 0)
    await settings.waitFor(waits)
    proof.capturedSavedTarget = true
  })

  await step('i70-ssh-settings-with-workspace-preserved', 'Open the existing SSH settings without removing the workspace', async () => {
    assert.equal(proof.capturedSavedTarget, true)
    await settings.press('Enter', waits)
    await dialog.waitFor({ ...waits, state: 'hidden' })
    await page.locator('[data-ssh-target-card][data-ssh-target-label=' + JSON.stringify(label) + ']').waitFor(waits)
    assert.equal(await page.evaluate(id => Object.values(window.__store.getState().worktreesByRepo)
      .flat().some(item => item.id === id), fixtures.worktreeId), true)
    assert.equal(await win.evaluate(window => !window.isVisible() && !window.isFocused()), true)
    proof.settingsOpened = true
    proof.workspaceRecordPreserved = true
    if (checkLayout) {
      await verifyHeader(true)
      proof.narrowSharedActionsWrapped = true
    }
  })
  if (checkLayout) {
    await step('i70-ssh-settings-wide', 'Check the same SSH header and actions at desktop width', async () => {
      assert.equal(proof.narrowSharedActionsWrapped, true)
      await win.evaluate(window => window.setContentSize(1160, 700))
      await verifyHeader(false)
      proof.wideHeaderStayedHorizontal = true
    })
  }
  write('standalone-ssh-checks.json', { locale, profile: 'isolated legacy SSH workspace', ...proof })
}

module.exports = { seed, observe }
