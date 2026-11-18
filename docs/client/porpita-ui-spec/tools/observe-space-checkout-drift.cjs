const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const comparePath = value => value.replaceAll('\\', '/').toLowerCase()

async function observeSpaceCheckoutDrift({
  locale, page, app, space, repo, managed, external, externalPath, currentHead, git, holder, parent, previousBranch,
  waits, step, capture, exact, button, caption, branchReview, requireFocus, returnEntry,
  rowFor, openWorktree, forceButton, filter, retainedCount
}) {
  const baseline = process.argv.includes('--space-checkout-drift-baseline')
  const proof = {}
  const dialog = space.getByRole('dialog', {
    name: caption('Review kept branches', '复核保留的分支'), exact: true
  })
  const hidden = { ...waits, state: 'hidden' }
  const movedPath = path.join(parent, process.env.PORPITA_SPEC_WSL_DISTRO ? 'Moved Checkout 蓝' : 'moved checkout 蓝')
  const spaceWindow = await app.browserWindow(space)
  const originalWindowId = await spaceWindow.evaluate(window => window.id)
  const mainSelection = () => page.evaluate(() => window.__store.getState().activeWorktreeId)
  const originalRegistration = await page.evaluate(filePath => {
    const compare = value => value.replaceAll('\\', '/').toLowerCase()
    return Object.values(window.__store.getState().worktreesByRepo).flat().find(worktree =>
      worktree.hostId === 'local' && compare(worktree.path) === compare(filePath))
  }, holder)
  let releaseBranch = previousBranch

  await step('i60-return-after-checkout-move', 'Move a linked checkout and return to the original review by keyboard', async () => {
    await returnEntry.waitFor(waits)
    assert.equal(fs.existsSync(movedPath), false)
    assert.equal(path.dirname(fs.realpathSync(repo)).toLowerCase(), parent.toLowerCase())
    assert.equal(git(holder, 'branch', '--show-current'), managed.branch)
    assert.ok(originalRegistration?.id)
    const primary = page.locator('[data-worktree-id]').filter({ has: page.getByText('main', { exact: true }) })
    await primary.click(waits)
    await page.waitForFunction(id => window.__store.getState().activeWorktreeId !== id,
      originalRegistration.id, waits)
    await page.evaluate(id => window.__store.getState().shutdownWorktreeTerminals(id),
      originalRegistration.id)
    git(repo, 'worktree', 'move', holder, movedPath)
    assert.equal(path.dirname(fs.realpathSync(movedPath)).toLowerCase(), parent.toLowerCase())
    await space.evaluate(() => window.api.workspaceSpace.requestWorktreeRefresh())
    await openWorktree(dialog, managed).waitFor(hidden)
    const beforeReturn = await mainSelection()
    const keptRow = rowFor(dialog, managed)
    const checkbox = keptRow.getByRole('checkbox')
    await checkbox.focus(waits)
    await requireFocus(checkbox)
    await returnEntry.press('Enter', waits)
    await requireFocus(button(dialog, 'Cancel', '取消'))
    assert.equal(await spaceWindow.evaluate(window => window.id), originalWindowId)
    assert.equal(await mainSelection(), beforeReturn)
    assert.equal(await checkbox.getAttribute('aria-checked'), 'true')
    assert.equal(await rowFor(dialog, external).getByRole('checkbox').getAttribute('aria-checked'), 'false')
    assert.equal(currentHead(managed.branch), managed.head)
    assert.equal(git(movedPath, 'branch', '--show-current'), managed.branch)
    assert.equal(comparePath(await keptRow.locator('code').textContent()), comparePath(holder))
    if (baseline) {
      await exact(keptRow, 'Worktree opened in the main window.', '已在主窗口打开工作树。').waitFor(waits)
    }
    await capture(baseline ? 'i60-space-checkout-drift-baseline.jpg' : 'i60-space-fallback-focus.jpg')
    proof.fallback = { checkoutMovedInGit: true, oldButtonRemoved: true, sameSpaceWindow: true,
      cancelReceivedFocus: true, selectionPreserved: true, mainSelectionStableDuringReturn: true,
      previousSuccessStillVisible: baseline }
  })
  if (baseline) return proof
  if (process.argv.includes('--space-checkout-inspection')) {
    const { observeSpaceCheckoutInspection } = require('./observe-space-checkout-inspection.cjs')
    assert.ok(proof.fallback)
    proof.inspection = await observeSpaceCheckoutInspection({
      locale, dialog, space, repo, managed, external, externalPath, currentHead, git, holder, movedPath, previousBranch,
      waits, step, capture, exact, button, branchReview, requireFocus, returnEntry,
      rowFor, forceButton, filter, retainedCount
    })
    return proof
  }

  await step('i61-checkout-record-after-move', 'Show the last known path even if another worktree uses it', async () => {
    assert.ok(proof.fallback)
    const row = rowFor(dialog, managed)
    const lastPath = exact(row, 'Last reported checkout path', '上次检出路径')
    const changed = exact(row, 'This worktree can no longer be located here. Check the current Git checkout before retrying.',
      '这条记录已无法定位到工作树。请先核对 Git 当前的检出位置，再重试。')
    await lastPath.waitFor(waits)
    await changed.waitFor(waits)
    assert.equal(await exact(row, 'Worktree opened in the main window.', '已在主窗口打开工作树。').count(), 0)
    assert.equal(comparePath(await row.locator('code').textContent()), comparePath(holder))

    if (locale === 'en') {
      assert.ok(originalRegistration?.instanceId)
      assert.equal(fs.existsSync(holder), false)
      releaseBranch = previousBranch + '-release'
      git(repo, 'branch', '-m', previousBranch, releaseBranch)
      const replacement = await page.evaluate(async ({ original }) => {
        const created = await window.__store.getState().createWorktree(original.repoId, 'checkout-holder', 'main', 'skip')
        return created.worktree
      }, { original: originalRegistration })
      assert.equal(comparePath(replacement.path), comparePath(holder))
      assert.equal(replacement.id, originalRegistration.id)
      assert.ok(replacement.instanceId && replacement.instanceId !== originalRegistration.instanceId)
      assert.notEqual(git(holder, 'branch', '--show-current'), managed.branch)

      await space.evaluate(({ id, instanceId, timeout }) => new Promise((resolve, reject) => {
        const api = window.api.workspaceSpace
        const timer = setTimeout(() => {
          off()
          reject(new Error('The replacement worktree was not published to Space'))
        }, timeout)
        const off = api.onWindowState(state => {
          const found = Object.values(state.worktreesByRepo).flat().some(worktree =>
            worktree.id === id && worktree.instanceId === instanceId)
          if (found) {
            clearTimeout(timer)
            off()
            resolve()
          }
        })
        void api.requestWindowState()
      }), { id: replacement.id, instanceId: replacement.instanceId, timeout: waits.timeout })
      await changed.waitFor(waits)
      assert.equal(await openWorktree(dialog, managed).count(), 0)
      await row.getByRole('checkbox').focus(waits)
      await returnEntry.press('Enter', waits)
      await requireFocus(button(dialog, 'Cancel', '取消'))
    }
    await capture('i61-space-last-checkout-path.jpg')
    proof.record = { lastPathLabeled: true, staleSuccessCleared: true,
      ...(locale === 'en' ? { replacementAtSamePathDidNotInheritOpenAction: true } : {}) }
  })

  await step('i62-retry-after-checkout-move', 'Recheck Git on explicit submission and use its refreshed blocker', async () => {
    assert.ok(proof.record)
    assert.equal(await rowFor(dialog, managed).getByRole('checkbox').getAttribute('aria-checked'), 'true')
    await forceButton(dialog, 1).press('Enter', waits)
    await dialog.waitFor(hidden)
    await returnEntry.waitFor(hidden)
    await requireFocus(filter)
    await exact(space, 'Last Git branch deletion: 0 confirmed, 1 returned for review.',
      '上次分支清理已确认删除 0 个，1 个退回复核。').waitFor(waits)
    assert.equal(currentHead(managed.branch), managed.head)
    assert.equal(currentHead(external.branch), external.head)

    const refreshed = await branchReview()
    assert.equal(await refreshed.getByRole('checkbox', { checked: true }).count(), 0)
    const refreshedRow = rowFor(refreshed, managed)
    await exact(refreshedRow, 'Checkout path', '检出路径').waitFor(waits)
    assert.equal(comparePath(await refreshedRow.locator('code').textContent()), comparePath(movedPath))
    await capture('i62-space-checkout-refreshed.jpg')

    git(movedPath, 'switch', releaseBranch)
    await refreshedRow.getByRole('checkbox').press('Space', waits)
    await forceButton(refreshed, 1).press('Enter', waits)
    await refreshed.waitFor(hidden)
    await requireFocus(filter)
    await exact(space, 'Deleted 1 Git branch.', '已删除 1 个 Git 分支。').waitFor(waits)
    await retainedCount(1).waitFor(waits)
    assert.equal(currentHead(managed.branch), null)
    assert.equal(currentHead(external.branch), external.head)
    assert.equal(git(movedPath, 'branch', '--show-current'), releaseBranch)
    assert.equal(git(repo, 'branch', '--show-current'), 'main')
    await capture('i62-space-checkout-resolved.jpg')
    proof.retry = { movedCheckoutBlockedDeletion: true, newGitPathShown: true, freshReviewStartsUnselected: true,
      explicitRetryAfterReleaseSucceeded: true, otherBranchPreserved: true }
  })
  return proof
}

module.exports = { observeSpaceCheckoutDrift }
