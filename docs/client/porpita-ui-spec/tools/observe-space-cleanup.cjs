const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

async function observeSpaceCleanup({
  space, child, caption, waits, step, poll, captureSpaceWindow, checks, managedWorktrees
}) {
  const alpha = 'review-alpha'
  const beta = 'review-beta'
  const gamma = 'review-gamma'
  assert.deepEqual(Object.keys(managedWorktrees).sort(), [alpha, beta, gamma])
  const filter = space.getByPlaceholder(caption('Filter workspaces', '搜索工作区'))
  const checkbox = name => space.getByRole('checkbox', { name: caption('Select ' + name, '选择 ' + name), exact: true })
  const review = count => space.getByRole('button', {
    name: caption('Review deletion (' + count + ')', '查看删除清单（' + count + '）'), exact: true
  })
  const focused = locator => locator.evaluate(node => node.ownerDocument.activeElement === node)
  const completed = space.getByText(caption('Deleted 1 workspace.', '已删除 1 个工作区。'), { exact: true })
  const normalize = value => value.replaceAll('\\', '/').toLowerCase()

  const select = async name => {
    const choice = checkbox(name)
    await choice.waitFor(waits)
    await poll(() => choice.isEnabled(), Boolean, 'The disposable worktree must be available for review')
    if (await choice.getAttribute('aria-checked') !== 'true') {
      await choice.press('Space', waits)
    }
  }

  const openReview = async names => {
    await review(names.length).press('Enter', waits)
    const dialog = space.getByRole('dialog', {
      name: caption(names.length === 1 ? 'Delete Workspace' : 'Delete Workspaces', '删除工作区'), exact: true
    })
    await dialog.waitFor(waits)
    const text = normalize(await dialog.textContent())
    for (const [name, workspacePath] of Object.entries(managedWorktrees)) {
      assert.equal(text.includes(normalize(workspacePath)), names.includes(name),
        'The dialog must contain exactly the intended disposable worktrees')
      if (names.includes(name)) assert.ok(fs.existsSync(workspacePath))
    }
    return dialog
  }

  const deleteConfirmed = (dialog, count) => dialog.getByRole('button', {
    name: count === 1 ? caption('Delete Workspace', '删除工作区') : caption('Delete 2 Workspaces', '删除 2 个工作区'),
    exact: true
  }).click(waits)

  await step('i45-space-review-focus', 'Cancel a deletion review from the keyboard and return to its trigger', async () => {
    await filter.fill(alpha)
    await select(alpha)
    const dialog = await openReview([alpha])
    const cancel = dialog.getByRole('button', { name: caption('Cancel', '取消'), exact: true })
    await poll(() => focused(cancel), Boolean, 'The deletion review must initially focus Cancel')
    await captureSpaceWindow(space, child, 'i45-space-review-cancel-focus.jpg')
    await space.keyboard.press('Enter')
    await dialog.waitFor({ ...waits, state: 'hidden' })
    await poll(() => focused(review(1)), Boolean, 'Cancelling review must return focus to its trigger')
    assert.equal(await filter.inputValue(), alpha)
    assert.equal(await checkbox(alpha).getAttribute('aria-checked'), 'true')
    assert.ok(fs.existsSync(managedWorktrees[alpha]))
    await captureSpaceWindow(space, child, 'i45-space-review-returned.jpg')
    const reopened = await openReview([alpha])
    await space.keyboard.press('Escape')
    await reopened.waitFor({ ...waits, state: 'hidden' })
    await poll(() => focused(review(1)), Boolean, 'Escape must also return to the review trigger')
    checks.spaceReviewFocus = { cancelInitial: true, keyboardCancel: true, escapeCancel: true,
      focusReturned: true, selectionPreserved: true }
  })

  await step('i46-space-cleanup-result', 'Complete one real cleanup and retain the current Space filter', async () => {
    assert.ok(checks.spaceReviewFocus)
    await filter.fill(gamma)
    await select(gamma)
    const dialog = await openReview([gamma])
    await deleteConfirmed(dialog, 1)
    await completed.waitFor(waits)
    await poll(() => focused(filter), Boolean, 'Completed review must hand focus to the filter')
    assert.equal(await filter.inputValue(), gamma)
    await space.getByText(caption('No matching workspaces.', '没有匹配的工作区。'), { exact: true }).waitFor(waits)
    assert.equal(fs.existsSync(managedWorktrees[gamma]), false)
    await captureSpaceWindow(space, child, 'i46-space-cleaned.jpg')
    await filter.fill('')
    assert.equal(await checkbox(alpha).getAttribute('aria-checked'), 'true')
    assert.equal(await checkbox(gamma).count(), 0)
    assert.ok(fs.existsSync(managedWorktrees[alpha]) && fs.existsSync(managedWorktrees[beta]))
    checks.spaceCleanupResult = { realRemoval: true, resultVisible: true, filterRetained: true,
      focusInFilter: true, otherSelectionRetained: true }
  })

  await step('i47-space-partial-cleanup', 'Report a real partial cleanup, then review and retry the remaining worktree', async () => {
    assert.ok(checks.spaceCleanupResult)
    await select(beta)
    const dialog = await openReview([alpha, beta])
    const marker = path.join(managedWorktrees[beta], 'space-cleanup-retry.txt')
    const contents = 'Disposable late worktree change for Space review.\n'
    fs.writeFileSync(marker, contents, { encoding: 'utf8', flag: 'wx' })
    try {
      await deleteConfirmed(dialog, 2)
      await space.getByText(caption(
        'Deleted 1 of 2 workspaces.', '已删除 2 个工作区中的 1 个。'
      ), { exact: true }).waitFor(waits)
      const betaRow = checkbox(beta).locator('..')
      const reason = betaRow.getByText(caption(
        /modified|untracked|uncommitted|dirty|force/i, /修改|未跟踪|未提交|强制|untracked|force/i
      )).first()
      await reason.waitFor(waits)
      await space.evaluate(() => {
        window.__specSpaceWindowRepublished = false
        const off = window.api.workspaceSpace.onWindowState(() => {
          off()
          window.__specSpaceWindowRepublished = true
        })
        void window.api.workspaceSpace.requestWindowState()
      })
      await space.waitForFunction(() => window.__specSpaceWindowRepublished === true, null, waits)
      await reason.waitFor(waits)
      await betaRow.getByText(caption('Failed', '删除失败'), { exact: true }).waitFor(waits)
      assert.equal(fs.existsSync(managedWorktrees[alpha]), false)
      assert.equal(fs.readFileSync(marker, 'utf8'), contents)
      await captureSpaceWindow(space, child, 'i47-space-partial.jpg')
    } finally {
      if (fs.existsSync(marker)) fs.unlinkSync(marker)
    }
    await space.getByRole('button', { name: caption('Refresh', '刷新'), exact: true }).first().click(waits)
    await select(beta)
    const retry = await openReview([beta])
    await deleteConfirmed(retry, 1)
    await completed.waitFor(waits)
    assert.equal(fs.existsSync(managedWorktrees[beta]), false)
    assert.equal(await checkbox('main').isDisabled(), true)
    await captureSpaceWindow(space, child, 'i47-space-retried.jpg')
    checks.spacePartialCleanup = { ordinaryDeletePreservedLateChange: true, realPartialResult: true,
      reasonInRow: true, reasonSurvivedPublication: true, reviewedRetry: true,
      retryRemovedRemaining: true, protectedMain: true }
  })
}

module.exports = { observeSpaceCleanup }
