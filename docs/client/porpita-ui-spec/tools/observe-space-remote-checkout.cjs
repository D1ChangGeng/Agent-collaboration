const assert = require('node:assert/strict')
const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const { prepareStudio, reservePort } = require('./observe-host-search.cjs')

const hostName = 'Studio'
const worktreeName = 'checkout-review'

function seed({ temporary }) {
  const profile = path.join(temporary, 'studio-branch-profile')
  const studioHome = path.join(profile, 'home')
  const studioRepo = path.join(temporary, 'Studio-repository')
  for (const dir of [studioRepo, path.join(studioHome, 'AppData/Local'), path.join(studioHome, 'AppData/Roaming')]) {
    fs.mkdirSync(dir, { recursive: true })
  }
  fs.writeFileSync(path.join(profile, 'orca-data.json'), JSON.stringify({
    settings: {
      workspaceDir: path.join(temporary, 'Studio-worktrees'),
      telemetry: { optedIn: false }
    },
    onboarding: { flowVersion: 4, closedAt: 1, outcome: 'completed', lastCompletedStep: 5 }
  }))
  return { profile, studioHome, studioRepo }
}

async function observe({ page, win, step, write, fixtures, repo, runtime, locale }) {
  const studio = prepareStudio(runtime, fixtures)
  const waits = { timeout: 45000 }
  const text = (en, zh) => locale === 'zh' ? zh : en
  const button = (root, en, zh) => root.getByRole('button', { name: text(en, zh), exact: true })
  const exact = (root, en, zh) => root.getByText(text(en, zh), { exact: true })
  const comparePath = value => value.replaceAll('\\', '/').toLowerCase()
  const git = (cwd, ...args) => execFileSync('git', args, {
    cwd, windowsHide: true, env: runtime.env, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']
  }).trim()
  const gitRef = (cwd, branch) => {
    const ref = 'refs/heads/' + branch
    try {
      git(cwd, 'show-ref', '--verify', '--quiet', ref)
    } catch (error) {
      if (error.status !== 1) throw error
      return null
    }
    return git(cwd, 'show-ref', '--verify', '--hash', ref)
  }
  const dialog = page.getByRole('dialog', { name: text('Review kept branches', '复核保留的分支'), exact: true })
  const force = button(dialog, 'Force Delete 1 Branch', '强制删除 1 个分支')
  const studioRepo = fixtures.studioRepo
  const holdingPath = path.join(path.dirname(studioRepo), 'Studio Checkout 蓝')
  const movedPath = path.join(path.dirname(studioRepo), 'Studio Checkout 移动')
  const proof = {}
  try {
    const pairingCode = await studio.start(await reservePort(), true)
    const environmentId = await page.evaluate(async ({ name, pairingCode }) => {
      const { environment } = await window.api.runtimeEnvironments.addFromPairingCode({ name, pairingCode })
      const state = window.__store.getState()
      state.setRuntimeEnvironments(await window.api.runtimeEnvironments.list())
      if (!await state.refreshRuntimeEnvironmentStatus(environment.id)) {
        throw new Error('The Studio pairing did not connect')
      }
      return environment.id
    }, { name: hostName, pairingCode })
    const { repo: remoteRepo } = await page.evaluate(async ({ selector, path }) => {
      const response = await window.api.runtimeEnvironments.call({
        selector, method: 'repo.add', params: { path, kind: 'git', displayName: 'Studio repository' }
      })
      if (!response.ok) throw new Error(response.error.message)
      await window.__store.getState().fetchRepos({ runtimeEnvironmentId: selector })
      return response.result
    }, { selector: environmentId, path: studioRepo })
    const created = await page.evaluate(async ({ repoId, name }) => {
      const result = await window.__store.getState().createWorktree(repoId, name, 'main', 'skip')
      return result.worktree
    }, { repoId: remoteRepo.id, name: worktreeName })
    const relative = path.relative(path.dirname(studioRepo), fs.realpathSync(created.path))
    assert.ok(relative && !relative.startsWith('..') && !path.isAbsolute(relative))
    git(created.path, '-c', 'user.name=Porpita UI Spec', '-c', 'user.email=ui-spec@example.invalid',
      '-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-qm', 'Retain a Studio-only change')
    const branch = git(created.path, 'branch', '--show-current')
    const head = git(created.path, 'rev-parse', 'HEAD')
    git(repo, 'fetch', '-q', studioRepo, 'refs/heads/' + branch + ':refs/heads/' + branch)
    assert.equal(gitRef(repo, branch), head)
    const remoteRow = page.locator('[data-worktree-id=' + JSON.stringify(created.id) + ']').first()
    const keptRow = dialog.locator('li').filter({ hasText: branch })
    const check = button(keptRow, 'Check checkout for ' + branch, '核对 ' + branch + ' 的检出')
    const reconnect = button(keptRow, 'Reconnect and check checkout for ' + branch, '重连并核对 ' + branch + ' 的检出')
    const recoverFromRow = process.argv.includes('--space-recover-branch')
    const choice = keptRow.getByRole('checkbox')
    const requireFocus = async locator => assert.equal(await locator.evaluate(node => node.ownerDocument.activeElement === node), true)
    const expectPath = async expected => {
      await keptRow.locator('code').waitFor(waits)
      assert.equal(comparePath(await keptRow.locator('code').textContent()), comparePath(expected))
    }

    await step('i66-paired-host-checkout', 'Read the current checkout from the retained paired Host', async () => {
      await win.evaluate((window, width) => window.setContentSize(width, 700), locale === 'zh' ? 760 : 920)
      await remoteRow.hover(waits)
      await page.keyboard.press('Control+Shift+Backspace')
      const removal = page.getByRole('dialog', { name: text('Delete Workspace', '删除工作区'), exact: true })
      await removal.waitFor(waits)
      await button(removal, 'Delete Workspace', '删除工作区').press('Enter', waits)
      await removal.waitFor({ ...waits, state: 'hidden' })
      const reviewEntry = page.getByRole('button', { name: text(/^Review 1 Branch$/, /^复核 1 个分支$/) })
      await reviewEntry.waitFor(waits)
      assert.equal(gitRef(studioRepo, branch), head)
      git(studioRepo, 'worktree', 'add', '-q', holdingPath, branch)
      git(studioRepo, 'worktree', 'move', holdingPath, movedPath)
      await reviewEntry.press('Enter', waits)
      await dialog.waitFor(waits)
      assert.match(await keptRow.textContent(), / · Studio · /)
      assert.equal(await choice.getAttribute('aria-checked'), 'false')
      await check.press('Enter', waits)
      await exact(keptRow, 'Checkout path', '检出路径').waitFor(waits)
      await expectPath(movedPath)
      await requireFocus(check)
      assert.equal(gitRef(studioRepo, branch), head)
      assert.equal(gitRef(repo, branch), head)
      proof.owner = { originalHostPath: true, sameNameAndHeadOnLocal: true, neitherRefModified: true, checkFocused: true }
    })

    await step('i67-paired-host-offline', 'Keep the selection and previous checkout while Studio is disconnected', async () => {
      assert.ok(proof.owner)
      await choice.press('Space', waits)
      await page.evaluate(selector => window.api.runtimeEnvironments.disconnect({ selector }), environmentId)
      await check.press('Enter', waits)
      await exact(keptRow, 'Host unavailable', '暂时无法连接主机').waitFor(waits).catch(async error => {
        throw new Error((await keptRow.textContent({ timeout: 2000 })) + '\n' + error.message)
      })
      await exact(keptRow, 'Last reported checkout path', '上次检出路径').waitFor(waits)
      await expectPath(movedPath)
      await requireFocus(recoverFromRow ? reconnect : check)
      assert.equal(await choice.getAttribute('aria-checked'), 'true')
      assert.equal(await force.isDisabled(), true)
      assert.equal(gitRef(repo, branch), head)
      if (recoverFromRow) {
        const stale = await page.evaluate(async selector => {
          const environments = window.__store.getState().runtimeEnvironments
          const environment = environments.find(item => item.id === selector)
          const revision = environment.pairingRevision ?? environment.createdAt
          const denied = await window.api.runtimeEnvironments.connect({
            selector, expectedEnvironmentPairingRevision: revision + 1
          })
          const status = await window.api.runtimeEnvironments.getStatus({ selector })
          return { denied: denied.error?.code, status: status.error?.code }
        }, environmentId)
        assert.equal(stale.denied, 'runtime_environment_changed')
        assert.equal(stale.status, 'runtime_manually_disconnected')
      }
      proof.offline = { lastPathRetained: true, selectedBranchRetained: true, explicitSubmitPaused: true,
        ...(recoverFromRow ? { staleReconnectDidNotLiftDisconnect: true } : {}) }
    })

    await step('i67-paired-host-recovered', 'Reconnect the same pairing and check again in the same review', async () => {
      assert.ok(proof.offline)
      git(movedPath, 'switch', '--detach', 'HEAD')
      if (recoverFromRow) {
        const renamed = branch + '-during-reconnect'
        git(studioRepo, 'branch', '-m', branch, renamed)
        try {
          await reconnect.press('Enter', waits)
          await exact(keptRow, 'Result unconfirmed', '结果未确认').waitFor(waits)
          assert.equal(await force.isDisabled(), true)
          assert.equal(await choice.getAttribute('aria-checked'), 'true')
          await requireFocus(check)
          proof.inconclusive = { reconnectDidNotAuthorizeDelete: true, selectionRetained: true }
        } finally {
          git(studioRepo, 'branch', '-m', renamed, branch)
        }
        await check.press('Enter', waits)
      } else {
        const result = await page.evaluate(selector => window.api.runtimeEnvironments.connect({ selector }), environmentId)
        assert.equal(result.ok, true)
        await check.press('Enter', waits)
      }
      await exact(keptRow, 'No checkout', '未检出').waitFor(waits)
      await requireFocus(check)
      assert.equal(await choice.getAttribute('aria-checked'), 'true')
      assert.equal(await force.isEnabled(), true)
      proof.recovered = { sameRowAndFocus: true, sameSelection: true, newGitResult: true,
        ...(recoverFromRow ? { initiatedFromOriginalRow: true } : {}) }
    })

    await step('i67-paired-host-retry', 'Reopen a fresh review when Git refuses a checkout that appeared after the check', async () => {
      assert.ok(proof.recovered)
      git(movedPath, 'switch', branch)
      await force.press('Enter', waits)
      await dialog.waitFor({ ...waits, state: 'hidden' })
      const retry = button(page, 'Review failed branches', '复核未删除的分支')
      await retry.press('Enter', waits)
      await dialog.waitFor(waits)
      assert.equal(await choice.getAttribute('aria-checked'), 'false')
      await expectPath(movedPath)
      assert.equal(gitRef(studioRepo, branch), head)
      assert.equal(gitRef(repo, branch), head)
      proof.race = { checkedOutAfterReadBlocksSubmit: true, freshReviewStartsUnselected: true }
    })

    await step('i67-paired-host-result', 'Release the checkout and submit again only on the original paired host', async () => {
      assert.ok(proof.race)
      git(movedPath, 'switch', '--detach', 'HEAD')
      await check.press('Enter', waits)
      await exact(keptRow, 'No checkout', '未检出').waitFor(waits)
      assert.equal(await choice.getAttribute('aria-checked'), 'false')
      await choice.press('Space', waits)
      await force.press('Enter', waits)
      await dialog.waitFor({ ...waits, state: 'hidden' })
      await exact(page, 'Git branches deleted: 1', '已删除 1 个 Git 分支').waitFor(waits)
      assert.equal(gitRef(studioRepo, branch), null)
      assert.equal(gitRef(repo, branch), head)
      proof.result = { onlyOriginalHostBranchDeleted: true, sameNameLocalRefPreserved: true }
    })
    assert.equal(await win.evaluate(window => !window.isVisible() && !window.isFocused()), true)
    write('paired-branch-checks.json', { locale, transport: 'paired Runtime over loopback', hiddenWindow: true, ...proof })
  } finally {
    await studio.stop()
  }
}

module.exports = { seed, observe }
