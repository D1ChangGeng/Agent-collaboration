const assert = require('node:assert/strict')
const { createHash } = require('node:crypto')
const { createRequire } = require('node:module')
const fs = require('node:fs')
const path = require('node:path')
const { prepareConnection } = require('./physical-porpita-connection.cjs')

const targetId = 'spec-physical-ssh'
const targetName = 'Linux SSH project'
const directName = 'Linux acceptance service'
const repoId = 'spec-physical-project'
const branch = 'review-topic'

async function configure({ source, temporary, home, repo, env }) {
  const connection = prepareConnection(source, process.env.PORPITA_SPEC_PHYSICAL_FIXTURE)
  try {
    const ssh = await connection.forward(connection.fixture.sshPort)
    const pair = await connection.forward(connection.fixture.pairPort, connection.fixture.pairPort)
    const ready = JSON.parse(connection.remote('cat "$1/pair-ready.json"'))
    assert.equal(Number(new URL(ready.boundEndpoint).port), connection.fixture.pairPort)
    const accessLink = ready.pairing?.url
    if (typeof accessLink !== 'string' || !accessLink.startsWith('orca://pair?code=')) {
      throw new Error('The deployed runtime did not publish a valid access link')
    }
    const pairingCode = new URL(accessLink).searchParams.get('code')
    const key = connection.remote('cat "$1/$2/host_key.pub"', [connection.fixture.sshCell]).split(/\s+/)
    assert.equal(key[0], 'ssh-ed25519')
    const digest = createHash('sha256').update(Buffer.from(key[1], 'base64')).digest('base64')
    assert.equal('SHA256:' + digest.replace(/=+$/, ''), connection.fixture.fingerprint)
    fs.mkdirSync(path.join(home, '.ssh'), { recursive: true })
    fs.writeFileSync(path.join(home, '.ssh', 'known_hosts'), '[127.0.0.1]:' + ssh.port + ' ' + key.slice(0, 2).join(' ') + '\n')

    const bundle = path.join(temporary, 'physical-branch.bundle')
    connection.copy(connection.fixture.sshCell + '/branch.bundle', bundle)
    const runProcessSync = createRequire(path.join(source, 'package.json'))('@orca/process-host').runProcessSync
    const git = (...args) => {
      const result = runProcessSync({ program: 'git', args, cwd: repo, env, timeoutMs: 12000 })
      if (result.code !== 0) throw new Error('Fixture Git command failed: ' + result.stderr.trim())
      return result.stdout.trim()
    }
    git('fetch', '--quiet', '--no-tags', bundle, 'refs/heads/' + branch + ':refs/heads/' + branch)
    const head = connection.remote('cat "$1/$2/branch-head"', [connection.fixture.sshCell])
    assert.match(head, /^[a-f0-9]{40}$/)
    assert.equal(git('rev-parse', 'refs/heads/' + branch), head)
    env.ORCA_ORCAD_TEMPLATE_PATH = connection.fixture.templatePath
    const cache = path.join(temporary, 'profile', 'orcad-artifacts', 'node', 'archives')
    fs.mkdirSync(cache, { recursive: true })
    fs.copyFileSync(connection.fixture.nodeArchive, path.join(cache, 'node-v24.22.1-linux-x64.tar.gz'))
    ssh.setEnabled(false)
    return { connection, ssh, pair, git, head, ready, accessLink,
      redact: value => value.replaceAll(accessLink, '<access-link>').replaceAll(pairingCode, '<pairing-code>') }
  } catch (error) {
    await connection.close()
    throw error
  }
}

