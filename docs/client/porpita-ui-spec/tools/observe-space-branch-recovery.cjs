const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

function createBranchConflicts(repo, git, changed, checkedOut) {
  const tree = git(repo, 'rev-parse', changed.head + '^{tree}')
  const updatedHead = git(repo, '-c', 'user.name=Porpita UI Spec', '-c', 'user.email=ui-spec@example.invalid',
    '-c', 'commit.gpgsign=false', 'commit-tree', tree, '-p', changed.head, '-m', 'Advance the recorded tip')
  assert.notEqual(updatedHead, changed.head)
  git(repo, 'update-ref', 'refs/heads/' + changed.branch, updatedHead, changed.head)
  // The repository and the added worktree both live under this replay's temporary directory.
  const checkout = path.join(path.dirname(repo), 'branch-taken-by-another-worktree')
  assert.equal(fs.existsSync(checkout), false)
  git(repo, 'worktree', 'add', '-q', checkout, checkedOut.branch)
  const relative = path.relative(fs.realpathSync(path.dirname(repo)), fs.realpathSync(checkout))
  assert.ok(relative && !relative.startsWith('..') && !path.isAbsolute(relative))
  return { updatedHead, checkout }
}

async function observeSpaceBranchRecovery({
  baseline, locale, space, repo, kept, currentHead, git, waits, step, capture, resize,
  exact, button, caption, filter, branchReview, retainedCount, requireFocus
}) {
  const [removed, changed, checkedOut] = kept
  const proof = {}
  const row = (dialog, branch) => dialog.locator('li').filter({ hasText: branch.branch })
  const selectAll = dialog => dialog.getByRole('checkbox', { name: caption('Select all', '全选'), exact: true })
  const submit = (dialog, count) => {
    const noun = count === 1 ? ' Branch' : ' Branches'
    return button(dialog, 'Force Delete ' + count + noun, '强制删除 ' + count + ' 个分支')
  }
  const notices = space.locator('[data-sonner-toast][data-visible=true]')

  if (baseline) {
    await step('i51-branch-refusal-baseline', 'Observe the old branch review after one success and two actual refusals', async () => {
      await resize(850)
      let dialog = await branchReview()
      await selectAll(dialog).press('Space', waits)
      const { updatedHead } = createBranchConflicts(repo, git, changed, checkedOut)
      await submit(dialog, 3).press('Enter', waits)
      await dialog.waitFor({ ...waits, state: 'hidden' })
      await requireFocus(filter)
      await retainedCount(2).waitFor(waits)
      assert.equal(currentHead(removed.branch), null)
      assert.equal(currentHead(changed.branch), updatedHead)
      assert.equal(currentHead(checkedOut.branch), checkedOut.head)
      const failedToast = space.locator('[data-sonner-toast]').filter({ hasText: changed.branch })
      await failedToast.waitFor(waits)
      await capture('i51-old-branch-refusal-toast.jpg')
      await failedToast.locator('button[data-close-button]').click(waits)
      await failedToast.waitFor({ ...waits, state: 'hidden' })
      dialog = await branchReview()
      assert.equal(await row(dialog, changed).getByRole('checkbox').isEnabled(), true)
      assert.equal(await row(dialog, checkedOut).getByRole('checkbox').isEnabled(), true)
      await capture('i52-old-branch-refusal-review.jpg')
      await space.keyboard.press('Escape')
      proof.baseline = { oneBranchDeleted: true, changedTipRetained: true, checkedOutTipRetained: true,
        reasonOnlyInNotification: true, oldCommitStillSelectable: true }
    })
    return proof
  }

  let conflicts
  await step('i51-branch-batch-result', 'Read the confirmed branch result after one deletion and two refusals', async () => {
    await resize(locale === 'zh' ? 760 : 850)
    const dialog = await branchReview()
    await selectAll(dialog).press('Space', waits)
    conflicts = createBranchConflicts(repo, git, changed, checkedOut)
    await submit(dialog, 3).press('Enter', waits)
    await dialog.waitFor({ ...waits, state: 'hidden' })
    await requireFocus(filter)
    const result = exact(space, 'Last Git branch deletion: 1 confirmed, 2 returned for review.',
      '上次分支清理已确认删除 1 个，2 个退回复核。')
    await result.waitFor(waits)
    await retainedCount(2).waitFor(waits)
    assert.equal(currentHead(removed.branch), null)
    assert.equal(currentHead(changed.branch), conflicts.updatedHead)
    assert.equal(currentHead(checkedOut.branch), checkedOut.head)
    await filter.fill('cleanup-kept-', waits)
    await result.waitFor(waits)
    await filter.fill('main', waits)
    assert.equal(await notices.count(), 0)
    await capture('i51-space-branch-batch-result.jpg')
    proof.batch = { confirmedDeleted: 1, returnedForReview: 2, bothRefsPreserved: true, filterIndependent: true,
      focusInFilter: true, noNotificationNeeded: true }
  })

  await step('i52-branch-refusal-states', 'Read the actual changed commit and use Select all on eligible branches', async () => {
    assert.ok(proof.batch)
    const dialog = await branchReview()
    assert.equal(await dialog.locator('li').count(), 2)
    const changedRow = row(dialog, changed)
    const otherRow = row(dialog, checkedOut)
    await exact(changedRow, 'Branch changed', '分支已变化').waitFor(waits)
    await exact(otherRow, 'Checked out', '已在别处检出').waitFor(waits)
    const text = await changedRow.textContent()
    assert.ok(text.includes(changed.head.slice(0, 7)))
    assert.ok(text.includes(conflicts.updatedHead.slice(0, 7)))
    const staleChoice = changedRow.getByRole('checkbox')
    const otherChoice = otherRow.getByRole('checkbox')
    assert.equal(await staleChoice.isDisabled(), true)
    assert.equal(await otherChoice.isEnabled(), true)
    await selectAll(dialog).press('Space', waits)
    assert.equal(await staleChoice.getAttribute('aria-checked'), 'false')
    assert.equal(await otherChoice.getAttribute('aria-checked'), 'true')
    assert.equal(await submit(dialog, 1).isEnabled(), true)
    await capture('i52-space-branch-refusals.jpg')
    await space.keyboard.press('Escape')
    await dialog.waitFor({ ...waits, state: 'hidden' })
    await requireFocus(button(space, 'Review kept branches', '复核保留的分支'))
    proof.refusals = { recordedAndObservedHeadVisible: true, staleExcludedFromSelectAll: true,
      checkedOutStillReviewable: true, cancelPreservedBoth: currentHead(changed.branch) === conflicts.updatedHead &&
        currentHead(checkedOut.branch) === checkedOut.head }
    assert.ok(proof.refusals.cancelPreservedBoth)
  })

  await step('i53-branch-refusal-recovery', 'Keep the changed branch and retry the released checkout', async () => {
    assert.ok(proof.refusals)
    const keepButton = dialog => button(row(dialog, changed), 'Keep branch ' + changed.branch,
      '保留分支 ' + changed.branch)
    const acknowledgement = exact(space, 'Review ended for ' + changed.branch + '.',
      '已结束 ' + changed.branch + ' 的复核。')
    const releaseCheckout = () => {
      assert.equal(git(conflicts.checkout, 'branch', '--show-current'), checkedOut.branch)
      git(conflicts.checkout, 'switch', '--detach', checkedOut.head)
      assert.equal(git(conflicts.checkout, 'branch', '--show-current'), '')
    }
    const retry = async (dialog) => {
      await row(dialog, checkedOut).getByRole('checkbox').press('Space', waits)
      await submit(dialog, 1).press('Enter', waits)
      await dialog.waitFor({ ...waits, state: 'hidden' })
      await requireFocus(filter)
      await exact(space, 'Deleted 1 Git branch.', '已删除 1 个 Git 分支。').waitFor(waits)
      assert.equal(currentHead(checkedOut.branch), null)
      assert.equal(currentHead(changed.branch), conflicts.updatedHead)
    }

    let dialog = await branchReview()
    if (locale === 'en') {
      await keepButton(dialog).press('Enter', waits)
      await row(dialog, changed).waitFor({ ...waits, state: 'hidden' })
      await requireFocus(button(dialog, 'Cancel', '取消'))
      assert.equal(currentHead(changed.branch), conflicts.updatedHead)
      await capture('i53-space-branch-keep.jpg')
      await space.keyboard.press('Escape')
      await dialog.waitFor({ ...waits, state: 'hidden' })
      await acknowledgement.waitFor(waits)
      releaseCheckout()
      dialog = await branchReview()
      await retry(dialog)
    } else {
      releaseCheckout()
      await retry(dialog)
      dialog = await branchReview()
      assert.equal(await dialog.locator('li').count(), 1)
      await keepButton(dialog).press('Enter', waits)
      await dialog.waitFor({ ...waits, state: 'hidden' })
      await requireFocus(filter)
      await acknowledgement.waitFor(waits)
    }
    await button(space, 'Review kept branches', '复核保留的分支').waitFor({ ...waits, state: 'hidden' })
    assert.equal(currentHead(changed.branch), conflicts.updatedHead)
    assert.equal(currentHead(removed.branch), null)
    assert.equal(git(repo, 'branch', '--show-current'), 'main')
    await capture('i53-space-branch-recovered.jpg')
    proof.recovery = { checkedOutReleased: true, retryDeletedOnlyReleasedBranch: true,
      changedBranchKeptInGit: true, reviewCleared: true, protectedMain: true,
      acknowledgementVisible: true,
      keepFocus: locale === 'en' ? 'cancel' : 'filter' }
  })
  return proof
}

module.exports = { observeSpaceBranchRecovery }
