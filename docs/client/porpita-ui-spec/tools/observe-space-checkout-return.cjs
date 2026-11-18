const assert = require('node:assert/strict')

async function observeSpaceCheckoutReturn({
  locale, page, app, space, repo, managed, external, currentHead, git, holder, waits, step, capture,
  exact, button, caption, branchReview, requireFocus, returnEntry, rowFor, openWorktree
}) {
  const proof = {}
  const dialog = space.getByRole('dialog', {
    name: caption('Review kept branches', '复核保留的分支'), exact: true
  })
  const hidden = { ...waits, state: 'hidden' }
  const mainWindow = await app.browserWindow(page)
  const spaceWindow = await app.browserWindow(space)
  const spaceWindowId = await spaceWindow.evaluate(window => window.id)
  const mainSelection = () => page.evaluate(() => window.__store.getState().activeWorktreeId)
  const mainIsHidden = () => mainWindow.evaluate(window => !window.isVisible() && !window.isFocused())

  await step('i57-workbench-return-entry', 'Find the Space return action in the active workbench', async () => {
    await returnEntry.waitFor(waits)
    const initialSelection = await mainSelection()
    const width = locale === 'zh' ? 820 : 1100
    await mainWindow.evaluate((window, value) => window.setContentSize(value, 700), width)
    await page.waitForFunction(value => innerWidth === value && innerHeight === 700, width, waits)
    await returnEntry.waitFor(waits)
    assert.ok(await returnEntry.isEnabled())
    assert.equal(await mainSelection(), initialSelection)
    assert.equal(await page.evaluate(() => window.api.workspaceSpace.canReturnToCheckoutReview()), true)
    assert.equal(await mainIsHidden(), true)
    proof.entry = { workbenchWidth: width, remainedAfterResize: true, activeCheckoutUnchanged: true }
  })

  await step('i58-space-return-focus', 'Use the workbench action and restore the original Space control', async () => {
    assert.ok(proof.entry)
    const before = await mainSelection()
    const cancel = button(dialog, 'Cancel', '取消')
    const invoker = openWorktree(dialog, managed)
    await cancel.focus(waits)
    await requireFocus(cancel)
    await returnEntry.press('Enter', waits)
    await requireFocus(invoker)
    assert.equal(await spaceWindow.evaluate(window => window.id), spaceWindowId)
    assert.equal(await mainSelection(), before)
    assert.equal(await rowFor(dialog, managed).getByRole('checkbox').getAttribute('aria-checked'), 'true')
    assert.equal(await rowFor(dialog, external).getByRole('checkbox').getAttribute('aria-checked'), 'false')
    assert.equal(await mainIsHidden(), true)
    await capture('i58-space-review-returned.jpg')
    proof.returned = { sameSpaceWindow: true, originatingControlFocused: true, selectionPreserved: true,
      mainWorktreeUnchanged: true }
  })

  await step('i59-space-return-lifetime', 'End the review and verify that the old return cannot reopen it', async () => {
    assert.ok(proof.returned)
    await space.keyboard.press('Escape')
    await dialog.waitFor(hidden)
    await returnEntry.waitFor(hidden)
    assert.equal(await page.evaluate(() => window.api.workspaceSpace.returnToCheckoutReview()), false)

    const next = await branchReview()
    assert.equal(await next.getByRole('checkbox', { checked: true }).count(), 0)
    assert.equal(await returnEntry.count(), 0)
    await openWorktree(next, managed).press('Enter', waits)
    await exact(rowFor(next, managed), 'Worktree opened in the main window.',
      '已在主窗口打开工作树。').waitFor(waits)
    await returnEntry.waitFor(waits)

    if (locale === 'zh') {
      await space.reload({ waitUntil: 'domcontentloaded', timeout: waits.timeout })
      await dialog.waitFor(hidden)
      await returnEntry.waitFor(hidden)
      assert.equal(await page.evaluate(() => window.api.workspaceSpace.returnToCheckoutReview()), false)
    }
    await Promise.all([
      space.waitForEvent('close', waits),
      spaceWindow.evaluate(window => window.close())
    ])
    await returnEntry.waitFor(hidden)
    const count = app.windows().length
    assert.equal(await page.evaluate(() => window.api.workspaceSpace.returnToCheckoutReview()), false)
    assert.equal(app.windows().length, count)
    assert.equal(space.isClosed(), true)
    assert.equal(currentHead(managed.branch), managed.head)
    assert.equal(currentHead(external.branch), external.head)
    assert.equal(git(holder, 'branch', '--show-current'), managed.branch)
    assert.equal(git(repo, 'branch', '--show-current'), 'main')
    proof.lifetime = { cancelledReviewClearedEntry: true, newReviewStartsWithoutEntry: true,
      reloadClearedEntry: locale === 'zh', closedWindowClearedEntry: true,
      staleReturnDidNotOpenWindow: true, branchesPreserved: true }
  })
  return proof
}

module.exports = { observeSpaceCheckoutReturn }