function seed(profilePath, { connection, ssh }) {
  const { fixture } = connection
  const data = JSON.parse(fs.readFileSync(profilePath, 'utf8'))
  data.sshTargets = [{
    id: targetId, label: targetName, host: '127.0.0.1', configHost: '127.0.0.1', port: ssh.port,
    username: fixture.sshUser, identityFile: fixture.identityFile, identitiesOnly: true,
    source: 'manual', generation: 1
  }]
  data.sshTargetGenerationCounter = 1
  data.repos = [{
    id: repoId, path: fixture.repoPath, displayName: 'Independent project', kind: 'git',
    badgeColor: '#737373', addedAt: 1, connectionId: targetId
  }]
  data.worktreeMeta = {
    [repoId + '::' + path.posix.dirname(fixture.repoPath) + '/review-worktree']: {
      hostId: 'ssh:' + targetId,
      instanceId: 'physical-legacy-checkout',
      displayName: 'Legacy checkout',
      comment: '',
      isArchived: false,
      isUnread: false,
      isPinned: false,
      sortOrder: 0,
      lastActivityAt: 1
    }
  }
  fs.writeFileSync(profilePath, JSON.stringify(data))
}

async function observe({ page, win, step, write, fixtures, state }) {
  const { connection, git, ssh, head, ready, accessLink } = fixtures
  const { fixture } = connection
  const testHome = path.posix.dirname(fixture.repoPath)
  const runOnSshHost = script => connection.remote(script, [fixture.sshCell])
  const wait = { timeout: 45000 }
  const proof = {}
  const back = () => page.getByRole('button', { name: /^Back to app$/i }).click()
  const dismissChatNotice = async () => {
    const stay = page.getByRole('button', { name: 'Stay in terminal', exact: true })
    if (await stay.isVisible()) await stay.click()
  }
  const oldWorktreeId = repoId + '::' + testHome + '/review-worktree'
  const row = page.locator('[data-worktree-id=' + JSON.stringify(oldWorktreeId) + ']').first()
  let paired
  let adopted

  await step('i72-physical-pairing', 'Pair Windows with the deployed Linux runtime', async () => {
    const serverVersion = ready.health?.buildVersion
    assert.equal(typeof serverVersion, 'string')
    assert.equal(serverVersion.split('+')[0], state.version)
    await win.evaluate(window => window.setContentSize(1000, 720))
    await dismissChatNotice()
    await page.getByRole('button', { name: 'Settings', exact: true }).click(wait)
    await page.getByRole('button', { name: 'Remote Orca Servers', exact: true }).click(wait)
    await page.getByRole('button', { name: /^Add server$/i }).click(wait)
    const dialog = page.getByRole('dialog', { name: /^Add server$/i })
    await dialog.getByLabel('Access link', { exact: true }).fill(accessLink)
    await dialog.getByRole('checkbox', { name: /I reach this address through an SSH tunnel/ }).check()
    await dialog.locator('#runtime-server-name').fill(directName)
    await dialog.locator('button[type=submit]').click()
    try {
      await dialog.waitFor({ ...wait, state: 'hidden' })
    } catch {
      throw new Error('Physical pairing dialogue stayed open: ' + (await dialog.innerText()).slice(0, 850))
    }
    await page.getByText(directName, { exact: true }).first().waitFor(wait)
    await dismissChatNotice()
    const server = await page.evaluate(async name => (await window.api.runtimeEnvironments.list())
      .find(item => item.name === name)?.id, directName)
    assert.ok(server)
    paired = await runtimeIdentity(page, server)
    assert.ok(paired && paired.runtimeId === ready.runtimeId)
    proof.pairing = { matchedLinuxRuntimeId: true, createdThroughVisibleSettings: true, serverVersion }
  })

  await step('i73-standalone-project-before-adoption', 'Open the preexisting independent SSH workspace and its recovery dialog', async () => {
    assert.ok(proof.pairing)
    await back()
    await row.hover(wait)
    await page.keyboard.press('Control+Shift+Backspace')
    const dialog = page.getByRole('dialog').filter({ hasText: 'Legacy checkout' })
    await dialog.waitFor(wait)
    assert.ok((await dialog.innerText()).includes(targetName))
    await dialog.getByRole('button', { name: 'Open SSH settings', exact: true }).waitFor(wait)
    proof.before = { sourceWasStandaloneSsh: true, offeredSettingsOnSameProject: true }
  })

  await step('i73-adopted-server', 'Connect the same SSH target and adopt the existing project', async () => {
    assert.ok(proof.before)
    await page.getByRole('button', { name: 'Open SSH settings', exact: true }).press('Enter', wait)
    await dismissChatNotice()
    const card = page.locator('[data-ssh-target-card][data-ssh-target-label=' + JSON.stringify(targetName) + ']')
    await card.hover(wait)
    ssh.setEnabled(true)
    await card.getByRole('button', { name: /^Connect(?: |$)/ }).click()
    const disconnect = card.getByRole('button', { name: /^Disconnect(?: |$)/ })
    const failed = card.getByRole('button', { name: 'Open plain SSH terminal', exact: true })
    await disconnect.or(failed).first().waitFor({ timeout: 125000 })
    assert.ok(await disconnect.isVisible(), 'Managed SSH did not connect. ' + (await card.innerText()).slice(0, 700))
    const managed = await page.waitForFunction(async targetId => (await window.api.runtimeEnvironments.list())
      .find(server => server.orcadDeployment?.sshTargetId === targetId)?.id, targetId, { timeout: 125000, polling: 250 })
    const id = await managed.jsonValue()
    await managed.dispose()
    adopted = await page.evaluate(async ({ id, repoPath }) => {
      const result = await window.api.runtimeEnvironments.call({ selector: id, method: 'repo.list' })
      const status = await window.api.runtimeEnvironments.call({ selector: id, method: 'status.get' })
      return {
        id, runtimeId: status.ok && status.result.runtimeId,
        matches: result.ok && (result.result.repos ?? []).filter(item => item.path === repoPath)
      }
    }, { id, repoPath: fixture.repoPath })
    assert.ok(adopted.runtimeId && adopted.runtimeId !== paired.runtimeId)
    assert.equal(adopted.matches.length, 1)
    assert.equal(adopted.matches[0].id, repoId)
    proof.adoption = { originalProjectIdAndPath: true, separateManagedRuntime: true }
  })

  const review = page.getByRole('dialog', { name: 'Review kept branches', exact: true })
  const branchRow = review.locator('li').filter({ hasText: branch })
  const checkbox = branchRow.getByRole('checkbox')
  const check = branchRow.getByRole('button', { name: 'Check checkout for ' + branch, exact: true })
  const reconnect = branchRow.getByRole('button', { name: 'Reconnect and check checkout for ' + branch, exact: true })
  const force = review.getByRole('button', { name: 'Force Delete 1 Branch', exact: true })
  const moved = testHome + '/Checkout Moved'
  const remoteHead = () => runOnSshHost('git -C "$1/$2/home/project" rev-parse --verify --quiet refs/heads/review-topic || true')
  const localHead = () => git('rev-parse', 'refs/heads/' + branch)

  await step('i74-adopted-branch-checkout', 'Remove the adopted workspace and check the retained ref on its new owner', async () => {
    assert.ok(proof.adoption)
    await back()
    await row.hover(wait)
    assert.equal(remoteHead(), head)
    await page.keyboard.press('Control+Shift+Backspace')
    const removal = page.getByRole('dialog', { name: 'Delete Workspace', exact: true })
    await removal.getByRole('button', { name: 'Delete Workspace', exact: true }).press('Enter', wait)
    const entry = page.getByRole('button', { name: 'Review 1 Branch', exact: true })
    await entry.waitFor(wait)
    runOnSshHost([
      'test ! -e "$1/$2/home/review-worktree"',
      'git -C "$1/$2/home/project" worktree add -q "$1/$2/home/Checkout Before" review-topic',
      'git -C "$1/$2/home/project" worktree move "$1/$2/home/Checkout Before" "$1/$2/home/Checkout Moved"'
    ].join('\n'))
    await entry.press('Enter', wait)
    await check.press('Enter', wait)
    await branchRow.getByText('Checkout path', { exact: true }).waitFor(wait)
    assert.equal(await branchRow.locator('code').textContent(), moved)
    assert.equal(await checkbox.getAttribute('aria-checked'), 'false')
    assert.equal(remoteHead(), head)
    assert.equal(localHead(), head)
    proof.checkout = { actualMovedLinuxPath: true, retainedBothRefs: true, initialZeroSelection: true }
  })

  await step('i74-disconnected-branch-review', 'Drop the SSH transport while the adopted branch is selected', async () => {
    assert.ok(proof.checkout)
    await checkbox.press('Space', wait)
    assert.equal(await checkbox.getAttribute('aria-checked'), 'true')
    ssh.setEnabled(false)
    await check.press('Enter', wait)
    await branchRow.getByText('Host unavailable', { exact: true }).waitFor(wait)
    assert.equal(await checkbox.getAttribute('aria-checked'), 'true')
    assert.ok(await force.isDisabled())
    assert.equal(await branchRow.locator('code').textContent(), moved)
    assert.equal(await reconnect.evaluate(button => button === document.activeElement), true)
    assert.deepEqual(await runtimeIdentity(page, paired.environmentId), paired)
    proof.outage = { cutRealSshForward: true, retainedPathAndSelection: true, blockedSubmit: true, originalRowFocus: true, directPairingStillReachable: true }
  })

  await step('i74-reconnected-original-row', 'Release the checkout and reconnect from the original review row', async () => {
    assert.ok(proof.outage)
    runOnSshHost('git -C "$1/$2/home/Checkout Moved" switch --detach HEAD')
    ssh.setEnabled(true)
    await reconnect.press('Enter', wait)
    await branchRow.getByText('No checkout', { exact: true }).waitFor(wait)
    assert.ok(await force.isEnabled())
    assert.equal(await checkbox.getAttribute('aria-checked'), 'true')
    assert.equal(remoteHead(), head)
    assert.equal((await runtimeIdentity(page, adopted.id)).runtimeId, adopted.runtimeId)
    proof.recovery = { readFreshGitAfterReconnect: true, preservedSelectionAndRef: true }
  })

  await step('i74-refusal-and-retry', 'Review the real refusal after the branch is checked out again', async () => {
    assert.ok(proof.recovery)
    runOnSshHost('git -C "$1/$2/home/Checkout Moved" switch review-topic')
    await force.press('Enter', wait)
    await page.getByRole('button', { name: 'Review failed branches', exact: true }).press('Enter', wait)
    await review.waitFor(wait)
    assert.equal(await checkbox.getAttribute('aria-checked'), 'false')
    assert.equal(await branchRow.locator('code').textContent(), moved)
    assert.equal(remoteHead(), head)
    proof.refusal = { gitRecheckedBeforeDelete: true, startedRetryAtZeroSelection: true }
  })

  await step('i74-explicit-retry-on-linux', 'Submit a fresh selection on Linux after releasing the branch again', async () => {
    assert.ok(proof.refusal)
    runOnSshHost('git -C "$1/$2/home/Checkout Moved" switch --detach HEAD')
    await check.press('Enter', wait)
    await branchRow.getByText('No checkout', { exact: true }).waitFor(wait)
    await checkbox.press('Space', wait)
    await force.press('Enter', wait)
    await review.waitFor({ ...wait, state: 'hidden' })
    await page.getByText('Git branches deleted: 1', { exact: true }).waitFor(wait)
    await page.getByRole('button', { name: 'Review failed branches', exact: true }).waitFor({ ...wait, state: 'hidden' })
    assert.equal(await page.getByText(/review-topic:.*is checked out in another worktree/).isVisible(), false)
    assert.equal(remoteHead(), '')
    assert.equal(localHead(), head)
    proof.result = { confirmedDeleteOnLinux: true, pairedWindowsRefKept: true, clearedPreviousRefusalAndRetry: true }
  })
  ssh.setEnabled(true)
  assert.equal(await win.evaluate(window => !window.isVisible() && !window.isFocused()), true)
  write('physical-porpita-checks.json', {
    client: 'Windows x64',
    clientVersion: state.version,
    electronVersion: state.electronVersion,
    server: 'physical Linux x86_64',
    transport: 'OpenSSH forwarding',
    ...proof
  })
}

function runtimeIdentity(page, environmentId) {
  return page.evaluate(async environmentId => {
    const status = await window.api.runtimeEnvironments.call({ selector: environmentId, method: 'status.get' })
    return status.ok && { runtimeId: status.result.runtimeId, environmentId }
  }, environmentId)
}

module.exports = { configure, seed, observe }
