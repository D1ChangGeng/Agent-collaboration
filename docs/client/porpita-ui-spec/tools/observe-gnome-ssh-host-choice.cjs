const assert = require('node:assert/strict')
const { execFileSync, spawn } = require('node:child_process')
const { createRequire } = require('node:module')
const fs = require('node:fs')
const path = require('node:path')
const { setTimeout: delay } = require('node:timers/promises')

const [source, executable, template, archive, mode] = process.argv.slice(2)
const stage = fs.realpathSync(process.env.PORPITA_NATIVE_STAGE)
const run = fs.realpathSync(process.env.PORPITA_NATIVE_RUN)
assert.equal(path.dirname(run), stage)
assert.equal(process.env.HOME, path.join(run, 'home'))
assert.equal(process.env.PORPITA_NATIVE_COMPOSITOR, 'gnome')
assert.equal(process.env.DISPLAY, undefined)
assert.ok(['baseline', 'verify', 'config-baseline', 'config-verify'].includes(mode))

const { _electron } = createRequire(path.join(source, 'package.json'))('playwright')
const cell = path.join(stage, 'ssh-cell')
const targets = JSON.parse(fs.readFileSync(path.join(cell, 'targets.json')))
const profile = path.join(run, 'profile')
const output = path.join(run, 'evidence')
const voiceLog = path.join(run, 'orca-private.log')
const steps = []
const keys = []
const proof = { mode, steps }
const wait = { timeout: 20000 }
const configReplay = mode.startsWith('config-')
const endpoint = target => target.username + '@' +
  (target.host.includes(':') && mode !== 'config-baseline' ? '[' + target.host + ']' : target.host) + ':' + target.port
const targetId = target => path.basename(stage) + '-' + path.basename(run) + '-' + target.name

function save(file, value) {
  fs.writeFileSync(path.join(output, file), JSON.stringify(value, null, 2) + '\n')
}

function command(program, args) {
  return execFileSync(program, args, { encoding: 'utf8', timeout: 15000 }).trim()
}

function mutter(operation, value) {
  command('/usr/bin/python3', [path.join(stage, 'gnome-wayland-control.py'), operation, value])
}

async function key(combination) {
  mutter('key', combination)
  keys.push(combination)
  await delay(100)
}

async function tabTo(locator) {
  await locator.waitFor(wait)
  for (let n = 0; n < 80; n++) {
    if (await locator.evaluate(node => node === document.activeElement)) return
    await key('Tab')
  }
  throw new Error('Tab did not reach ' + await locator.ariaSnapshot())
}

async function choose(locator) {
  await tabTo(locator)
  await key('Return')
}

