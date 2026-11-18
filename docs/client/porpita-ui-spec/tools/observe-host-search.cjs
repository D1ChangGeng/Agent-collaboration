const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { createServer } = require('node:net')
const { execFileSync } = require('node:child_process')
const { createRequire } = require('node:module')
const { seedTranscript } = require('./observe-session-history.cjs')
const { observe: observeDirectoryHosts, studioDraft } = require('./observe-session-index-host.cjs')

const title = 'Review the release checklist'
const sessionId = '019f1000-1111-7222-8333-444444444451'
const remoteOnlyId = '019f1000-1111-7222-8333-444444444452'
const localReply = 'The Local queue contains the release checklist.'
const remoteReply = 'The Studio queue contains the release checklist.'
const remoteOnly = 'Studio handoff notes'
const hostName = 'Studio'

function seed({ home, repo, temporary, workspaceExplorerContinuity, workspacePortsFocused }) {
  const profile = path.join(temporary, 'studio-profile')
  const studioHome = path.join(profile, 'home')
  const studioRepo = workspaceExplorerContinuity
    ? path.join(temporary, 'Studio-projects', 'Release-review')
    : path.join(temporary, 'Studio-project')
  fs.mkdirSync(studioRepo, { recursive: true })
  if (workspaceExplorerContinuity) {
    const { seedExplorerFolders } = require('./observe-workspace-explorer-continuity.cjs')
    seedExplorerFolders(repo, studioRepo)
  }
  for (const dir of ['Local', 'Roaming']) {
    fs.mkdirSync(path.join(studioHome, 'AppData', dir), { recursive: true })
  }
  fs.writeFileSync(path.join(profile,'orca-data.json'), JSON.stringify({
    settings: {
      telemetry: { optedIn: false }, aiVaultSearch: { enabled: !workspacePortsFocused, historyDays: null },
      nativeChatProviders: { codex: true }, agentDefaultSurface: 'chat'
    },
    onboarding: { flowVersion: 4, closedAt: 1, outcome: 'completed', lastCompletedStep: 5 }
  }))
  seedTranscript({ home, repo, id: sessionId, clock: '11', prompt: title, reply: localReply })
  const studioSource = seedTranscript({ home: studioHome, repo: studioRepo, id: sessionId, clock: '12', prompt: title, reply: remoteReply })
  seedTranscript({ home: studioHome, repo: studioRepo, id: remoteOnlyId, clock: '10', prompt: remoteOnly, reply: 'The handoff is ready for review.' })
  return { profile, studioHome, studioRepo, studioSource }
}

async function reservePort() {
  const listener = createServer()
  await new Promise((resolve, reject) => {
    listener.once('error', reject)
    listener.listen(0, '127.0.0.1', resolve)
  })
  const port = listener.address().port
  await new Promise((resolve, reject) => listener.close(error => error ? reject(error) : resolve()))
  return port
}

