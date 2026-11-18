const assert = require('node:assert/strict')
const { execFileSync, spawn } = require('node:child_process')
const { createRequire } = require('node:module')
const fs = require('node:fs')
const net = require('node:net')
const path = require('node:path')
const { setTimeout: delay } = require('node:timers/promises')

const [source, executable, appArgument, template, archive] = process.argv.slice(2)
const stage = fs.realpathSync(process.env.PORPITA_NATIVE_STAGE)
const run = fs.realpathSync(process.env.PORPITA_NATIVE_RUN)
assert.equal(process.platform, 'linux')
assert.equal(path.dirname(run), stage)
assert.equal(process.env.HOME, path.join(run, 'home'))
const wayland = process.env.PORPITA_NATIVE_DISPLAY === 'wayland'
const gnome = process.env.PORPITA_NATIVE_COMPOSITOR === 'gnome'
const verifyWayland = wayland && process.env.PORPITA_NATIVE_WAYLAND_MODE === 'verify'
if (wayland) {
  assert.equal(process.env.XDG_SESSION_TYPE, 'wayland')
  assert.equal(process.env.DISPLAY, undefined)
  assert.match(process.env.WAYLAND_DISPLAY, /^wayland-\d+$/)
  assert.ok(fs.statSync(path.join(run, 'runtime', process.env.WAYLAND_DISPLAY)).isSocket())
  const compositorSocket = gnome ? path.join(run, 'runtime', 'mutter-observer.sock') : process.env.SWAYSOCK
  assert.ok(fs.realpathSync(compositorSocket).startsWith(path.join(run, 'runtime') + path.sep))
} else {
  assert.match(process.env.DISPLAY, /^:\d+$/)
}
assert.equal(fs.readFileSync(path.join(run, 'display'), 'utf8').trim(),
  wayland ? process.env.WAYLAND_DISPLAY : process.env.DISPLAY)
const { _electron } = createRequire(path.join(source, 'package.json'))('playwright')
const cellName = process.env.PORPITA_NATIVE_FIXTURE_CELL ?? 'ssh-cell'
assert.match(cellName, /^ssh-cell(?:-[a-z0-9-]+)?$/)
const cell = path.join(stage, cellName)
const fixture = JSON.parse(fs.readFileSync(path.join(cell, 'fixture.json')))
const peer = JSON.parse(fs.readFileSync(path.join(stage, 'peer-ready.json')))
const repo = path.join(cell, 'home/project')
const worktree = path.join(cell, 'home/review-worktree')
const moved = path.join(cell, 'home/Checkout Moved')
const profile = path.join(run, 'profile')
const output = path.join(run, 'evidence')
const orcaLog = path.join(run, 'orca-private.log')
const fixtureScope = gnome ? '-' + path.basename(stage).split('.').at(-1).toLowerCase() + '-' + path.basename(run) : ''
const targetId = 'spec-independent-ssh' + fixtureScope
const targetName = 'Linux SSH project'
const repoId = 'spec-independent-project' + fixtureScope
const branch = 'review-topic'
const keys = []
const steps = []
const proof = {}
const normalWait = { timeout: 20000 }
let speechOffset = fs.statSync(orcaLog).size