function speechSince(offset) {
  return fs.readFileSync(voiceLog).subarray(offset).toString('utf8').split('\n')
    .map(line => line.split("SPEECH OUTPUT: '")[1]?.split(/'(?=\s*(?:\{|None|$))/)[0])
    .filter(Boolean)
}

function identitySpoken(utterances, target) {
  const normalize = text => text.toLowerCase().replace(/\b(at|dot|point|colon|dash|hyphen)\b/g, '')
    .replace(/[^a-z0-9]/g, '')
  const heard = normalize(utterances.join(' '))
  return heard.includes(normalize(target.label)) && heard.includes(normalize(endpoint(target)))
}

function connectionCounts(pattern) {
  return Object.fromEntries(targets.map(target => [
    target.name,
    (fs.readFileSync(path.join(cell, target.name, 'server.log'), 'utf8').match(pattern) ?? []).length
  ]))
}

function prepareProfile() {
  fs.mkdirSync(profile)
  const ssh = path.join(process.env.HOME, '.ssh')
  fs.mkdirSync(ssh, { mode: 0o700 })
  if (!configReplay) {
    const hostKey = fs.readFileSync(path.join(cell, 'host_key.pub'), 'utf8').trim().split(/\s+/).slice(0, 2).join(' ')
    fs.writeFileSync(path.join(ssh, 'known_hosts'), targets.map(target =>
      '[' + target.host + ']:' + target.port + ' ' + hostKey).join('\n') + '\n', { mode: 0o600 })
  }
  const archives = path.join(profile, 'orcad-artifacts/node/archives')
  fs.mkdirSync(archives, { recursive: true })
  fs.copyFileSync(archive, path.join(archives, 'node-v24.22.1-linux-x64.tar.gz'))
  fs.writeFileSync(path.join(profile, 'orca-data.json'), JSON.stringify({
    settings: { telemetry: { optedIn: false }, uiLanguage: 'en', theme: 'light', agentDefaultSurface: 'terminal' },
    ui: { contextualToursAutoEligible: false, browserImportHintHidden: true },
    onboarding: { flowVersion: 4, closedAt: 1, outcome: 'completed', lastCompletedStep: 5 },
    sshTargets: configReplay ? [] : targets.map((target, i) => ({
      id: targetId(target), label: target.label, host: target.host, configHost: target.host,
      username: target.username, port: target.port, identityFile: path.join(cell, 'client_key'),
      identitiesOnly: true, source: 'manual', generation: i + 1
    })), sshTargetGenerationCounter: configReplay ? 0 : targets.length
  }))
}

function row(page, target) {
  return page.locator('[data-ssh-target-label=' + JSON.stringify(target.label) + ']')
}

function primary(page, target) {
  return row(page, target).getByRole('button', { name: /^(Connect|Connecting|Disconnect)( |$)/ })
}

async function measure(page, target) {
  return row(page, target).evaluate((card, strings) => {
    const text = value => {
      const span = [...card.querySelectorAll('span')].find(node =>
        node.childElementCount === 0 && node.textContent === value && node.getClientRects().length
      )
      if (!span) return { full: false, lines: 0 }
      const range = document.createRange()
      range.selectNodeContents(span)
      const fragments = [...range.getClientRects()]
      let left = Math.max(0, card.getBoundingClientRect().left)
      let right = Math.min(innerWidth, card.getBoundingClientRect().right)
      for (let node = span; node && node !== card; node = node.parentElement) {
        if (['hidden', 'clip', 'scroll', 'auto'].includes(getComputedStyle(node).overflowX)) {
          const box = node.getBoundingClientRect()
          left = Math.max(left, box.left)
          right = Math.min(right, box.right)
        }
      }
      const full = fragments.length > 0 && fragments.every(rect => rect.left >= left - 1 && rect.right <= right + 1)
      return { full, lines: fragments.length }
    }
    return { label: text(strings.label), endpoint: text(strings.endpoint),
      selected: card.dataset.selected === 'true', rowWidth: card.clientWidth }
  }, { label: target.label, endpoint: endpoint(target) })
}

async function capture(page, id, detail) {
  const imageFile = id + '.png'
  const record = { id, imageFile, imageMethod: 'Mutter RecordMonitor / PipeWire',
    viewport: await page.evaluate(() => [innerWidth, innerHeight]),
    focused: await page.evaluate(() => document.activeElement?.textContent?.trim()),
    rows: Object.fromEntries(await Promise.all(targets.map(async target => [target.name, await measure(page, target)]))),
    ...detail }
  mutter('screenshot', path.join(output, imageFile))
  save(id + '.json', record)
  steps.push(id)
  save('run.json', proof)
  process.stdout.write(id + '\n')
}

async function audio(file, action) {
  const recorder = spawn('parecord', ['--device=porpita-validation.monitor', '--file-format=wav',
    '--rate=16000', '--channels=1', '--format=s16le', path.join(output, file)], { stdio: 'ignore' })
  const stopped = new Promise((resolve, reject) => {
    recorder.once('error', reject)
    recorder.once('close', code => resolve(code === 0))
  })
  try {
    await delay(180)
    await action()
    await delay(800)
  } finally {
    recorder.kill('SIGINT')
    assert.equal(await stopped, true, 'System speech recorder did not close')
  }
}

async function runChecks(page) {
  const [atlas, beacon, cedar] = targets
  const before = connectionCounts(/Accepted publickey/g)
  const tcpBefore = connectionCounts(/Connection from /g)
  await choose(page.getByRole('button', { name: 'Settings', exact: true }))
  await choose(page.getByRole('button', { name: 'SSH Hosts', exact: true }))
  await row(page, cedar).waitFor(wait)
  await capture(page, mode === 'baseline' ? 'i84-baseline-wide' : 'i84-wide', {})
  await key('super+Left')
  await page.waitForFunction(() => innerWidth === 720, null, wait)

  await audio(mode === 'baseline' ? 'baseline-focus.wav' : 'host-focus.wav', async () => {
    for (const target of targets) {
      const offset = fs.statSync(voiceLog).size
      await tabTo(primary(page, target))
      await delay(mode === 'baseline' ? 2100 : 6700)
      const utterances = speechSince(offset)
      const aria = await primary(page, target).ariaSnapshot()
      proof.primarySpeech ??= {}
      proof.primarySpeech[target.name] = utterances.some(text => /^Connect\b/i.test(text) && identitySpoken([text], target))
      await capture(page, (mode === 'baseline' ? 'i84-baseline-' : 'i85-focus-') + target.name, {
        target: target.label, endpoint: endpoint(target), keys: keys.slice(-8), aria, utterances
      })
    }
  })

  if (mode === 'baseline') {
    assert.equal(Object.values(proof.primarySpeech).every(value => value === false), true)
    assert.deepEqual(connectionCounts(/Accepted publickey/g), before)
    return
  }

  for (const target of targets) {
    const identity = await measure(page, target)
    assert.equal(identity.label.full && identity.endpoint.full, true, target.label)
    assert.equal(proof.primarySpeech[target.name], true, 'Incomplete spoken Connect identity for ' + target.name)
  }
  await capture(page, 'i84-tiled', {})
  const selectAtlas = row(page, atlas).getByRole('checkbox')
  const selectionOffset = fs.statSync(voiceLog).size
  await tabTo(selectAtlas)
  await delay(1800)
  const selectionSpeech = speechSince(selectionOffset)
  proof.checkboxIdentity = selectionSpeech.some(text => /^Select\b/i.test(text) && identitySpoken([text], atlas))
  assert.equal(proof.checkboxIdentity, true, 'Incomplete spoken checkbox identity')
  await key('space')
  assert.equal(await selectAtlas.getAttribute('aria-checked'), 'true')
  assert.equal(await row(page, beacon).getByRole('checkbox').getAttribute('aria-checked'), 'false')
  assert.deepEqual(connectionCounts(/Accepted publickey/g), before)
  assert.deepEqual(connectionCounts(/Connection from /g), tcpBefore)
  await capture(page, 'i85-bulk-selection', { utterances: selectionSpeech })

  await tabTo(primary(page, beacon))
  await key('shift+Tab')
  assert.equal(await row(page, beacon).getByRole('checkbox').evaluate(node => node === document.activeElement), true)
  await key('Tab')
  assert.equal(await primary(page, beacon).evaluate(node => node === document.activeElement), true)
  const focused = await primary(page, beacon).elementHandle()
  const checkpoint = keys.length
  const offset = fs.statSync(voiceLog).size
  await audio('connection-confirmation.wav', async () => {
    await key('Return')
    await row(page, beacon).getByRole('button', { name: /^Disconnect( |$)/ }).waitFor({ timeout: 150000 })
    await delay(6700)
  })
  const after = connectionCounts(/Accepted publickey/g)
  const tcpAfter = connectionCounts(/Connection from /g)
  assert.ok(after.beacon > before.beacon, 'No real authentication at the selected endpoint')
  assert.equal(after.atlas, before.atlas)
  assert.equal(after.cedar, before.cedar)
  assert.ok(tcpAfter.beacon > tcpBefore.beacon)
  assert.equal(tcpAfter.atlas, tcpBefore.atlas)
  assert.equal(tcpAfter.cedar, tcpBefore.cedar)
  assert.equal(await selectAtlas.getAttribute('aria-checked'), 'true')
  const focusRetained = await focused.evaluate(node => node === document.activeElement)
  assert.equal(focusRetained, true)
  const utterances = speechSince(offset)
  const connectedStatus = utterances.find(text => /^Connected\b/i.test(text) && identitySpoken([text], beacon))
  proof.connection = { target: beacon.label, endpoint: endpoint(beacon), before, after, tcpBefore, tcpAfter, focusRetained,
    keys: keys.slice(checkpoint), utterances, connectedStatus: connectedStatus ?? null }
  assert.deepEqual(proof.connection.keys, ['Return'])
  await capture(page, 'i86-connected', { connection: proof.connection })
  assert.ok(connectedStatus, 'Orca did not speak the connected status with the full target identity')
  await key('Return')
  await row(page, beacon).getByRole('button', { name: /^Connect( |$)/ }).waitFor(wait)
  assert.equal(await focused.evaluate(node => node === document.activeElement), true)
  await focused.dispose()
  await capture(page, 'i86-disconnected', {})
}

function writeConfig() {
  const ssh = path.join(process.env.HOME, '.ssh')
  const config = path.join(ssh, 'config')
  const lines = targets.flatMap(target => [
    'Host ' + target.label, '  HostName ' + target.host, '  Port ' + target.port, ''
  ])
  lines.push(
    'Host porpita-config-validation-workspace-*', '  User ' + targets[0].username,
    '  IdentityFile ' + path.join(cell, 'client_key'), '  IdentitiesOnly yes',
    '  StrictHostKeyChecking ask', '  UserKnownHostsFile ' + path.join(ssh, 'known_hosts'),
    '  GlobalKnownHostsFile ' + path.join(ssh, 'global_known_hosts'), ''
  )
  fs.writeFileSync(config, lines.join('\n'), { mode: 0o600 })
  proof.resolvedConfig = targets.map(target => {
    const settings = command('ssh', ['-G', '-F', config, target.label])
    return { alias: target.label, ...Object.fromEntries(settings.split('\n')
      .map(line => line.split(' ', 2))
      .filter(([key]) => ['hostname', 'port', 'user', 'stricthostkeychecking'].includes(key))) }
  })
}

function storedKeys() {
  const file = path.join(profile, 'profiles/local-default/ssh-host-keys.json')
  if (!fs.existsSync(file)) return []
  return JSON.parse(fs.readFileSync(file)).hostKeys.map(({ host, port, fingerprint }) => ({ host, port, fingerprint }))
}

async function runConfigChecks(page) {
  const [, beacon] = targets
  const authCounts = () => connectionCounts(/Accepted publickey/g)
  const before = authCounts()
  assert.deepEqual(storedKeys(), [])
  await choose(page.getByRole('button', { name: 'Settings', exact: true }))
  await choose(page.getByRole('button', { name: 'SSH Hosts', exact: true }))
  assert.equal((await page.evaluate(() => window.api.ssh.listTargets())).length, 0)
  await key('super+Left')
  await page.waitForFunction(() => innerWidth === 720, null, wait)
  writeConfig()
  await choose(page.getByRole('button', { name: 'Sync ~/.ssh/config', exact: true }))
  await row(page, targets[2]).waitFor(wait)
  proof.imported = await page.evaluate(async () => (await window.api.ssh.listTargets())
    .map(({ label, host, port, username, source }) => ({ label, host, port, username, source })))
  assert.equal(proof.imported.length, 3)
  assert.ok(proof.imported.every(target => target.source === 'ssh-config'))
  await capture(page, mode === 'config-baseline' ? 'i87-baseline-import' : 'i87-import', {
    imported: proof.imported, resolvedConfig: proof.resolvedConfig
  })

  await audio('config-host-focus.wav', async () => {
    proof.configSpeech = {}
    for (const target of targets) {
      const offset = fs.statSync(voiceLog).size
      const control = primary(page, target)
      await tabTo(control)
      await delay(mode === 'config-baseline' ? 1900 : 6400)
      const utterances = speechSince(offset)
      const aria = await control.ariaSnapshot()
      proof.configSpeech[target.name] = utterances.find(text => /^Connect\b/i.test(text) && identitySpoken([text], target)) ?? null
      await capture(page, (mode === 'config-baseline' ? 'i88-baseline-' : 'i88-focus-') + target.name, {
        target: target.label, endpoint: endpoint(target), aria, utterances
      })
    }
  })

  await tabTo(primary(page, beacon))
  const focused = await primary(page, beacon).elementHandle()
  const trust = page.getByRole('dialog', { name: 'Trust SSH host key', exact: true })
  const disconnect = row(page, beacon).getByRole('button', { name: /^Disconnect( |$)/ })
  if (mode === 'config-baseline') {
    await key('Return')
    await disconnect.or(trust).waitFor({ timeout: 150000 })
    await delay(250)
    proof.firstConnect = { prompt: await trust.isVisible(), authentication: authCounts(), trusted: storedKeys() }
    await capture(page, 'i89-baseline-first-connect', { firstConnect: proof.firstConnect })
    if (await disconnect.isVisible()) await key('Return')
    await focused.dispose()
    return
  }

  for (const target of targets) {
    assert.deepEqual(proof.imported.find(entry => entry.label === target.label), {
      label: target.label, host: target.host, port: target.port, username: target.username, source: 'ssh-config'
    })
    const identity = await measure(page, target)
    assert.ok(identity.label.full && identity.endpoint.full, target.label)
    assert.ok(proof.configSpeech[target.name], 'Incomplete spoken target: ' + target.name)
  }

  await key('Return')
  await trust.waitFor(wait)
  const cancel = trust.getByRole('button', { name: 'Cancel', exact: true })
  await page.waitForFunction(() => document.activeElement?.textContent?.trim() === 'Cancel', null, wait)
  assert.ok(await cancel.evaluate(node => node === document.activeElement))
  assert.ok((await trust.innerText()).includes(beacon.fingerprint))
  assert.deepEqual(authCounts(), before)
  assert.deepEqual(storedKeys(), [])
  await capture(page, 'i89-first-prompt', { dialog: await trust.ariaSnapshot(), stored: storedKeys(), authentication: authCounts() })
  await key('Escape')
  await trust.waitFor({ ...wait, state: 'hidden' })
  await row(page, beacon).getByRole('button', { name: /^Connect( |$)/ }).waitFor(wait)
  await delay(350)
  assert.ok(await focused.evaluate(node => node === document.activeElement), 'Cancel lost the SSH row focus')
  assert.deepEqual(authCounts(), before)
  assert.deepEqual(storedKeys(), [])
  await capture(page, 'i89-cancel', { stored: storedKeys(), authentication: authCounts() })

  const offset = fs.statSync(voiceLog).size
  await audio('host-key-confirmation.wav', async () => {
    await key('Return')
    await trust.waitFor(wait)
    const approve = trust.getByRole('button', { name: /^Trust and connect( |$)/i })
    await tabTo(approve)
    await delay(6500)
    const utterances = speechSince(offset)
    proof.promptSpeech = utterances.find(text => /^Trust and connect\b/i.test(text) && identitySpoken([text], beacon)) ?? null
    assert.ok(proof.promptSpeech, 'Orca did not read the full target on the trust action')
    await capture(page, 'i89-trust-action', { dialog: await trust.ariaSnapshot(), utterances })
    assert.deepEqual(authCounts(), before)
    await key('Return')
    await trust.waitFor({ ...wait, state: 'hidden' })
    await disconnect.waitFor({ timeout: 150000 })
    await delay(6400)
  })
  const after = authCounts()
  assert.equal(after.atlas, before.atlas)
  assert.equal(after.cedar, before.cedar)
  assert.ok(after.beacon > before.beacon)
  const trusted = storedKeys()
  assert.deepEqual(trusted, [{ host: beacon.host, port: beacon.port, fingerprint: beacon.fingerprint }])
  assert.ok(await focused.evaluate(node => node === document.activeElement), 'Approve lost the SSH row focus')
  proof.connection = { before, after, trusted, utterances: speechSince(offset) }
  await capture(page, 'i89-connected', { connection: proof.connection })
  const connect = row(page, beacon).getByRole('button', { name: /^Connect( |$)/ })
  await key('Return')
  await connect.waitFor(wait)
  await key('Return')
  await disconnect.or(trust).waitFor({ timeout: 150000 })
  assert.equal(await trust.isVisible(), false)
  assert.ok(await disconnect.isVisible())
  assert.deepEqual(storedKeys(), trusted)
  assert.ok(authCounts().beacon > after.beacon)
  await capture(page, 'i89-reconnected', { authentication: authCounts(), trusted: storedKeys() })
  await key('Return')
  await connect.waitFor(wait)
  await focused.dispose()
}

async function main() {
  fs.mkdirSync(output)
  prepareProfile()
  proof.sourceCommit = command('git', ['-C', source, 'rev-parse', 'HEAD'])
  proof.compositor = JSON.parse(fs.readFileSync(path.join(run, 'compositor.json')))
  proof.reader = fs.readFileSync(path.join(run, 'orca-version.txt'), 'utf8').trim()
  const env = { ...process.env, ORCA_E2E_USER_DATA_DIR: profile,
    ORCA_E2E_HOME_DIR: process.env.HOME, ORCA_ORCAD_TEMPLATE_PATH: template }
  for (const name of ['ORCA_BACKGROUND_LAUNCH', 'ORCA_E2E_HEADFUL', 'ORCA_E2E_HEADLESS']) delete env[name]
  const app = await _electron.launch({ executablePath: executable, cwd: run, env, timeout: 35000,
    args: ['--ozone-platform=wayland', '--no-sandbox', '--disable-gpu'] })
  try {
    const page = await app.firstWindow({ timeout: 40000 })
    const window = await app.browserWindow(page)
    await page.getByRole('button', { name: 'Settings', exact: true }).waitFor(wait)
    for (let n = 0; n < 130 && !await window.evaluate(win => win.isVisible()); n++) await delay(150)
    assert.equal(await window.evaluate(win => win.isVisible()), true)
    if (!await window.evaluate(win => win.isFocused())) {
      await key('Escape')
      if (!await window.evaluate(win => win.isFocused())) await key('super+Tab')
    }
    assert.equal(await window.evaluate(win => win.isFocused()), true)
    await key('super+Up')
    await page.waitForFunction(() => innerWidth === 1440, null, wait)
    proof.product = await app.evaluate(({ app }) => ({ version: app.getVersion(), electron: process.versions.electron }))
    if (configReplay) await runConfigChecks(page)
    else await runChecks(page)
    proof.completed = true
    save('run.json', proof)
  } catch (error) {
    save('run.json', { ...proof, failure: error.message })
    process.stderr.write(error.message + '\n')
    process.exitCode = 1
  } finally {
    await app.close()
  }
}

main().catch(error => {
  save('run.json', { ...proof, failure: error.message })
  process.stderr.write(error.message + '\n')
  process.exitCode = 1
})
