const assert = require('node:assert/strict')

const comparePath = value => value.replaceAll('\\', '/').toLowerCase()

async function observeSpaceCheckoutInspection({
  locale, dialog, space, repo, managed, external, externalPath, currentHead, git, holder, movedPath, previousBranch,
  waits, step, capture, exact, button, branchReview, requireFocus, returnEntry,
  rowFor, forceButton, filter, retainedCount
}) {
  const proof = {}
  const hidden = { ...waits, state: 'hidden' }
  const inspectionButton = (review, branch) => button(
    rowFor(review, branch), 'Check checkout for ' + branch.branch, '核对 ' + branch.branch + ' 的检出'
  )
  const managedRow = rowFor(dialog, managed)
  const managedChoice = managedRow.getByRole('checkbox')
  let preservedExternalHead = external.head

  await step('i63-checkout-read-only-location', 'Check Git checkout after the linked worktree was moved', async () => {
    await exact(managedRow, 'Last reported checkout path', '上次检出路径').waitFor(waits)
    assert.equal(comparePath(await managedRow.locator('code').textContent()), comparePath(holder))
    const check = inspectionButton(dialog, managed)
    await check.press('Enter', waits)
    await exact(managedRow, 'Checkout path', '检出路径').waitFor(waits)
    assert.equal(comparePath(await managedRow.locator('code').textContent()), comparePath(movedPath))
    const distro = process.env.PORPITA_SPEC_WSL_DISTRO
    if (distro) {
      assert.ok((await managedRow.textContent()).includes('WSL ' + distro))
      assert.match((await managedRow.locator('code').textContent()).replaceAll('\\', '/'), /\/Moved Checkout 蓝$/)
      proof.wsl = { distro, nativeGitPathCasePreserved: true }
    }
    await requireFocus(check)
    assert.equal(await managedChoice.getAttribute('aria-checked'), 'true')
    assert.equal(currentHead(managed.branch), managed.head)
    assert.equal(currentHead(external.branch), external.head)
    assert.equal(git(movedPath, 'branch', '--show-current'), managed.branch)
    await capture('i63-space-checkout-current.jpg')
    proof.location = { sameReviewAndSelection: true, checkButtonFocused: true,
      movedPathFoundBeforeSubmit: true, bothBranchRefsPreserved: true }
  })

  if (process.env.PORPITA_SPEC_WSL_RECOVERY_FIXTURE) {
    const { readFixture, wsl } = require('./space-wsl-recovery-distro.cjs')
    const { distro } = readFixture(process.env.PORPITA_SPEC_WSL_RECOVERY_FIXTURE)
    assert.equal(process.env.PORPITA_SPEC_WSL_DISTRO, distro)
    const running = () => wsl(['--list','--running','--quiet']).split(/\r?\n/)
      .some(name => name.trim().toLowerCase() === distro.toLowerCase())
    const passive = inspectionButton(dialog, managed)
    const wake = button(managedRow, 'Start ' + distro + ' and check checkout for ' + managed.branch,
      '启动 ' + distro + ' 并核对 ' + managed.branch + ' 的检出')
    await step('i71-wsl-stopped', 'Stop only the disposable distro and check without waking it', async () => {
      assert.ok(proof.location && running())
      git(movedPath, 'switch', previousBranch)
      wsl(['--terminate', distro])
      assert.equal(running(), false)
      await passive.press('Enter', waits)
      await exact(managedRow, 'WSL unavailable', 'WSL 不可用').waitFor(waits)
      assert.equal(running(), false)
      assert.equal(comparePath(await managedRow.locator('code').textContent()), comparePath(movedPath))
      assert.equal(await managedChoice.getAttribute('aria-checked'), 'true')
      assert.equal(await forceButton(dialog, 1).isDisabled(), true)
      await requireFocus(wake)
      await capture('i71-space-wsl-stopped.jpg')
      proof.stopped = { passiveCheckDidNotWake: true, priorPathKept: true, selectedBranchKept: true, submissionPaused: true }
    })

    await step('i71-wsl-start-and-check', 'Start the named distro from the row and obtain a fresh Git result', async () => {
      assert.ok(proof.stopped)
      await wake.press('Enter', waits)
      await exact(managedRow, 'No checkout', '未检出').waitFor(waits)
      assert.equal(running(), true)
      assert.equal(currentHead(managed.branch), managed.head)
      assert.equal(currentHead(external.branch), external.head)
      assert.equal(await managedChoice.getAttribute('aria-checked'), 'true')
      assert.equal(await forceButton(dialog, 1).isEnabled(), true)
      await requireFocus(passive)
      await capture('i71-space-wsl-started.jpg')
      proof.started = { onlyExplicitStartWokeDistro: true, freshGitResult: true, focusAndSelectionKept: true, bothRefsPreserved: true }
    })
  }

  await step('i64-checkout-release-and-branch-head', 'Check the released checkout in the existing review', async () => {
    assert.ok(proof.location)
    git(movedPath, 'switch', previousBranch)
    const check = inspectionButton(dialog, managed)
    await check.press('Enter', waits)
    await exact(managedRow, 'No checkout', '未检出').waitFor(waits).catch(async error => {
      throw new Error((await managedRow.textContent({ timeout: 2000 })) + '\n' + error.message)
    })
    await exact(managedRow, 'Last reported checkout path', '上次检出路径').waitFor(waits)
    assert.equal(comparePath(await managedRow.locator('code').textContent()), comparePath(movedPath))
    await requireFocus(check)
    assert.equal(await managedChoice.getAttribute('aria-checked'), 'true')
    assert.equal(currentHead(managed.branch), managed.head)
    await capture('i64-space-checkout-available.jpg')

    if (locale === 'en') {
      assert.equal(git(externalPath, 'branch', '--show-current'), external.branch)
      git(externalPath, '-c', 'user.name=Porpita UI Spec', '-c', 'user.email=ui-spec@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-qm', 'Advance the kept branch during review')
      preservedExternalHead = currentHead(external.branch)
      assert.notEqual(preservedExternalHead, external.head)
      const externalRow = rowFor(dialog, external)
      const choice = externalRow.getByRole('checkbox')
      await choice.press('Space', waits)
      await forceButton(dialog, 2).waitFor(waits)
      const checkExternal = inspectionButton(dialog, external)
      await checkExternal.press('Enter', waits)
      await exact(externalRow, 'Branch changed', '分支已变更').waitFor(waits)
      await requireFocus(checkExternal)
      assert.equal(await checkExternal.evaluate(button => {
        const viewport = button.closest('ul').parentElement.getBoundingClientRect()
        const target = button.getBoundingClientRect()
        return target.top > viewport.top && target.bottom < viewport.bottom
      }), true)
      assert.equal(await choice.isDisabled(), true)
      assert.equal(await choice.getAttribute('aria-checked'), 'false')
      await forceButton(dialog, 1).waitFor(waits)
      assert.equal(currentHead(external.branch), preservedExternalHead)
      await capture('i64-space-checkout-head-changed.jpg')
    } else if (locale === 'zh') {
      const renamedBranch = managed.branch + '-during-check'
      git(repo, 'branch', '-m', managed.branch, renamedBranch)
      try {
        await check.press('Enter', waits)
        await exact(managedRow, 'Result unconfirmed', '结果未确认').waitFor(waits)
        await exact(managedRow, 'Last reported checkout path', '上次检出路径').waitFor(waits)
        assert.equal(comparePath(await managedRow.locator('code').textContent()), comparePath(movedPath))
        assert.equal(await managedChoice.getAttribute('aria-checked'), 'true')
        assert.equal(currentHead(renamedBranch), managed.head)
        await requireFocus(check)
        await capture('i64-space-checkout-unconfirmed.jpg')
      } finally {
        git(repo, 'branch', '-m', renamedBranch, managed.branch)
      }
      await check.press('Enter', waits)
      await exact(managedRow, 'No checkout', '未检出').waitFor(waits)
    }
    proof.state = { releasedStatusShown: true, currentReviewSelectionPreserved: true,
      lastPathStillVisible: true,
      ...(locale === 'en' ? { changedHeadRemovedOnlyThatSelection: true, changedHeadFocusVisible: true } : {}),
      ...(locale === 'zh' ? { missingRefRetainsLastPathAndSelection: true, restoredRefCanBeCheckedAgain: true } : {}) }
  })

  await step('i65-checkout-changed-after-check', 'Recheck on submit when a checked branch becomes occupied again', async () => {
    assert.ok(proof.state)
    git(movedPath, 'switch', managed.branch)
    await forceButton(dialog, 1).press('Enter', waits)
    await dialog.waitFor(hidden)
    await returnEntry.waitFor(hidden)
    await requireFocus(filter)
    await exact(space, 'Last Git branch deletion: 0 confirmed, 1 returned for review.',
      '上次分支清理已确认删除 0 个，1 个退回复核。').waitFor(waits)
    assert.equal(currentHead(managed.branch), managed.head)
    assert.equal(currentHead(external.branch), preservedExternalHead)

    const refreshed = await branchReview()
    assert.equal(await refreshed.getByRole('checkbox', { checked: true }).count(), 0)
    const refreshedRow = rowFor(refreshed, managed)
    await exact(refreshedRow, 'Checkout path', '检出路径').waitFor(waits)
    assert.equal(comparePath(await refreshedRow.locator('code').textContent()), comparePath(movedPath))
    await capture('i65-space-checkout-occupied-again.jpg')

    git(movedPath, 'switch', previousBranch)
    await refreshedRow.getByRole('checkbox').press('Space', waits)
    await forceButton(refreshed, 1).press('Enter', waits)
    await refreshed.waitFor(hidden)
    await requireFocus(filter)
    await exact(space, 'Deleted 1 Git branch.', '已删除 1 个 Git 分支。').waitFor(waits)
    await retainedCount(1).waitFor(waits)
    assert.equal(currentHead(managed.branch), null)
    assert.equal(currentHead(external.branch), preservedExternalHead)
    assert.equal(git(movedPath, 'branch', '--show-current'), previousBranch)
    assert.equal(git(repo, 'branch', '--show-current'), 'main')
    await capture('i65-space-checkout-retry-resolved.jpg')
    proof.race = { laterCheckoutBlockedDeletion: true, freshReviewStartsUnselected: true,
      explicitRetryAfterReleaseSucceeded: true, otherBranchPreserved: true }
  })
  return proof
}

module.exports = { observeSpaceCheckoutInspection }