function prepareStudio(runtime, { profile, studioHome, studioRepo }) {
  const load = createRequire(path.join(runtime.source, 'package.json'))
  load('tsx/cjs')
  const read = (relative) => load(path.join(runtime.source, relative))
  const { readServeReadiness } = read('tests/e2e/helpers/headless-paired-runtime-serve-readiness.ts')
  const { closeElectronAppForE2E } = read('tests/e2e/helpers/electron-process-shutdown.ts')
  const homeEnv = {
    ...runtime.env, HOME: studioHome, USERPROFILE: studioHome,
    APPDATA: path.join(studioHome, 'AppData/Roaming'),
    LOCALAPPDATA: path.join(studioHome, 'AppData/Local'),
    ORCA_E2E_USER_DATA_DIR: profile, ORCA_E2E_HOME_DIR: studioHome,
    GIT_CONFIG_GLOBAL: path.join(studioHome, 'gitconfig')
  }
  const git = (...args) => execFileSync('git', args, {
    cwd: studioRepo, env: homeEnv, windowsHide: true, stdio: 'pipe'
  })
  git('init', '-q', '-b', 'main')
  fs.writeFileSync(path.join(studioRepo, 'release.md'), '# Release checklist\n')
  git('add', 'release.md')
  git('-c','user.name=Porpita UI Spec','-c','user.email=ui-spec@example.invalid','-c','commit.gpgSign=false','commit','-qm','Seed Studio')
  let server
  return {
    async start(port, requirePairingOffer) {
      server = await runtime.electron.launch({
        executablePath: runtime.executablePath, env: homeEnv,
        cwd: path.dirname(profile), timeout: 30000,
        args: [runtime.developmentEntry, '--serve', '--serve-json', '--serve-bind', '127.0.0.1',
          '--serve-port', String(port), '--serve-pairing-address', '127.0.0.1',
          ...(requirePairingOffer ? [] : ['--serve-no-pairing'])]
      })
      const offer = await readServeReadiness(server, { requirePairingOffer })
      const actual = await server.evaluate(({ app, BrowserWindow }) => ({
        profile: app.getPath('userData'), home: app.getPath('home'),
        hidden: BrowserWindow.getAllWindows().every(w => !w.isVisible() && !w.isFocused())
      }))
      assert.equal(path.resolve(actual.profile).toLowerCase(), path.resolve(profile).toLowerCase())
      assert.equal(path.resolve(actual.home).toLowerCase(), path.resolve(studioHome).toLowerCase())
      assert.equal(actual.hidden, true)
      return offer?.pairingUrl
    },
    async stop() {
      if (server) {
        const closing = server
        server = undefined
        await closeElectronAppForE2E(closing, { cleanupDaemonsForUserDataDir: profile })
      }
    }
  }
}

