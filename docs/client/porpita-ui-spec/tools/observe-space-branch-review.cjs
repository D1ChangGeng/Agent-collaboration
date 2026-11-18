const assert = require('node:assert/strict')
const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const refusalName = 'cleanup-refused'
const defaultKeptNames = ['cleanup-kept-one', 'cleanup-kept-two']

function assertContained(parent, entry) {
  const relative = path.relative(fs.realpathSync(parent), fs.realpathSync(entry))
  assert.ok(relative && !relative.startsWith('..') && !path.isAbsolute(relative))
}

async function seedWorktrees(page, repo, env, waits, keptNames, checkoutHolder, gitForSpace) {
  const managedRoot = path.join(path.dirname(repo), 'managed-worktrees')
  assertContained(path.dirname(repo), repo)
  const fixture = await page.evaluate(path => window.api.repos.add({ path }), repo)
  assert.ok(!fixture.error, fixture.error)
  const repoId = fixture.repo.id
  await page.waitForFunction(id => window.__store?.getState().repos.some(row => row.id === id), repoId, waits)
  const worktrees = await page.evaluate(async ({ repoId, managedRoot, names }) => {
    const state = window.__store.getState()
    const normalize = value => value?.replaceAll('\\', '/').toLowerCase()
    if (normalize(state.settings?.workspaceDir) !== normalize(managedRoot)) {
      throw new Error('The Space replay requires the isolated worktree directory')
    }
    const paths = {}
    for (const name of names) {
      const created = await state.createWorktree(repoId, name, 'main', 'skip')
      paths[name] = created.worktree.path
    }
    return paths
  }, { repoId, managedRoot, names: [refusalName, ...keptNames, ...(checkoutHolder ? [checkoutHolder] : [])] })
  assertContained(path.dirname(repo), managedRoot)
  for (const worktree of Object.values(worktrees)) assertContained(managedRoot, worktree)

  const git = gitForSpace ?? ((cwd, ...args) => execFileSync('git', args, {
    cwd, env, windowsHide: true, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']
  }).trim())
  const kept = keptNames.map(name => {
    const cwd = worktrees[name]
    fs.writeFileSync(path.join(cwd, name + '.md'), name + ' contains one unique commit.\n', { flag: 'wx' })
    git(cwd, 'add', '--', name + '.md')
    git(cwd, '-c', 'user.name=Porpita UI Spec', '-c', 'user.email=ui-spec@example.invalid',
      '-c', 'commit.gpgsign=false', 'commit', '-qm', name)
    const branch = git(cwd, 'branch', '--show-current')
    const head = git(cwd, 'rev-parse', 'HEAD')
    assert.ok(branch.endsWith(name) && head !== git(repo, 'rev-parse', 'HEAD'))
    return { name, branch, head }
  })
  const currentHead = (branch) => {
    const ref = 'refs/heads/' + branch
    try {
      git(repo, 'show-ref', '--verify', '--quiet', ref)
    } catch (error) {
      if (error.status !== 1) throw error
      return null
    }
    return git(repo, 'show-ref', '--verify', '--hash', ref)
  }
  return { worktrees, kept, currentHead, git }
}

