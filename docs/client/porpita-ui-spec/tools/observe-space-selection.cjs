const assert = require('node:assert/strict')

async function observeSpaceSelection({
  caption, waits, step, poll, desktopApp, openManager, requireStudioPreview, captureSpaceWindow, checks,
  managedWorktrees
}) {
  let space
  let child
  try {
    await step('i43-space-folder-navigation', 'Inspect a folder chart and return using the keyboard', async () => {
      assert.ok(checks.spaceReview?.actualScan)
      const contents = await openManager('resources')
      const review = contents.getByRole('button', {
        name: caption('Review in Space', '在空间管理中查看'), exact: true
      })
      const existing = new Set(desktopApp().windows())
      ;[space] = await Promise.all([
        desktopApp().waitForEvent('window', { predicate: candidate => !existing.has(candidate), timeout: 14000 }),
        review.press('Enter', waits)
      ])
      await space.waitForLoadState('domcontentloaded', waits)
      assert.ok(new URL(space.url()).pathname.endsWith('/space.html'))
      child = await desktopApp().browserWindow(space)
      const overview = space.getByRole('group', { name: caption('Workspace sizes', '工作区大小'), exact: true })
      const folders = space.getByRole('group', { name: caption('Folder sizes', '目录大小'), exact: true })
      const enter = overview.getByRole('button', { name: caption('View folders', '查看目录'), exact: true })
      const back = folders.getByRole('button', { name: caption('Back to workspaces', '返回工作区概览'), exact: true })
      const focus = locator => locator.evaluate(node => node.ownerDocument.activeElement === node)
      const tile = overview.getByRole('button', { name: caption(/^View folders for main,/, /^查看 main 的目录，/) })
      await tile.press('Enter', waits)
      await back.waitFor(waits)
      await poll(() => focus(back), Boolean, 'Entering the folder chart must hand focus to Back to workspaces')
      await folders.getByText('.git', { exact: true }).waitFor(waits)
      await captureSpaceWindow(space, child, 'i43-space-folders.jpg')
      await back.press('Space', waits)
      await enter.waitFor(waits)
      await poll(() => focus(enter), Boolean, 'Returning from the folder chart must keep focus in the chart')
      await captureSpaceWindow(space, child, 'i43-space-overview.jpg')
      await enter.press('Enter', waits)
      await poll(() => focus(back), Boolean, 'The toolbar action must use the same keyboard path')
      await back.press('Space', waits)
      await enter.waitFor(waits)
      checks.spaceNavigation = { realFolderSizes: true, tileEntry: true, toolbarEntry: true, keyboardFocus: true }
    })

    await step('i44-space-filtered-selection', 'Check visible review scope with two real linked worktrees', async () => {
      assert.ok(space && child && checks.spaceNavigation)
      const filter = space.getByPlaceholder(caption('Filter workspaces', '搜索工作区'))
      const choice = name => space.getByRole('checkbox', {
        name: caption('Select ' + name, '选择 ' + name), exact: true
      })
      const alpha = choice('review-alpha')
      const beta = choice('review-beta')
      const review = count => space.getByRole('button', {
        name: caption('Review deletion (' + count + ')', '查看删除清单（' + count + '）'), exact: true
      })
      const outsideFilter = count =>
        space.getByText(caption(
          count + ' selected outside the current filter', '当前筛选范围外已选 ' + count + ' 项'
        ), { exact: true })
      await alpha.waitFor(waits)
      await beta.waitFor(waits)
      await poll(async () => await alpha.isEnabled() && await beta.isEnabled(), Boolean,
        'The clean linked worktrees did not receive deletion readiness')
      assert.equal(await choice('main').isDisabled(), true)
      await alpha.press('Space', waits)
      await beta.press('Space', waits)
      await review(2).waitFor(waits)
      await filter.fill('review-alpha')
      await outsideFilter(1).waitFor(waits)
      assert.equal(await review(1).isEnabled(), true)
      await captureSpaceWindow(space, child, 'i44-space-filtered.jpg')
      await review(1).click(waits)
      const dialog = space.getByRole('dialog', { name: caption('Delete Workspace', '删除工作区') })
      await dialog.waitFor(waits)
      assert.match(await dialog.innerText(), /review-alpha/)
      assert.doesNotMatch(await dialog.innerText(), /review-beta/)
      await captureSpaceWindow(space, child, 'i44-space-one-target-review.jpg')
      await dialog.getByRole('button', { name: caption('Cancel', '取消'), exact: true }).click(waits)
      await dialog.waitFor({ ...waits, state: 'hidden' })
      await filter.fill('no-visible-review-worktrees')
      await outsideFilter(2).waitFor(waits)
      assert.equal(await review(0).isDisabled(), true)
      await captureSpaceWindow(space, child, 'i44-space-hidden-only.jpg')
      await filter.fill('')
      await review(2).waitFor(waits)
      assert.equal(await alpha.getAttribute('aria-checked'), 'true')
      assert.equal(await beta.getAttribute('aria-checked'), 'true')
      await space.getByRole('button', { name: caption('Clear selection', '清除选择'), exact: true }).click(waits)
      await poll(async () => await alpha.getAttribute('aria-checked') === 'false' &&
        await beta.getAttribute('aria-checked') === 'false', Boolean, 'Clear selection did not clear both worktrees')
      assert.equal(await choice('main').isDisabled(), true)
      checks.spaceSelection = { linkedWorktrees: 2, protectedMain: true, reviewedVisibleOnly: true,
        hiddenOnlyUnavailable: true, restoredByRemovingFilter: true, cleared: true, cancelled: true }
    })
    if (process.argv.includes('--space-cleanup-continuity')) {
      assert.ok(space && child && checks.spaceSelection)
      const { observeSpaceCleanup } = require('./observe-space-cleanup.cjs')
      await observeSpaceCleanup({ space, child, caption, waits, step, poll, captureSpaceWindow, checks,
        managedWorktrees })
    }
  } finally {
    if (child && !space.isClosed()) {
      await child.evaluate(window => window.close())
      await requireStudioPreview()
    }
  }
}

module.exports = { observeSpaceSelection }