async function observe({
  page, win, app, click, button, step, episode, write, repo, fixtures, baseline, runtime,
  hostDirectory, workspaceHostContinuity, workspaceExplorerContinuity, workspaceUsageContinuity,
  workspacePortsContinuity, workspacePortsFocused, locale, userData, restartWorkspaceDesktop
}) {
  assert.ok(runtime.developmentEntry, 'Host replay requires the isolated source build')
  const studio = prepareStudio(runtime, fixtures)
  const port = await reservePort()
  const waits = { timeout: 25000 }
  let environmentId
  let remoteWorkspace
  let studioChat
  let localWorkspace
  const proofs = {}
  const query = page.getByRole('textbox', { name: /^(Search sessions|搜索会话)$/i })
  const rows = page.locator('.ai-vault-session-row:visible')
  const namedRows = rows.filter({ has: page.getByText(title, { exact: true }) })
  const studioRow = namedRows.filter({ has: page.getByText(hostName, { exact: true }) })
  const localRow = namedRows.filter({ has: page.getByText(/^(Local Windows|Local Linux|Local Mac)$/) })
  const refresh = button(/^(Refresh Session History|刷新会话历史)$/i)
  const retry = page.getByRole('button', { name: /^(Try again|重试|再试一次)$/i })
  const recoveredRow = rows.filter({ has: page.getByText(remoteOnly, { exact: true }) })
  const status = () => page.locator('[role=status]').allTextContents()
  const dismissToasts = async () => {
    const toasts = page.locator('[data-sonner-toast] [data-close-button]')
    for (let n = 0; n < 3 && await toasts.first().isVisible(); n++) {
      await toasts.first().click({ timeout: 1500 }).catch(() => {})
    }
  }
  const rpc = async (method, params) => {
    const response = await page.evaluate(
      ({ selector, method, params }) => window.api.runtimeEnvironments.call({ selector, method, params }),
      { selector: environmentId, method, params }
    )
    if (!response.ok) throw new Error(`${method}: ${response.error?.code} ${response.error?.message}`)
    return response.result
  }
  const poll = async (read, accept, message, timeout = waits.timeout) => {
    const stop = Date.now() + timeout
    do {
      const result = await read()
      if (accept(result)) return result
      await new Promise(resolve => setTimeout(resolve, 400))
    } while (Date.now() < stop)
    throw new Error(message)
  }
  const openVault = async () => {
    if (!(await query.isVisible())) {
      const history = button(/^(智能体|Agents)(?:\s|$)/i)
      if (!(await history.isVisible())) {
        await click(/^(Toggle right sidebar|切换右侧边栏|显示\/隐藏右侧边栏)$/i)
      }
      if (workspaceHostContinuity) {
        const dialog = page.locator('[data-slot=dialog-content]:visible').first()
        if (await dialog.isVisible()) {
          const dismiss = dialog.getByRole('button', { name: /^(Close|关闭|Later|稍后|Skip|跳过|Cancel|取消)$/i }).first()
          if (await dismiss.isVisible()) await dismiss.click(waits)
          else await page.keyboard.press('Escape')
          await dialog.waitFor({ ...waits, state: 'hidden' })
        }
        await history.press('Enter', waits)
      } else {
        await history.click(waits)
      }
    }
    await query.waitFor(waits)
  }
  const chooseHost = async (name) => {
    await click(/^(Session History host|会话历史主机)[:：]/)
    await page.getByRole('menuitemradio', { name, exact: true }).click(waits)
  }
  const assertRows = async () => {
    await studioRow.waitFor(waits)
    await localRow.waitFor(waits)
    assert.equal(await namedRows.count(), 2)
  }
  const selectedChat = () => page.evaluate(() => {
    const state = window.__store.getState()
    const workspaceId = state.activeWorktreeId
    const tabId = state.groupsByWorktree[workspaceId]?.find(
      group => group.id === state.activeGroupIdByWorktree[workspaceId]
    )?.activeTabId
    const tab = (state.unifiedTabsByWorktree[workspaceId] ?? []).find(tab => tab.id === tabId)
    return { workspaceId, activeHost: state.activeWorkspaceExecutionHostId, tabHost: tab?.executionHostId,
      contentType: tab?.contentType, id: tab?.id, sessionId: tab?.entityId }
  })
  const observeWorkspace = async () => {
    const { observe: observeWorkspaceHosts } = require('./observe-workspace-host-continuity.cjs')
    await observeWorkspaceHosts({
      page, win, app, step, episode, write, waits, locale, title, hostName,
      localReply, remoteReply,
      localRow, assertHistoryRows: assertRows, selectedChat, poll, localWorkspace,
      remoteWorkspace, studioChat, studioDraft, environmentId, userData, restartWorkspaceDesktop,
      workspaceExplorerContinuity, workspaceUsageContinuity, workspacePortsContinuity, workspacePortsFocused,
      studioRoot: fixtures.studioRepo, localRoot: repo,
      restartStudio: () => studio.start(port, false),
      stopStudio: studio.stop
    })
  }
  try {
    const pairingCode = await studio.start(port, true)
    environmentId = await page.evaluate(async ({ name, pairingCode }) => {
      const { environment } = await window.api.runtimeEnvironments.addFromPairingCode({ name, pairingCode })
      const state = window.__store.getState()
      state.setRuntimeEnvironments(await window.api.runtimeEnvironments.list())
      if (!await state.refreshRuntimeEnvironmentStatus(environment.id)) {
        throw new Error('Studio runtime could not be reached')
      }
      return environment.id
    }, { name: hostName, pairingCode })
    const { repo: studioRepo } = await rpc('repo.add', {
      path: fixtures.studioRepo, kind: 'git', displayName: path.basename(fixtures.studioRepo)
    })
    const worktrees = await rpc('worktree.list', { repo: `id:${studioRepo.id}` })
    remoteWorkspace = worktrees.worktrees[0]?.id
    assert.ok(remoteWorkspace)
    const verifyFixtureIndexes = async () => {
      let outcomes = []
      try {
        await poll(async () => {
          let results
          try {
            results = await Promise.all([
              rpc('aiVault.searchSessions', { query: title, filters: { agents: ['codex'] } }),
              page.evaluate(title => window.api.aiVault.searchSessions({ query: title, filters: { agents: ['codex'] } }, 'local'), title)
            ])
          } catch (error) {
            if (workspaceExplorerContinuity && /runtime_timeout/.test(error.message)) return false
            throw error
          }
          outcomes = results.map(result => ({
            kind: result.kind,
            containsFixture: result.kind === 'results' && result.hits.some(hit => hit.sessionId === sessionId)
          }))
          return outcomes.every(result => result.containsFixture)
        }, Boolean, 'The isolated indexes did not publish both Codex fixtures', workspaceHostContinuity ? 60000 : waits.timeout)
      } catch (error) {
        write('host-index-diagnostics.json', outcomes)
        throw error
      }
      proofs.searchViaPairedRuntime = true
    }
    if (!workspaceHostContinuity) await verifyFixtureIndexes()
    await step(
      workspacePortsFocused ? 'i30-add-worktrees' : 'i5-two-sources',
      workspacePortsFocused ? 'Pair Studio and add the two real worktrees' : 'Search for the same Codex session ID on Local and Studio',
      async () => {
      await app.evaluate(({ dialog }, fixture) => {
        dialog.showOpenDialog = async () => ({ canceled:false, filePaths:[fixture] })
      }, repo)
      await click(/^(添加项目|Add project)$/i)
      await click(/浏览文件夹|Browse folder/i)
      await page.getByText(path.basename(repo), { exact: true }).first().waitFor(waits)
      localWorkspace = await poll(
        () => page.evaluate(root => {
          const state = window.__store.getState()
          return state.allWorktrees().find(row =>
            row.path.toLowerCase().replaceAll('\\', '/') === root.toLowerCase().replaceAll('\\', '/')
          )?.id
        }, repo),
        result => typeof result === 'string', 'The local checkout did not publish'
      )
      for (const id of ['chat-ui-here-corner-heading','codex-shared-settings-notice-heading']) {
        const card = page.locator(`[aria-labelledby="${id}"]`)
        if (await card.isVisible()) await card.getByRole('button', { name: /^(Dismiss|关闭)$/i }).click(waits)
      }
      const setup = button(/^(Dismiss setup scripts|关闭安装脚本)$/i)
      if (await setup.isVisible()) await setup.click(waits)
      if (workspacePortsFocused) return
      await openVault()
      if (workspaceHostContinuity) await verifyFixtureIndexes()
      await page.getByText(/^(All|全部)$/i, {exact:true}).last().click(waits)
      await chooseHost(/^(All hosts|所有主机)$/i)
      await query.fill(title)
      await assertRows()
      await dismissToasts()
      proofs.sameTitleAndProviderId = 2
    })
    if (workspacePortsFocused) {
      await observeWorkspace()
      return
    }
    if (!hostDirectory && !workspaceHostContinuity) {
    if (!baseline) {
      await step('i5-source-disappears', 'Withdraw the Studio fixture transcript and refresh the same search', async () => {
        const studioSource = fixtures.studioSource
        const backup = studioSource + '.aside'
        fs.renameSync(studioSource, backup)
        try {
          const results = await poll(
            () => rpc('aiVault.searchSessions', { query: title, filters: { agents: ['codex'] } }),
            response => response.kind === 'results' && (
              !response.hits.some(hit => hit.sessionId === sessionId) ||
              response.hits.some(hit => hit.sessionId === sessionId && hit.source.presence !== 'present')
            ),
            'The withdrawn Studio fixture was still reported as available'
          )
          const retained = results.hits.some(hit => hit.sessionId === sessionId)
          await refresh.click(waits)
          await refresh.waitFor(waits)
          await poll(() => refresh.isEnabled(), enabled => enabled, 'The search did not finish after withdrawal')
          await localRow.waitFor(waits)
          if (retained) {
            await studioRow.getByText(/Transcript is no longer available|Transcript availability could not be verified|会话记录不再可用|无法确认会话记录是否可用/).waitFor(waits)
            assert.equal(await studioRow.getByTestId('ai-vault-session-resume').isEnabled(), false)
          } else {
            await studioRow.waitFor({ state: 'hidden', ...waits })
          }
          proofs.sourceDisappears = { localStillAvailable: true, staleSourcePresent: retained }
        } finally {
          fs.renameSync(backup, studioSource)
          fs.utimesSync(studioSource, new Date(), new Date())
        }
      })
    }
    await step('i5-unreachable', 'Repeat the same search after Studio becomes unreachable', async () => {
      await studio.stop()
      await refresh.click(waits)
      const skipped = page.getByText(/^(Not searched|未搜索)[:：]/).first()
      await skipped.waitFor(waits)
      const message = await skipped.innerText()
      proofs.unreachable = {
        visibleRows: await namedRows.count(),
        usesHostName: message.includes(hostName),
        localRowNamed: await localRow.count() === 1,
        retry: await retry.count() === 1,
        loadMore: await page.getByRole('button', { name: /^(Load more matches|加载更多匹配项)$/i }).isVisible()
      }
      if (!baseline) {
        assert.equal(await namedRows.count(), 1)
        assert.equal(proofs.unreachable.usesHostName, true)
        assert.equal(proofs.unreachable.localRowNamed, true)
        assert.equal(proofs.unreachable.retry, true)
        assert.equal(proofs.unreachable.loadMore, false)
      }
    })
    if (baseline) {
      write('hosts.json', proofs)
      return
    }
    await step('i5-partial-empty', 'Search for a session that only the unavailable Studio host can return', async () => {
      await query.fill(remoteOnly)
      await retry.waitFor(waits)
      assert.equal(await rows.count(), 0)
      assert.match((await status()).join(' '), /Not searched|未搜索/i)
      assert.doesNotMatch((await status()).join(' '), /No matching sessions in the indexed history|索引历史记录中没有匹配的会话/)
      proofs.emptyIsPartial = true
    })
    await step('i5-retry-offline', 'Use Enter on the inline retry while Studio is still offline', async () => {
      await retry.press('Enter', waits)
      await page.waitForFunction(() =>
        document.activeElement?.getAttribute('placeholder') === 'Search sessions' ||
        document.activeElement?.getAttribute('placeholder') === '搜索会话', null, waits)
      await poll(() => retry.isEnabled(), enabled => enabled, 'The repeated offline search did not settle')
      assert.equal(await query.inputValue(), remoteOnly)
      assert.equal(await rows.count(), 0)
      proofs.offlineRetry = { queryPreserved: true, focusReturnedToSearch: true }
    })
    await step('i5-retry', 'Restart Studio and retry without changing the query or host scope', async () => {
      await studio.start(port, false)
      await poll(
        async () => rpc('status.get').catch(() => undefined),
        result => Boolean(result?.runtimeId), 'Studio pairing could not reconnect'
      )
      let recovery = 'explicit retry'
      await episode('retry-host', [
        ['retry the same search when the host has not already returned', async () => {
          try {
            await retry.press('Enter', { timeout: 2000 })
          } catch (error) {
            if (error.name !== 'TimeoutError') throw error
            await recoveredRow.waitFor(waits)
            recovery = 'automatic refresh'
          }
        }],
        ['wait for the match on Studio', () => recoveredRow.waitFor(waits)]
      ])
      assert.equal(await query.inputValue(), remoteOnly)
      assert.equal(await rows.filter({ hasText: hostName }).count(), 1)
      assert.equal(await retry.count(), 0)
      proofs.retry = { queryPreserved: true, restoredStudioResult: true, recovery }
    })
    await step('i5-compact', 'Inspect both owners and the host selector at 860×520 with reduced motion', async () => {
      await query.fill(title)
      await assertRows()
      await win.evaluate(w=>w.setContentSize(860,520))
      await page.emulateMedia({ reducedMotion: 'reduce' })
      await assertRows()
      for (const [row, label] of [[studioRow, hostName], [localRow, 'Local Windows']]) {
        const host = row.getByText(label, { exact: true })
        assert.equal(await host.evaluate(el => el.scrollWidth <= el.clientWidth + 1), true)
      }
    })
    }
    await step('i5-owning-chat', 'Read the Studio transcript and open it on its owning runtime', async () => {
      await win.evaluate(w=>w.setContentSize(1280,800))
      await studioRow.getByTestId('ai-vault-session-toggle-details').click(waits)
      await studioRow.getByText(remoteReply, { exact: true }).waitFor(waits)
      assert.equal(await studioRow.getByText(localReply, { exact: true }).count(), 0)
      proofs.studioPreview = true
      const expectedHost = `runtime:${encodeURIComponent(environmentId)}`
      const remoteTabs = () => page.evaluate(({ workspace, host }) => {
        const state = window.__store.getState()
        return (state.unifiedTabsByWorktree[workspace] ?? []).filter(
          tab => tab.contentType === 'agent-session' && tab.executionHostId === host
        ).map(({ id, entityId }) => ({ id, entityId }))
      }, { workspace: remoteWorkspace, host: expectedHost })
      await studioRow.getByTestId('ai-vault-session-more-actions').click(waits)
      await page.getByRole('menuitem', { name: /^(Resume in New Chat|在新聊天中恢复)$/i }).click(waits)
      const trust = button(/^(信任仓库|Trust repository)$/i)
      if (await trust.waitFor({ timeout: 3500 }).then(() => true, () => false)) {
        await trust.click(waits)
      }
      const chat = page.locator('[data-native-chat-root=true]:visible')
      const published = await poll(remoteTabs, tabs => tabs.length === 1, 'Studio did not publish the resumed chat')
      studioChat = published[0]
      if (workspaceExplorerContinuity && (await selectedChat()).id !== studioChat.id) {
        await studioRow.getByTestId('ai-vault-session-jump-original-pane').click(waits)
      }
      await poll(selectedChat, state => state.id === studioChat.id, 'Published Studio chat was not selected')
      await chat.getByText(remoteReply, { exact: true }).waitFor(waits)
      await dismissToasts()
      const active = await selectedChat()
      assert.equal(active.workspaceId, remoteWorkspace)
      assert.equal(active.activeHost, expectedHost)
      assert.equal(active.tabHost, expectedHost)
      assert.equal(active.contentType, 'agent-session')
      assert.equal(active.sessionId, studioChat.entityId)
      assert.equal(await chat.getByText(localReply, { exact: true }).count(), 0)
      for (const id of ['chat-ui-here-corner-heading','codex-shared-settings-notice-heading']) {
        const card = page.locator(`[aria-labelledby="${id}"]`)
        if (await card.isVisible()) await card.getByRole('button', { name: /^(Dismiss|关闭)$/i }).click(waits)
      }
      proofs.owningChat = { studioOwner: true, originalTranscript: true, initialSelection: true }
    })
    await step('i5-return-chat', 'Return from the local worktree to the same Studio chat', async () => {
      assert.ok(studioChat)
      const composer = page.locator('[data-native-chat-composer-scope] [contenteditable=true]:visible').first()
      await composer.fill(studioDraft, waits)
      const escaped = await page.evaluate(id => CSS.escape(id), localWorkspace)
      await page.locator(`[data-worktree-id=${escaped}] [data-worktree-card-surface]`).first().click(waits)
      assert.equal((await selectedChat()).workspaceId, localWorkspace)
      await assertRows()
      const jump = studioRow.getByTestId('ai-vault-session-jump-original-pane')
      await jump.waitFor(waits)
      assert.equal(await localRow.getByTestId('ai-vault-session-jump-original-pane').count(), 0)
      await episode('return-to-studio', [
        ['choose the Studio history row', () => jump.click(waits)],
        ['wait for the original chat input', () => composer.waitFor(waits)]
      ])
      const opened = await selectedChat()
      const expectedHost = `runtime:${encodeURIComponent(environmentId)}`
      assert.equal(opened.workspaceId, remoteWorkspace)
      assert.equal(opened.activeHost, expectedHost)
      assert.equal(opened.tabHost, expectedHost)
      assert.equal(opened.sessionId, studioChat.entityId)
      assert.equal(await composer.innerText(), studioDraft)
      await page.waitForFunction(() =>
        document.activeElement?.closest('[data-native-chat-composer-scope]') != null, null, waits)
      proofs.returnToStudio = { sameSession: true, inputFocused: true, draftPreserved: true }
    })
    write('hosts.json', proofs)
    if (workspaceHostContinuity) {
      await observeWorkspace()
    } else if (hostDirectory) {
      await observeDirectoryHosts({
        page, win, button, step, episode, write, waits, locale, title, hostName, localReply,
        remoteReply, localRow, assertHistoryRows: assertRows, selectedChat, poll, localWorkspace,
        remoteWorkspace, studioChat, environmentId,
        restartStudio: () => studio.start(port, false),
        stopStudio: studio.stop
      })
    }
  } finally {
    await studio.stop()
  }
}

module.exports = { seed, observe, prepareStudio, reservePort }
