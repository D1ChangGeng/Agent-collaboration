const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

function normalizedPath(value) {
  return value.replaceAll('\\', '/').toLowerCase()
}

async function observeSpaceBranchCheckout({
  returnToReview, locale, page, app, space, repo, kept, currentHead, git, waits, step, capture, resize, exact,
  button, caption, filter, branchReview, retainedCount, requireFocus, holderPath
}) {
  const [managed, external] = kept
  const proof = {}
  const parent = fs.realpathSync(path.dirname(repo))
  const externalPath = path.join(parent, 'outside checkout 蓝')
  const holder = fs.realpathSync(holderPath)
  const holderRelative = path.relative(parent, holder)
  assert.ok(holderRelative && !holderRelative.startsWith('..') && !path.isAbsolute(holderRelative))
  const previousBranch = git(holder, 'branch', '--show-current')
  assert.ok(previousBranch.endsWith('checkout-holder'))
  assert.equal(fs.existsSync(externalPath), false)

  const rowFor = (dialog, branch) => dialog.locator('li').filter({ hasText: branch.branch })
  const forceButton = (dialog, count) => button(
    dialog,
    count === 1 ? 'Force Delete 1 Branch' : 'Force Delete 2 Branches',
    '强制删除 ' + count + ' 个分支'
  )
  const openWorktree = (dialog, branch) => button(
    rowFor(dialog, branch), 'Open worktree for ' + branch.branch, '打开 ' + branch.branch + ' 的工作树'
  )
  const returnEntry = button(page.locator('[data-orca-status-bar]'),
    'Return to Space review', '返回 Space 复核')
  const hidden = { ...waits, state: 'hidden' }

  await step('i54-branch-checkout-location', 'Read the Git checkout paths of both recorded refusals', async () => {
    await resize(locale === 'zh' ? 760 : 850)
    const initial = await branchReview()
    git(holder, 'switch', managed.branch)
    git(repo, 'worktree', 'add', '-q', externalPath, external.branch)
    const added = fs.realpathSync(externalPath)
    assert.equal(path.dirname(added).toLowerCase(), parent.toLowerCase())
    await initial.getByRole('checkbox', {
      name: caption('Select all', '全选'), exact: true
    }).press('Space', waits)
    await forceButton(initial, 2).press('Enter', waits)
    await initial.waitFor(hidden)
    await requireFocus(filter)
    await exact(space, 'Last Git branch deletion: 0 confirmed, 2 returned for review.',
      '上次分支清理已确认删除 0 个，2 个退回复核。').waitFor(waits)
    await retainedCount(2).waitFor(waits)
    assert.equal(currentHead(managed.branch), managed.head)
    assert.equal(currentHead(external.branch), external.head)

    const review = await branchReview()
    for (const [branch, location] of [[managed, holder], [external, added]]) {
      const row = rowFor(review, branch)
      await exact(row, 'Checkout path', '检出路径').waitFor(waits)
      assert.equal(normalizedPath(await row.locator('code').textContent()), normalizedPath(location))
    }
    await openWorktree(review, managed).waitFor(waits)
    assert.equal(await openWorktree(review, external).count(), 0)
    if (returnToReview) assert.equal(await returnEntry.count(), 0)
    await capture('i54-space-checkout-paths.jpg')
    await rowFor(review, external).locator('code').scrollIntoViewIfNeeded(waits)
    await capture('i54-space-checkout-external.jpg')
    await space.keyboard.press('Escape')
    await review.waitFor(hidden)
    proof.location = { bothPathsFromGit: true, spacedUnicodePathRetained: true, manuallyManagedPathVisible: true,
      externalPathScrolledIntoView: true }
  })

  await step('i55-branch-open-checkout', 'Open the exact registered worktree from its retained branch', async () => {
    assert.ok(proof.location)
    const findHolder = (candidatePath) => {
      const state = window.__store.getState()
      const compare = value => value.replaceAll('\\', '/').toLowerCase()
      return Object.values(state.worktreesByRepo).flat().find(record =>
        compare(record.path) === compare(candidatePath) && record.hostId === 'local')
    }
    const registration = await page.evaluate(findHolder, holder)
    assert.ok(registration?.id)
    const before = await page.evaluate(() => window.__store.getState().activeWorktreeId)
    const refused = await space.evaluate(async ({ id, instanceId }) =>
      window.api.workspaceSpace.revealCheckout({
        worktreeId: id, executionHostId: 'local', instanceId: instanceId + '-superseded'
      }), registration)
    assert.equal(refused, false)
    assert.equal(await page.evaluate(() => window.__store.getState().activeWorktreeId), before)

    const review = await branchReview()
    const choice = rowFor(review, managed).getByRole('checkbox')
    await choice.press('Space', waits)
    await openWorktree(review, managed).press('Enter', waits)
    await exact(rowFor(review, managed), 'Worktree opened in the main window.',
      '已在主窗口打开工作树。').waitFor(waits)
    await page.waitForFunction(id => {
      const state = window.__store.getState()
      return state.activeWorktreeId === id && state.activeWorkspaceExecutionHostId === 'local'
    }, registration.id, waits)
    assert.equal(await choice.getAttribute('aria-checked'), 'true')
    assert.equal(git(holder, 'branch', '--show-current'), managed.branch)
    assert.equal(currentHead(managed.branch), managed.head)
    await capture('i55-space-checkout-opened.jpg')
    proof.opened = { exactRegisteredWorktree: true, acknowledgedByMain: true, otherInstanceRefused: true,
      sameDialogAndSelection: true, checkoutWasNotSwitched: true }
  })

  if (process.argv.includes('--space-checkout-drift')) {
    const { observeSpaceCheckoutDrift } = require('./observe-space-checkout-drift.cjs')
    assert.ok(proof.opened)
    proof.drift = await observeSpaceCheckoutDrift({
      locale, page, app, space, repo, managed, external, externalPath, currentHead, git, holder, parent, previousBranch,
      waits, step, capture, exact, button, caption, branchReview, requireFocus, returnEntry,
      rowFor, openWorktree, forceButton, filter, retainedCount
    })
    return proof
  }

  if (returnToReview) {
    const { observeSpaceCheckoutReturn } = require('./observe-space-checkout-return.cjs')
    assert.ok(proof.opened)
    proof.returnReview = await observeSpaceCheckoutReturn({
      locale, page, app, space, repo, managed, external, currentHead, git, holder, waits, step, capture,
      exact, button, caption, branchReview, requireFocus, returnEntry,
      rowFor, openWorktree
    })
    return proof
  }

  await step('i56-branch-checkout-resume', 'Resume the same review and retry only after the checkouts are released', async () => {
    assert.ok(proof.opened)
    const review = space.getByRole('dialog', {
      name: caption('Review kept branches', '复核保留的分支'), exact: true
    })
    await review.waitFor(waits)
    assert.equal(await rowFor(review, managed).getByRole('checkbox').getAttribute('aria-checked'), 'true')
    const hasReturnEntry = await page.evaluate(() => typeof window.api.workspaceSpace.returnToCheckoutReview === 'function')
    if (hasReturnEntry) await returnEntry.waitFor(waits)
    git(holder, 'switch', previousBranch)
    await forceButton(review, 1).press('Enter', waits)
    await review.waitFor(hidden)
    if (hasReturnEntry) await returnEntry.waitFor(hidden)
    await requireFocus(filter)
    await exact(space, 'Deleted 1 Git branch.', '已删除 1 个 Git 分支。').waitFor(waits)
    await retainedCount(1).waitFor(waits)
    assert.equal(currentHead(managed.branch), null)
    assert.equal(currentHead(external.branch), external.head)
    assert.equal(git(holder, 'branch', '--show-current'), previousBranch)
    await capture('i56-space-checkout-resumed.jpg')

    // Release the external worktree through Git, then use the same Space review again.
    git(externalPath, 'switch', '--detach', external.head)
    const last = await branchReview()
    assert.equal(await last.locator('li').count(), 1)
    const row = rowFor(last, external)
    await exact(row, 'Checkout path', '检出路径').waitFor(waits)
    await row.getByRole('checkbox').press('Space', waits)
    await forceButton(last, 1).press('Enter', waits)
    await last.waitFor(hidden)
    await requireFocus(filter)
    await button(space, 'Review kept branches', '复核保留的分支').waitFor(hidden)
    assert.equal(currentHead(external.branch), null)
    assert.equal(git(repo, 'branch', '--show-current'), 'main')
    await capture('i56-space-checkout-completed.jpg')
    proof.resumed = { approvedCheckoutReleased: true, submittedAgainThroughSpace: true,
      externalFallbackResolved: true, retainedOtherBranchUntilSelected: true,
      filterFocusRestored: true, reviewCleared: true,
      ...(hasReturnEntry ? { submissionClearedReturnEntry: true } : {}) }
  })
  return proof
}

module.exports = { observeSpaceBranchCheckout }