async function observeSpaceBranchReview({ page, app, step, write, repo, runtime, locale, gitForSpace }) {
  const checkoutDrift = process.argv.includes('--space-checkout-drift')
  const waits = { timeout: checkoutDrift ? 45000 : 18000 }
  const caption = (en, zh) => locale === 'zh' ? zh : en
  const baseline = process.argv.includes('--space-branch-recovery-baseline')
  const recovery = baseline || process.argv.includes('--space-branch-recovery')
  const returnToReview = process.argv.includes('--space-checkout-return')
  const checkoutHolder = returnToReview || process.argv.includes('--space-branch-checkout') ||
    checkoutDrift
    ? 'checkout-holder'
    : null
  const keptNames = recovery ? [...defaultKeptNames, 'cleanup-kept-checked-out'] : defaultKeptNames
  const numbers = {}
  await page.locator('[data-orca-status-bar]').waitFor(waits)
  const { worktrees, kept, currentHead, git } = await seedWorktrees(page, repo, runtime.env, waits, keptNames, checkoutHolder, gitForSpace)
  const monitor = page.locator('[data-orca-status-bar]').getByRole('button', {
    name: caption(/^Resource Manager[,，]/i, /^资源管理器[,，]/)
  })
  await monitor.click(waits)
  const resources = page.getByRole('dialog', { name: caption('Resource Manager', '资源管理器'), exact: true })
  const resourceTab = caption('Resources', '资源')
  await resources.getByRole('tab', { name: resourceTab, exact: true }).click(waits)
  const resourcePanel = resources.getByRole('tabpanel', { name: resourceTab, exact: true })
  await resourcePanel.getByRole('button', { name: caption('Scan', '扫描'), exact: true }).click(waits)
  await page.waitForFunction(count => {
    const state = window.__store.getState()
    return !state.workspaceSpaceScanning && (state.workspaceSpaceAnalysis?.scannedWorktreeCount ?? 0) >= count
  }, keptNames.length + 2 + Number(Boolean(checkoutHolder)), waits)
  const existing = new Set(app.windows())
  const [space] = await Promise.all([
    app.waitForEvent('window', { predicate: candidate => !existing.has(candidate), ...waits }),
    resourcePanel.getByRole('button', { name: caption('Review in Space', '在空间管理中查看'), exact: true }).press('Enter', waits)
  ])
  await space.waitForLoadState('domcontentloaded', waits)
  assert.ok(new URL(space.url()).pathname.endsWith('/space.html'))
  const child = await app.browserWindow(space)
  const isHidden = () => child.evaluate(window => !window.isVisible() && !window.isFocused())
  assert.equal(await isHidden(), true)
  const cdp = await space.context().newCDPSession(space)
  try {
    await cdp.send('Page.enable')
    cdp.on('Page.screencastFrame', ({ sessionId }) => {
      void cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => {})
    })
    await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 88, maxWidth: 1100, maxHeight: 700 })
    await child.evaluate(window => window.webContents.setBackgroundThrottling(false))
    await space.waitForFunction(value => {
      const { lang } = document.documentElement
      return lang && new Intl.Locale(lang).language === value
    }, locale, waits)
    const settledDocumentLanguage = await space.evaluate(() => document.documentElement.lang)
    const resize = async width => {
      await child.evaluate((window, value) => window.setContentSize(value, 700), width)
      await space.waitForFunction(value => innerWidth === value && innerHeight === 700, width, waits)
    }
    const capture = async filename => {
      await space.evaluate(() => document.fonts.ready.then(() => true))
      await space.waitForFunction(() => {
        const dialog = document.querySelector('[role="dialog"]')
        return !dialog || Number(getComputedStyle(dialog).opacity) > 0.99
      }, null, waits)
      const screenshot = await cdp.send('Page.captureScreenshot', { format: 'jpeg', quality: 88, fromSurface: true })
      assert.equal(await isHidden(), true)
      fs.writeFileSync(path.join(process.argv[2], filename), Buffer.from(screenshot.data, 'base64'))
      const rendering = await space.evaluate(() => ({
        size: [innerWidth, innerHeight],
        dpr: devicePixelRatio,
        lang: document.documentElement.lang,
        theme: document.documentElement.classList.contains('dark') ? 'dark' : 'light',
        reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches,
        focus: document.activeElement?.getAttribute('aria-label') ||
          document.activeElement?.getAttribute('placeholder') ||
          document.activeElement?.textContent?.trim().slice(0, 80) || null
      }))
      write(filename.replace(/\.jpg$/, '.json'), {
        ...rendering, imageFile: filename, imageMethod: 'CDP screenshot of hidden Space renderer'
      })
    }
    const filter = space.getByPlaceholder(caption('Filter workspaces', '搜索工作区'))
    const exact = (locator, en, zh) => locator.getByText(caption(en, zh), { exact: true })
    const button = (locator, en, zh) => locator.getByRole('button', { name: caption(en, zh), exact: true })
    const workspaceChoice = name => space.getByRole('checkbox', {
      name: caption('Select ' + name, '选择 ' + name), exact: true
    })
    const requireFocus = async locator => {
      const element = await locator.elementHandle(waits)
      try {
        await space.waitForFunction(node => node.ownerDocument.activeElement === node, element, waits)
      } finally {
        await element.dispose()
      }
    }
    const reviewWorkspaces = async names => {
      for (const name of names) {
        const choice = workspaceChoice(name)
        try {
          await choice.and(space.locator('button:enabled')).waitFor(waits)
        } catch (error) {
          const row = await choice.locator('..').textContent({ timeout: 2000 }).catch(() => '')
          throw new Error('Worktree ' + name + ' did not become eligible: ' + row.trim(), { cause: error })
        }
        await choice.press('Space', waits)
        await choice.and(space.locator('[aria-checked=true]')).waitFor(waits)
      }
      const count = names.length
      await button(space, 'Review deletion (' + count + ')', '查看删除清单（' + count + '）').press('Enter', waits)
      const review = space.getByRole('dialog', { name: caption(count === 1 ? 'Delete Workspace' : 'Delete Workspaces', '删除工作区'), exact: true })
      await review.waitFor(waits)
      const text = (await review.textContent()).replaceAll('\\', '/').toLowerCase()
      for (const [name, worktree] of Object.entries(worktrees)) {
        assert.equal(text.includes(worktree.replaceAll('\\', '/').toLowerCase()), names.includes(name))
      }
      return review
    }
    const reviewBranchesButton = button(space, 'Review kept branches', '复核保留的分支')
    const retainedCount = count => exact(space, count + (count === 1 ? ' Git branch kept.' : ' Git branches kept.'), '已保留 ' + count + ' 个 Git 分支。')
    const branchReview = async () => {
      await reviewBranchesButton.press('Enter', waits)
      const dialog = space.getByRole('dialog', { name: caption('Review kept branches', '复核保留的分支'), exact: true })
      await dialog.waitFor(waits)
      await requireFocus(button(dialog, 'Cancel', '取消'))
      return dialog
    }

    await step('i48-space-refusal', 'Read the actual failed worktree reason at 760 content pixels', async () => {
      await resize(760)
      await filter.fill(refusalName, waits)
      const review = await reviewWorkspaces([refusalName])
      const marker = path.join(worktrees[refusalName], 'late-change.txt')
      const contents = 'Unsaved to Git after the cleanup review opened.\n'
      fs.writeFileSync(marker, contents, { flag: 'wx' })
      await button(review, 'Delete Workspace', '删除工作区').press('Enter', waits)
      await exact(space, 'No workspaces were deleted.', '本次未删除工作区。').waitFor(waits)
      const row = workspaceChoice(refusalName).locator('..')
      const reason = exact(row, 'Uncommitted changes', '有未提交的改动')
      await reason.waitFor(waits)
      await space.evaluate(() => {
        window.__specSpaceRepublished = false
        const off = window.api.workspaceSpace.onWindowState(() => {
          off()
          window.__specSpaceRepublished = true
        })
        void window.api.workspaceSpace.requestWindowState()
      })
      await space.waitForFunction(() => window.__specSpaceRepublished === true, null, waits)
      assert.match(await reason.getAttribute('title'), /\?\? late-change\.txt|untracked/i)
      assert.ok(await reason.evaluate(element => element.scrollWidth <= element.clientWidth))
      assert.equal(fs.readFileSync(marker, 'utf8'), contents)
      const toast = space.locator('[data-sonner-toast][data-visible=true]').first()
      await toast.locator('button[data-close-button]').click(waits)
      await toast.waitFor({ ...waits, state: 'hidden' })
      await capture('i48-space-refusal-reason.jpg')
      await button(space, 'Clear selection', '清除选择').click(waits)
      numbers.refusal = { width: 760, reasonVisible: true, registrationRetained: true, sourceErrorAvailable: true, republished: true }
    })

    await step('i49-space-branch-outcome', 'Remove worktrees and retain their actual unmerged Git branches', async () => {
      assert.ok(numbers.refusal)
      await resize(1100)
      await filter.fill('cleanup-kept-', waits)
      const review = await reviewWorkspaces(keptNames)
      const count = keptNames.length
      await button(review, 'Delete ' + count + ' Workspaces', '删除 ' + count + ' 个工作区').press('Enter', waits)
      try {
        await exact(space, 'Deleted ' + count + ' workspaces.', '已删除 ' + count + ' 个工作区。').waitFor(waits)
      } catch (error) {
        const status = await space.getByRole('status').allTextContents()
        throw new Error(`${error.message}\nSpace status: ${status.filter(Boolean).join(' / ')}`)
      }
      await retainedCount(count).waitFor(waits)
      for (const { name, branch, head } of kept) {
        assert.equal(fs.existsSync(worktrees[name]), false)
        assert.equal(currentHead(branch), head)
      }
      await filter.fill('main', waits)
      await workspaceChoice('main').waitFor(waits)
      assert.equal(await workspaceChoice('main').isDisabled(), true)
      await retainedCount(count).waitFor(waits)
      await reviewBranchesButton.waitFor(waits)
      assert.equal(await space.locator('[data-sonner-toast][data-visible=true]').count(), 0)
      await capture('i49-space-kept-branches.jpg')
      numbers.kept = { workspacePathsRemoved: count, originalRefsKept: count, filterIndependent: true, noToastNeeded: true }
    })

    if (checkoutHolder) {
      const { observeSpaceBranchCheckout } = require('./observe-space-branch-checkout.cjs')
      assert.ok(numbers.kept)
      numbers.checkout = await observeSpaceBranchCheckout({
        returnToReview, locale, page, app, space, repo, kept, currentHead, git, waits, step, capture, resize, exact,
        button, caption, filter, branchReview, retainedCount, requireFocus,
        holderPath: worktrees[checkoutHolder]
      })
    } else if (recovery) {
      const { observeSpaceBranchRecovery } = require('./observe-space-branch-recovery.cjs')
      assert.ok(numbers.kept)
      numbers.recovery = await observeSpaceBranchRecovery({
        baseline, locale, space, repo, kept, currentHead, git, waits, step, capture, resize,
        exact, button, caption, filter, branchReview, retainedCount, requireFocus
      })
    } else await step('i50-space-review-kept-branches', 'Cancel a branch review, reopen and force delete only the selected branch', async () => {
      assert.ok(numbers.kept)
      const forceButton = (dialog, count) => count === 0
        ? button(dialog, 'Force Delete', '强制删除')
        : button(dialog, 'Force Delete ' + count + (count === 1 ? ' Branch' : ' Branches'), '强制删除 ' + count + ' 个分支')
      let dialog = await branchReview()
      for (const row of await dialog.locator('li').all()) {
        await exact(row, /This device ·/, /本机 ·/).waitFor(waits)
      }
      assert.equal(await forceButton(dialog, 0).isDisabled(), true)
      assert.equal(await dialog.getByRole('checkbox', { checked: true }).count(), 0)
      await capture('i50-space-branch-review-empty.jpg')
      const selectAll = dialog.getByRole('checkbox', { name: caption('Select all', '全选'), exact: true })
      await selectAll.press('Space', waits)
      assert.equal(await forceButton(dialog, 2).isEnabled(), true)
      await selectAll.press('Space', waits)
      assert.equal(await forceButton(dialog, 0).isDisabled(), true)
      const one = kept[0]
      const two = kept[1]
      const choice = () => dialog.locator('li').filter({ hasText: one.branch }).getByRole('checkbox')
      await choice().press('Space', waits)
      await space.keyboard.press('Escape')
      await dialog.waitFor({ ...waits, state: 'hidden' })
      await requireFocus(reviewBranchesButton)
      assert.equal(currentHead(one.branch), one.head)
      assert.equal(currentHead(two.branch), two.head)

      dialog = await branchReview()
      assert.equal(await forceButton(dialog, 0).isDisabled(), true)
      await choice().press('Space', waits)
      await capture('i50-space-branch-review-selected.jpg')
      await forceButton(dialog, 1).press('Enter', waits)
      await dialog.waitFor({ ...waits, state: 'hidden' })
      await requireFocus(filter)
      await retainedCount(1).waitFor(waits)
      assert.equal(currentHead(one.branch), null)
      assert.equal(currentHead(two.branch), two.head)
      await capture('i50-space-branch-review-result.jpg')

      const remaining = await branchReview()
      assert.equal(await remaining.locator('li').count(), 1)
      assert.match(await remaining.locator('li').textContent(), new RegExp(two.name))
      await space.keyboard.press('Escape')
      numbers.review = { initialCancelFocus: true, noneSelected: true, selectAllAndClear: true, escapeReturnsToTrigger: true,
        cancelPreservedBothRefs: true, submitFocusedFilter: true, onlySelectedRefRemoved: true, remainingRefReviewable: true }
    })
    write('space-branch-review-checks.json', { locale, documentLanguage: settledDocumentLanguage, hiddenWindow: true, ...numbers })
  } finally {
    await cdp.send('Page.stopScreencast').catch(() => {})
    await cdp.detach().catch(() => {})
    if (!space.isClosed()) await child.evaluate(window => window.close())
  }
}

module.exports = { observeSpaceBranchReview }