function redact(text) {
  return String(text).replaceAll(peer.accessLink, '<pairing link>').replace(/orca:\/\/[^\s"']+/g, '<pairing link>')
}

function save(name, data) {
  fs.writeFileSync(path.join(output, name), JSON.stringify(data, null, 2) + '\n')
}

function shell(program, args, options = {}) {
  const stdout = execFileSync(program, args, { timeout: 15000, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], ...options })
  return typeof stdout === 'string' ? stdout.trim() : ''
}

function git(directory, ...args) {
  return shell('git', ['-C', directory, ...args])
}

function linuxHead() {
  try {
    return git(repo, 'rev-parse', '--verify', '--quiet', 'refs/heads/' + branch)
  } catch (error) {
    if (error.status === 1) return null
    throw error
  }
}

function mutter(...args) {
  return shell('/usr/bin/python3', [path.join(stage, 'gnome-wayland-control.py'), ...args])
}

async function key(combination) {
  if (gnome) {
    mutter('key', combination)
  } else if (wayland) {
    shell(path.join(stage, 'wayland-evdev-key'), combination.split('+'))
  } else {
    shell('xdotool', ['key', '--clearmodifiers', combination])
  }
  keys.push(combination)
  await delay(95)
}

async function tabTo(locator, limit = 100) {
  await locator.waitFor(normalWait)
  for (let i = 0; i <= limit; i++) {
    if (await locator.evaluate(node => node === document.activeElement)) return
    await key('Tab')
  }
  const requested = (await locator.getAttribute('aria-label') ?? await locator.innerText()).trim().slice(0, 180)
  const actual = await locator.evaluate(() => document.activeElement?.getAttribute('aria-label') ||
    document.activeElement?.outerHTML.slice(0, 160))
  throw new Error('Tab traversal did not reach ' + requested + '. Current focus: ' + actual)
}

async function choose(locator, combination = 'Return') {
  await tabTo(locator)
  await key(combination)
}

async function chooseNotification(page, locator) {
  await locator.waitFor(normalWait)
  await page.locator('[data-slot="dialog-overlay"]:visible').waitFor({ ...normalWait, state: 'hidden' })
  // Let the closing dialog finish returning focus before taking it with the notification shortcut.
  try {
    await page.waitForFunction(() => document.activeElement !== document.body, null, { timeout: 4000 })
  } catch (error) {
    if (error.name !== 'TimeoutError') throw error
  }
  const before = await page.evaluate(() => document.activeElement?.outerHTML.slice(0, 180))
  await key('alt+t')
  const after = await page.evaluate(() => document.activeElement?.outerHTML.slice(0, 180))
  proof.latestNotificationFocus = { before, after }
  save('run.json', { ...proof, captured: steps })
  assert.equal(await page.evaluate(() => document.activeElement?.matches('[data-sonner-toaster]')), true,
    'The notification shortcut did not focus the notification list')
  await choose(locator)
}

async function recordVoice(name, action) {
  const file = path.join(output, name)
  const recorder = spawn('parecord', ['--device=porpita-validation.monitor', '--file-format=wav',
    '--rate=16000', '--channels=1', '--format=s16le', file], { stdio: 'ignore' })
  const stopped = new Promise(resolve => {
    recorder.once('error', () => resolve(false))
    recorder.once('close', code => resolve(code === 0))
  })
  let audible = false
  try {
    await delay(180)
    await action()
    await delay(1600)
  } finally {
    recorder.kill('SIGINT')
    if (await stopped && fs.existsSync(file)) {
      const peak = shell('/usr/bin/python3', ['-c',
        'import array,sys,wave; stream=wave.open(sys.argv[1]); print(max((abs(x) for x in array.array("h", stream.readframes(stream.getnframes()))), default=0))',
        file])
      audible = Number(peak) > 64
    }
  }
  return audible
}

function parseSpeech(buffer) {
  return buffer.toString('utf8').split('\n')
    .map(line => line.split("SPEECH OUTPUT: '")[1]?.split(/'(?=\s*(?:\{|None|$))/)[0])
    .filter(value => value && !/orca:\/\/|pair\?code=|^(?:[A-Za-z0-9_-]{32,})/.test(value))
    .map(value => redact(value).slice(0, 270))
}

function speechSinceLastStep() {
  const buffer = fs.readFileSync(orcaLog)
  const utterances = parseSpeech(buffer.subarray(speechOffset))
  speechOffset = buffer.length
  return utterances
}

function waylandWindows(node) {
  return [node, ...[...node.nodes, ...node.floating_nodes].flatMap(waylandWindows)]
}

function waylandSurfaces() {
  return waylandWindows(JSON.parse(shell('swaymsg', ['-rt', 'get_tree'])))
    .filter(window => window.app_id)
}

function focusedWaylandWindow() {
  return waylandSurfaces().find(window => window.focused)
}

async function focusWaylandWindow(pid) {
  for (let index = 0; index < 70; index++) {
    const surface = waylandSurfaces().find(window => window.pid === pid && /Porpita/i.test(window.name))
    if (surface) {
      if (!surface.focused) {
        shell('swaymsg', ['-r', '[con_id=' + surface.id + ']', 'focus'])
      } else {
        return surface
      }
    }
    await delay(180)
  }
  throw new Error('Porpita did not receive Wayland focus: ' + JSON.stringify(
    waylandSurfaces().map(({ name, pid, shell, focused }) => ({ name, pid, shell, focused }))
  ))
}

async function capture(id, description, page, keyStart, checks = {}) {
  await delay(1100)
  const surface = wayland && !gnome ? focusedWaylandWindow() : null
  const nativeWindow = gnome ? await page.title()
    : wayland ? surface?.name : shell('xdotool', ['getactivewindow', 'getwindowname'])
  assert.match(nativeWindow, /Porpita/i)
  const state = await page.evaluate(() => {
    const node = document.activeElement
    const descendant = node?.getAttribute('aria-activedescendant')
    return {
      viewport: [innerWidth, innerHeight],
      documentFocused: document.hasFocus(),
      dialog: [...document.querySelectorAll('[role=dialog]')].filter(x => x.getClientRects().length).map(x => x.innerText),
      focus: node ? { role: node.getAttribute('role') ?? node.tagName.toLowerCase(), name: node.getAttribute('aria-label') ||
        (descendant && document.getElementById(descendant)?.innerText.trim()) || node.innerText?.trim().slice(0, 140) } : null,
      text: document.body.innerText.slice(0, 5200)
    }
  })
  const imageFile = id + '.png'
  const screenshot = path.join(output, imageFile)
  if (gnome) {
    mutter('screenshot', screenshot)
  } else if (wayland) {
    shell('grim', ['-o', 'HEADLESS-1', screenshot])
  } else {
    shell('/usr/bin/python3', [path.join(stage, 'linux-native-screenshot.py'), process.env.DISPLAY, screenshot])
  }
  const spoken = speechSinceLastStep()
  // Keep the connection result only. The preceding keys could cause a credential to be read.
  const utterances = id.endsWith('-windows-paired')
    ? spoken.filter(value => value.startsWith('Connected to Windows acceptance service.'))
    : spoken
  const record = {
    id, description, imageFile,
    imageMethod: gnome ? 'Mutter RecordMonitor / PipeWire' : wayland ? 'Wayland compositor screencopy' : 'X11 root pixels',
    nativeWindow, ...(surface ? { appId: surface.app_id } : {}),
    keys: keys.slice(keyStart), ...state, utterances, ...checks
  }
  save(id + '.json', JSON.parse(redact(JSON.stringify(record))))
  steps.push(id)
  save('run.json', { ...proof, captured: steps })
  process.stdout.write(id + ' ' + utterances.length + ' speech events\n')
  return record
}

async function createSshTransport() {
  let enabled = true
  const connections = new Set()
  const gateway = net.createServer(input => {
    if (!enabled) return input.destroy()
    const endpoint = net.connect(fixture.port, '127.0.0.1')
    connections.add(input)
    input.on('close', () => { connections.delete(input); endpoint.destroy() })
    endpoint.on('close', () => input.destroy())
    input.on('error', () => endpoint.destroy())
    endpoint.on('error', () => input.destroy())
    input.pipe(endpoint)
    endpoint.pipe(input)
  })
  await new Promise((resolve, reject) => {
    gateway.once('error', reject)
    gateway.listen(0, '127.0.0.1', resolve)
  })
  return {
    port: gateway.address().port,
    enable(value) {
      enabled = value
      if (!enabled) for (const connection of connections) connection.destroy()
    },
    close: () => new Promise(resolve => gateway.close(resolve))
  }
}

function prepareProfile(port) {
  fs.mkdirSync(profile)
  const ssh = path.join(process.env.HOME, '.ssh')
  fs.mkdirSync(ssh, { mode: 0o700 })
  const key = fs.readFileSync(path.join(cell, 'host_key.pub'), 'utf8').trim().split(/\s+/).slice(0, 2).join(' ')
  fs.writeFileSync(path.join(ssh, 'known_hosts'), '[127.0.0.1]:' + port + ' ' + key + '\n', { mode: 0o600 })
  const archivedNode = path.join(profile, 'orcad-artifacts/node/archives')
  fs.mkdirSync(archivedNode, { recursive: true })
  fs.copyFileSync(archive, path.join(archivedNode, 'node-v24.22.1-linux-x64.tar.gz'))
  fs.writeFileSync(path.join(profile, 'orca-data.json'), JSON.stringify({
    settings: { telemetry: { optedIn: false }, uiLanguage: 'en', theme: 'light', agentDefaultSurface: 'terminal' },
    ui: { contextualToursAutoEligible: false, browserImportHintHidden: true, codexTerminalServerIsolationNoticeSeen: true },
    onboarding: { flowVersion: 4, closedAt: 1, outcome: 'completed', lastCompletedStep: 5 },
    sshTargets: [{ id: targetId, label: targetName, host: '127.0.0.1', configHost: '127.0.0.1', port,
      username: fixture.user, identityFile: path.join(cell, 'client_key'), identitiesOnly: true, source: 'manual', generation: 1 }],
    sshTargetGenerationCounter: 1,
    repos: [{ id: repoId, path: repo, displayName: 'Independent project', kind: 'git',
      badgeColor: '#737373', addedAt: 1, connectionId: targetId }],
    worktreeMeta: { [repoId + '::' + worktree]: { hostId: 'ssh:' + targetId,
      instanceId: 'linux-legacy-worktree' + fixtureScope, displayName: 'Legacy checkout',
      comment: '', isArchived: false, isUnread: false, isPinned: false, sortOrder: 0, lastActivityAt: 1 } }
  }))
}

async function waitWindowFocus(browserWindow, focused) {
  for (let i = 0; i < 30; i++) {
    if (await browserWindow.evaluate(window => window.isFocused()) === focused) return
    await delay(150)
  }
  throw new Error('Porpita window focused state did not become ' + focused)
}

async function checkGnomeShortcuts(mark, browserWindow, accessLink) {
  await key('super')
  await mark('i81-activities', 'GNOME Activities takes the keyboard from the pairing form')
  await key('Escape')
  await waitWindowFocus(browserWindow, true)
  const retainedAfterOverview = await accessLink.evaluate(node => node === document.activeElement)
  assert.equal(retainedAfterOverview, true)
  await key('super+v')
  await mark('i81-system-notifications', 'GNOME displays its notification list above Porpita')
  await key('Escape')
  await waitWindowFocus(browserWindow, true)
  const retainedAfterNotifications = await accessLink.evaluate(node => node === document.activeElement)
  assert.equal(retainedAfterNotifications, true)
  const other = spawn('zenity', ['--info', '--title=GNOME keyboard comparison',
    '--text=Second application in the isolated Wayland session'], { stdio: 'ignore' })
  try {
    await delay(750)
    if (await browserWindow.evaluate(window => window.isFocused())) await key('super+Tab')
    await waitWindowFocus(browserWindow, false)
    await key('super+Tab')
    await waitWindowFocus(browserWindow, true)
    await key('super+Tab')
    await waitWindowFocus(browserWindow, false)
    await mark('i81-switch-away', 'GNOME Super+Tab switches from Porpita to the GTK comparison window')
    await key('super+Tab')
    await waitWindowFocus(browserWindow, true)
    const retainedAfterSwitch = await accessLink.evaluate(node => node === document.activeElement)
    assert.equal(retainedAfterSwitch, true)
    proof.gnomeFocus = { retainedAfterOverview, retainedAfterNotifications, retainedAfterSwitch }
    await mark('i81-switch-return', 'GNOME returns keyboard focus to the original pairing input')
  } finally {
    other.kill('SIGTERM')
  }
}

async function pairFromSettings(page, mark, app, browserWindow) {
  const add = page.getByRole('button', { name: 'Add server', exact: true })
  const dialog = page.getByRole('dialog', { name: 'Add server', exact: true })
  const accessLink = dialog.getByLabel('Access link', { exact: true })
  const tip = page.locator('#chat-ui-here-corner-heading')
  if (wayland) {
    await tip.waitFor(normalWait)
    await mark('i80-card-workbench', 'The pending feature card appears in the workbench')
  }
  await choose(page.getByRole('button', { name: 'Settings', exact: true }))
  await choose(page.getByRole('button', { name: 'Remote Orca Servers', exact: true }))
  if (wayland) {
    proof.tipHiddenInServerSettings = !await tip.isVisible()
    await mark('i80-server-settings', 'Server controls share the view with the feature-card policy')
    if (verifyWayland) assert.equal(proof.tipHiddenInServerSettings, true)
  }
  await choose(add)
  await dialog.waitFor(normalWait)
  await tabTo(accessLink)
  if (gnome) await checkGnomeShortcuts(mark, browserWindow, accessLink)
  await key('Tab')
  await key('shift+Tab')
  assert.equal(await accessLink.evaluate(node => node === document.activeElement), true)
  await key('KP_Enter')
  await mark('i75-pair-dialog', 'Native Tab focus reaches the access link')
  await key('Escape')
  await dialog.waitFor({ ...normalWait, state: 'hidden' })
  await delay(300)
  proof.pairingCancelFocus = await add.evaluate(node => node === document.activeElement)
  if (process.env.PORPITA_NATIVE_DISCOVERY !== '1') assert.equal(proof.pairingCancelFocus, true)
  await mark('i75-pair-cancel', 'Escape closes the pairing dialogue and exposes the resulting keyboard focus')
  await choose(add)
  await tabTo(accessLink)
  if (gnome) {
    await app.evaluate(({ clipboard }, text) => clipboard.writeText(text), peer.accessLink)
  } else {
    shell(wayland ? 'wl-copy' : 'xclip', wayland ? [] : ['-selection', 'clipboard', '-in', '-loops', '1'], {
      input: peer.accessLink, stdio: ['pipe', 'ignore', 'ignore']
    })
  }
  await key('ctrl+v')
  const tunnel = dialog.getByRole('checkbox', { name: /I reach this address through an SSH tunnel/ })
  await choose(tunnel, 'space')
  const hostName = dialog.locator('#runtime-server-name')
  await tabTo(hostName)
  await key('ctrl+a')
  const name = 'Windows acceptance service'
  if (gnome) {
    await app.evaluate(({ clipboard }, text) => clipboard.writeText(text), name)
    await key('ctrl+v')
  } else {
    shell(wayland ? 'wtype' : 'xdotool', wayland ? [name] : ['type', '--clearmodifiers', name])
  }
  await choose(dialog.locator('button[type=submit]'))
  await dialog.waitFor({ ...normalWait, state: 'hidden' })
  if (gnome) await app.evaluate(({ clipboard }) => clipboard.clear())
  else if (wayland) shell('wl-copy', ['--clear'])
  await page.getByText(name, { exact: true }).first().waitFor(normalWait)
  const id = await page.evaluate(async name => (await window.api.runtimeEnvironments.list())
    .find(env => env.name === name)?.id, name)
  const status = await call(page, id, 'status.get')
  assert.equal(status.runtimeId, peer.runtimeId)
  proof.pairedWithWindows = true
  await mark('i75-windows-paired', 'Linux desktop paired to the actual Windows peer')
  return id
}

async function call(page, selector, method) {
  return page.evaluate(async args => {
    const answer = await window.api.runtimeEnvironments.call(args)
    if (!answer.ok) throw new Error(answer.error.message)
    return answer.result
  }, { selector, method })
}

async function focusWorktree(page) {
  const list = page.locator('[data-worktree-sidebar][role=listbox]')
  const id = repoId + '::' + worktree
  await key('ctrl+shift+0')
  await tabTo(list)
  for (let i = 0; i < 20; i++) {
    if (await list.evaluate((node, id) => {
      const current = node.getAttribute('aria-activedescendant')
      return current && document.getElementById(current)?.getAttribute('data-worktree-id') === id
    }, id)) return
    await key('Down')
  }
  throw new Error('Keyboard traversal did not reach the legacy worktree')
}

async function openWorktreeRemoval(page, dialog) {
  try {
    await focusWorktree(page)
    await key('ctrl+shift+BackSpace')
    await dialog.waitFor({ timeout: 2600 })
    return true
  } catch (error) {
    if (process.env.PORPITA_NATIVE_DISCOVERY !== '1') throw error
  }
  const id = repoId + '::' + worktree
  await page.locator('[data-worktree-id=' + JSON.stringify(id) + ']').first().hover(normalWait)
  await key('ctrl+shift+BackSpace')
  await dialog.waitFor(normalWait)
  return false
}

async function adoptFromSsh(page, mark, transport, windowsId) {
  await choose(page.getByRole('button', { name: 'Back to app', exact: true }))
  const tip = page.locator('#chat-ui-here-corner-heading')
  if (wayland) {
    await tip.waitFor(normalWait)
    proof.tipResumedInWorkbench = true
    await mark('i80-card-returned', 'The pending feature card returns without recording a dismissal')
  }
  const dialog = page.getByRole('dialog').filter({ hasText: 'Legacy checkout' })
  proof.legacyWorktreeRemovalWithKeyboard = await openWorktreeRemoval(page, dialog)
  assert.match(await dialog.innerText(), /Linux SSH project/)
  await mark('i76-original-ssh-workspace', 'Open SSH recovery from the keyboard-selected legacy worktree')
  await choose(dialog.getByRole('button', { name: 'Open SSH settings', exact: true }))
  const card = page.locator('[data-ssh-target-card][data-ssh-target-label="Linux SSH project"]')
  transport.enable(true)
  const connect = card.getByRole('button', { name: /^Connect(?: |$)/ })
  if (wayland) {
    await tabTo(connect)
    if (gnome) {
      const wide = await page.evaluate(() => innerWidth)
      await mark('i83-ssh-before-tile', 'The connection action in the maximized GNOME window')
      await key('super+Left')
      const tiled = await page.waitForFunction(width => innerWidth <= width / 2 + 20, wide, normalWait)
      await tiled.dispose()
      const narrow = await page.evaluate(() => innerWidth)
      assert.ok(narrow >= 600)
      proof.gnomeWindowWidths = { wide, narrow }
      assert.equal(await connect.evaluate(node => node === document.activeElement), true)
    }
    proof.sshActionClear = await connect.evaluate(button => {
      const rect = button.getBoundingClientRect()
      return button.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2))
    })
    proof.tipHiddenInSshSettings = !await tip.isVisible()
    await mark('i80-ssh-settings', 'Hit test the focused primary SSH action and the feature-card visibility')
    if (verifyWayland) {
      assert.equal(proof.sshActionClear, true)
      assert.equal(proof.tipHiddenInSshSettings, true)
    }
  }
  await choose(connect)
  const connected = card.getByRole('button', { name: /^Disconnect(?: |$)/ })
  const failed = card.getByRole('button', { name: 'Open plain SSH terminal', exact: true })
  await connected.or(failed).first().waitFor({ timeout: 150000 })
  assert.ok(await connected.isVisible(), await card.innerText())
  const handle = await page.waitForFunction(async id => (await window.api.runtimeEnvironments.list())
    .find(item => item.orcadDeployment?.sshTargetId === id)?.id, targetId, { timeout: 25000, polling: 250 })
  const id = await handle.jsonValue()
  await handle.dispose()
  const result = await call(page, id, 'repo.list')
  assert.equal(result.repos.find(item => item.id === repoId)?.path, repo)
  assert.notEqual((await call(page, id, 'status.get')).runtimeId, (await call(page, windowsId, 'status.get')).runtimeId)
  proof.projectAdoptedWithOriginalIdentity = true
  proof.sshActionKeepsFocus = await connected.evaluate(node => node === document.activeElement)
  if (process.env.PORPITA_NATIVE_DISCOVERY !== '1') assert.equal(proof.sshActionKeepsFocus, true)
  await mark('i76-adopted-ssh-host', 'Original SSH project is owned by its independent managed runtime')
  return id
}

async function reviewBranch(page, mark, transport, windowsId, ownerId) {
  const dialog = page.getByRole('dialog', { name: 'Review kept branches', exact: true })
  const row = dialog.locator('li').filter({ hasText: branch })
  const check = row.getByRole('button', { name: 'Check checkout for ' + branch, exact: true })
  const retry = row.getByRole('button', { name: 'Reconnect and check checkout for ' + branch, exact: true })
  const checkbox = row.getByRole('checkbox')
  const force = dialog.getByRole('button', { name: 'Force Delete 1 Branch', exact: true })
  const failed = page.getByRole('button', { name: 'Review failed branches', exact: true })
  const currentOwner = (await call(page, ownerId, 'status.get')).runtimeId
  await choose(page.getByRole('button', { name: 'Back to app', exact: true }))
  const remove = page.getByRole('dialog', { name: 'Delete Workspace', exact: true })
  proof.adoptedWorktreeRemovalWithKeyboard = await openWorktreeRemoval(page, remove)
  await choose(remove.getByRole('button', { name: 'Delete Workspace', exact: true }))
  await remove.waitFor({ ...normalWait, state: 'hidden' })
  const entry = page.getByRole('button', { name: 'Review 1 Branch', exact: true })
  await entry.waitFor(normalWait)
  assert.equal(fs.existsSync(worktree), false)
  assert.equal(linuxHead(), peer.head)
  git(repo, 'worktree', 'add', '-q', path.join(cell, 'home/Checkout Before'), branch)
  git(repo, 'worktree', 'move', path.join(cell, 'home/Checkout Before'), moved)
  await chooseNotification(page, entry)
  await choose(check)
  await row.getByText('Checkout path', { exact: true }).waitFor(normalWait)
  assert.equal(await row.locator('code').textContent(), moved)
  assert.equal(await checkbox.getAttribute('aria-checked'), 'false')
  if (wayland) {
    proof.tipHiddenDuringReview = !await page.locator('#chat-ui-here-corner-heading').isVisible()
    if (verifyWayland) assert.equal(proof.tipHiddenDuringReview, true)
  }
  await mark('i77-moved-checkout', 'The original review reads the actual moved checkout, with no branch selected')
  await choose(checkbox, 'space')
  const outageRecording = gnome ? 'i81-outage-voice.wav' : wayland ? 'i78-outage-voice.wav' : 'i77-outage-voice.wav'
  proof.outageVoiceRecorded = await recordVoice(outageRecording, async () => {
    transport.enable(false)
    await choose(check)
    await row.getByText('Host unavailable', { exact: true }).waitFor({ timeout: 50000 })
  })
  assert.equal(await checkbox.getAttribute('aria-checked'), 'true')
  assert.equal(await row.locator('code').textContent(), moved)
  assert.equal(await force.isDisabled(), true)
  assert.equal(await retry.evaluate(node => node === document.activeElement), true)
  assert.equal((await call(page, windowsId, 'status.get')).runtimeId, peer.runtimeId)
  proof.outagePreservedFocusAndSelection = true
  await mark('i77-original-row-outage', 'The SSH outage retains previous checkout, selected branch, and original keyboard focus')
  git(moved, 'switch', '--detach', 'HEAD')
  transport.enable(true)
  await choose(retry)
  await row.getByText('No checkout', { exact: true }).waitFor(normalWait)
  assert.equal(await force.isEnabled(), true)
  assert.equal((await call(page, ownerId, 'status.get')).runtimeId, currentOwner)
  await mark('i77-original-row-recovered', 'Reconnect and read fresh Git state from the same runtime')
  git(moved, 'switch', branch)
  await choose(force)
  await dialog.waitFor({ ...normalWait, state: 'hidden' })
  await chooseNotification(page, failed)
  await dialog.waitFor(normalWait)
  assert.equal(await checkbox.getAttribute('aria-checked'), 'false')
  assert.equal(await row.locator('code').textContent(), moved)
  assert.equal(linuxHead(), peer.head)
  await mark('i77-git-refusal', 'Git refuses a newly occupied branch and review opens with no selection')
  git(moved, 'switch', '--detach', 'HEAD')
  await choose(check)
  await row.getByText('No checkout', { exact: true }).waitFor(normalWait)
  await choose(checkbox, 'space')
  await tabTo(force)
  if (gnome) {
    await key('super+v')
    await mark('i82-review-interrupted', 'GNOME notifications temporarily cover the Git review')
    await key('Escape')
    await dialog.waitFor(normalWait)
    assert.equal(await checkbox.getAttribute('aria-checked'), 'true')
    assert.equal(await force.evaluate(node => node === document.activeElement), true)
    proof.gnomeReviewRestored = true
    await mark('i82-review-resumed', 'GNOME Escape returns the same selection and action focus')
  }
  const submit = async () => {
    await key('Return')
    await dialog.waitFor({ ...normalWait, state: 'hidden' })
    await page.getByText('Git branches deleted: 1', { exact: true }).waitFor(normalWait)
    await failed.waitFor({ ...normalWait, state: 'hidden' })
    assert.equal(linuxHead(), null)
    proof.deletedOnlyFromSshProject = true
  }
  if (wayland) {
    let result
    let submitSpeechOffset
    const submitKeyStart = keys.length
    const receiptAnnouncements = () => parseSpeech(fs.readFileSync(orcaLog).subarray(submitSpeechOffset))
      .filter(value => /Git branches deleted[: ]+1/i.test(value))
    const receiptRecording = gnome ? 'i82-receipt-voice.wav' : 'i79-receipt-voice.wav'
    proof.receiptVoiceRecorded = await recordVoice(receiptRecording, async () => {
      submitSpeechOffset = fs.statSync(orcaLog).size
      await submit()
      result = await mark('i79-automatic-receipt', 'Watch the completed Git result after the submit key')
      const deadline = Date.now() + 6500
      while (receiptAnnouncements().length === 0 && Date.now() < deadline) await delay(160)
    })
    const announcements = receiptAnnouncements()
    proof.automaticReceiptSpoken = announcements.length > 0
    proof.receiptAnnouncements = announcements.length
    proof.receiptKeys = keys.slice(submitKeyStart)
    assert.deepEqual(proof.receiptKeys, ['Return'])
    save(result.id + '.json', { ...result, announcementsAfterSubmit: announcements, receiptKeys: proof.receiptKeys })
    if (verifyWayland) assert.deepEqual(announcements, ['Git branches deleted: 1'])
    if (gnome) {
      await page.locator('#chat-ui-here-corner-heading').waitFor(normalWait)
      proof.tipResumedAfterReview = true
    }
    return
  }
  await submit()
  await page.locator('[data-slot="dialog-overlay"]:visible').waitFor({ ...normalWait, state: 'hidden' })
  await key('alt+t')
  await key('Tab')
  await key('KP_Enter')
  const result = await mark('i77-explicit-retry-result', 'Read the current success receipt in the native notification list')
  proof.successReceiptSpoken = result.utterances.some(text => /Git branches deleted[: ]+1/i.test(text))
}

async function main() {
  fs.mkdirSync(output)
  assert.equal(peer.product, '0.1.0')
  assert.equal(peer.platform, 'win32')
  assert.equal(peer.sourceCommit, git(source, 'rev-parse', 'HEAD'))
  proof.sourceCommit = peer.sourceCommit
  assert.equal(linuxHead(), peer.head)
  const transport = await createSshTransport()
  transport.enable(false)
  let app
  try {
    prepareProfile(transport.port)
    const env = { ...process.env, ORCA_E2E_USER_DATA_DIR: profile,
      ORCA_E2E_HOME_DIR: process.env.HOME, ORCA_ORCAD_TEMPLATE_PATH: template,
      GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: path.join(run, 'gitconfig') }
    delete env.ORCA_BACKGROUND_LAUNCH
    delete env.ORCA_E2E_HEADLESS
    delete env.ORCA_E2E_HEADFUL
    app = await _electron.launch({
      executablePath: executable, cwd: run, env, timeout: 35000,
      args: [wayland ? '--ozone-platform=wayland' : '--ozone-platform=x11',
        '--no-sandbox', '--disable-gpu', ...(appArgument === '-' ? [] : [appArgument])]
    })
    const page = await app.firstWindow({ timeout: 40000 })
    const window = await app.browserWindow(page)
    if (!wayland) {
      await window.evaluate(browserWindow => browserWindow.setBounds({ x: 110, y: 50, width: 1060, height: 790 }))
    }
    await page.getByRole('button', { name: 'Settings', exact: true }).waitFor(normalWait)
    if (gnome) {
      const started = Date.now()
      while (Date.now() - started < normalWait.timeout && !await window.evaluate(win => win.isVisible())) {
        await delay(150)
      }
      assert.equal(await window.evaluate(win => win.isVisible()), true, 'Porpita did not present a visible Wayland window')
      const nativeWindowWaitMs = Date.now() - started
      const initiallyFocused = await window.evaluate(win => win.isFocused())
      if (!initiallyFocused) {
        mutter('screenshot', path.join(output, 'startup-activities.png'))
        await key('Escape')
        if (!await window.evaluate(win => win.isFocused())) await key('super+Tab')
      }
      await waitWindowFocus(window, true)
      proof.gnomeStartup = { nativeWindowWaitMs, initiallyFocused, focusedBeforeReplay: true }
      await key('super+Up')
      const maximized = await page.waitForFunction(() => innerWidth >= 1380, null, normalWait)
      await maximized.dispose()
      const compositor = JSON.parse(fs.readFileSync(path.join(run, 'compositor.json')))
      assert.equal(compositor.xwayland, false)
      proof.wayland = {
        compositor: compositor.human_readable, socket: process.env.WAYLAND_DISPLAY,
        monitor: compositor.monitor, input: 'Mutter keyboard keycodes (US evdev)',
        x11DisplaySet: false, xwayland: false
      }
    } else if (wayland) {
      const surface = await focusWaylandWindow(app.process().pid)
      assert.match(surface?.name, /Porpita/i)
      assert.equal(surface.shell, 'xdg_shell')
      proof.wayland = {
        compositor: JSON.parse(fs.readFileSync(path.join(run, 'compositor.json'))).human_readable,
        socket: process.env.WAYLAND_DISPLAY,
        appId: surface.app_id,
        shell: surface.shell,
        input: 'virtual keyboard with a standard US evdev map',
        x11DisplaySet: false
      }
    } else {
    const nativeWindow = String(await window.evaluate(win => win.getNativeWindowHandle().readUInt32LE(0)))
    let viewable = false
    for (let attempt = 0; attempt < 60; attempt++) {
      if (shell('xwininfo', ['-id', nativeWindow]).includes('Map State: IsViewable')) {
        viewable = true
        break
      }
      await delay(200)
    }
    if (!viewable) {
      save('window-startup.json', {
        state: await window.evaluate(win => ({ visible: win.isVisible(), title: win.getTitle(), bounds: win.getBounds() })),
        os: shell('xwininfo', ['-root', '-tree']).split('\n').filter(line => line.includes('Porpita'))
      })
      throw new Error('Porpita window did not map on the isolated X11 display')
    }
    assert.match(shell('xdotool', ['getwindowname', nativeWindow]), /Porpita/i)
    // Focus only the native handle returned by the installed app in this isolated display.
    shell('xdotool', ['windowactivate', '--sync', nativeWindow])
    assert.equal(shell('xdotool', ['getactivewindow']), nativeWindow)
    }
    const identity = await app.evaluate(({ app }) => ({
      product: app.getVersion(), electron: process.versions.electron, platform: process.platform,
      architecture: process.arch, packaged: app.isPackaged, profile: app.getPath('userData')
    }))
    assert.equal(identity.product, '0.1.0')
    assert.equal(identity.electron, '43.8.6')
    assert.equal(identity.profile, profile)
    proof.linux = { ...identity, profile: 'isolated' }
    proof.display = gnome ? 'isolated GNOME Shell Wayland and GNOME Orca'
      : wayland ? 'isolated Wayland with Sway and GNOME Orca' : 'isolated X11 with Openbox and GNOME Orca'
    let keyStart = 0
    const mark = async (id, description) => {
      try {
        const recordId = gnome ? id.replace(/^i7[5-8]-/, 'i81-').replace(/^i79-/, 'i82-').replace(/^i80-/, 'i83-')
          : wayland ? id.replace(/^i7[5-7]-/, 'i78-') : id
        const checks = gnome ? { windowFocused: await window.evaluate(win => win.isFocused()) } : {}
        return await capture(recordId, description, page, keyStart, checks)
      } finally {
        keyStart = keys.length
      }
    }
    const windowsId = await pairFromSettings(page, mark, app, window)
    const ownerId = await adoptFromSsh(page, mark, transport, windowsId)
    await reviewBranch(page, mark, transport, windowsId, ownerId)
    proof.completed = true
    save('run.json', { ...proof, captured: steps })
  } catch (error) {
    save('run.json', { ...proof, captured: steps, failure: redact(error.message).slice(0, 1300) })
    throw error
  } finally {
    transport.enable(false)
    try {
      if (app) await app.close()
    } finally {
      await transport.close()
    }
  }
}

main().catch(error => {
  process.stderr.write(redact(error.message) + '\n')
  save('run.json', { ...proof, captured: steps, failure: redact(error.message).slice(0, 1300) })
  process.exitCode = 1
})
