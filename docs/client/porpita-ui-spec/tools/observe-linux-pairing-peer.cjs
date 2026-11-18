const assert = require('node:assert/strict')
const { execFileSync, spawn } = require('node:child_process')
const { createRequire } = require('node:module')
const fs = require('node:fs')
const path = require('node:path')
const { setTimeout: delay } = require('node:timers/promises')

const [source, scratch, remote, portText] = process.argv.slice(2)
assert.equal(process.platform, 'win32')
assert.match(remote, /^[a-zA-Z0-9][a-zA-Z0-9_.-]*:\/tmp\/porpita-ui[0-9]+\.[A-Za-z0-9]{8}$/)
const [alias, remoteStage] = remote.split(':')
const port = Number(portText)
assert.ok(Number.isInteger(port) && port > 1024 && port < 65536)
const load = createRequire(path.join(source, 'package.json'))
const { _electron } = load('playwright')
const profile = path.join(scratch, 'profile')
const home = path.join(profile, 'home')
const repo = path.join(scratch, 'project')
const sshOptions = ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=8']

function prepare() {
  for (const dir of ['AppData/Local', 'AppData/Roaming']) {
    fs.mkdirSync(path.join(home, dir), { recursive: true })
  }
  fs.mkdirSync(repo, { recursive: true })
  const bundle = path.join(scratch, 'branch.bundle')
  execFileSync('scp.exe', ['-q', ...sshOptions, remote + '/ssh-cell/branch.bundle', bundle], {
    windowsHide: true, timeout: 30000
  })
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    !/^(HOME|USERPROFILE|APPDATA|LOCALAPPDATA|HOMEDRIVE|HOMEPATH|ELECTRON_RUN_AS_NODE|ORCA_.*|PORPITA_.*|ACS_.*|CODEX_.*|OPENAI_.*|ANTHROPIC_.*|GH_.*|GITHUB_.*|GITLAB_.*|AWS_.*|AZURE_.*)$/i.test(key)
  ))
  Object.assign(env, {
    HOME: home, USERPROFILE: home,
    APPDATA: path.join(home, 'AppData/Roaming'), LOCALAPPDATA: path.join(home, 'AppData/Local'),
    ORCA_BACKGROUND_LAUNCH: '1', ORCA_E2E_HEADLESS: '1',
    ORCA_E2E_HOME_DIR: home, ORCA_E2E_USER_DATA_DIR: profile,
    GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: path.join(home, 'gitconfig')
  })
  const git = (...args) => execFileSync('git', args, { env, cwd: repo, windowsHide: true, encoding: 'utf8' }).trim()
  git('init', '-q', '-b', 'main')
  git('fetch', '-q', '--no-tags', bundle, 'refs/heads/review-topic:refs/heads/review-topic')
  git('reset', '-q', '--hard', 'review-topic^')
  fs.writeFileSync(path.join(profile, 'orca-data.json'), JSON.stringify({
    settings: { telemetry: { optedIn: false }, uiLanguage: 'en' },
    onboarding: { flowVersion: 4, closedAt: 1, outcome: 'completed', lastCompletedStep: 5 },
    repos: [{ id: 'spec-windows-peer', displayName: 'Windows validation project', path: repo,
      kind: 'git', addedAt: 1, badgeColor: '#737373' }]
  }))
  return { env, git }
}

function readReady(child) {
  return new Promise((resolve, reject) => {
    let buffer = ''
    let stderr = ''
    const report = message => new Error(message + (stderr ? '\n' + stderr : ''))
    const receiveError = chunk => { stderr = (stderr + chunk).slice(-2000) }
    const timer = setTimeout(() => done(report('Windows peer readiness timed out')), 65000)
    const exit = () => done(report('Windows peer exited before publishing readiness'))
    function done(error, ready) {
      clearTimeout(timer)
      child.stdout.off('data', receive)
      child.stderr?.off('data', receiveError)
      child.off('exit', exit)
      if (error) reject(error)
      else resolve(ready)
    }
    function receive(chunk) {
      buffer = (buffer + chunk.toString()).slice(-65536)
      const start = buffer.lastIndexOf('"type": "orca_server_ready"')
      const offset = start >= 0 ? buffer.lastIndexOf('{', start) : -1
      const singleLine = buffer.split(/\r?\n/).filter(line => line.includes('"type":"orca_server_ready"'))
      if (offset >= 0) singleLine.push(buffer.slice(offset))
      for (const candidate of singleLine) {
        for (let end = candidate.indexOf('}'); end >= 0; end = candidate.indexOf('}', end + 1)) {
          try {
            const parsed = JSON.parse(candidate.slice(0, end + 1))
            if (parsed.type === 'orca_server_ready') return done(null, parsed)
          } catch {
            // A nested ready field may be split across process output writes.
          }
        }
      }
    }
    child.on('exit', exit)
    child.stdout.on('data', receive)
    child.stderr?.on('data', receiveError)
  })
}

async function main() {
  const { env, git } = prepare()
  const initialHead = git('rev-parse', 'refs/heads/review-topic')
  const sourceCommit = execFileSync('git', ['rev-parse', 'HEAD'], {
    cwd: source, windowsHide: true, encoding: 'utf8'
  }).trim()
  assert.match(sourceCommit, /^[a-f0-9]{40}$/)
  const forward = spawn('ssh.exe', [
    ...sshOptions, '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=15',
    '-NT', '-R', `127.0.0.1:${port}:127.0.0.1:${port}`, alias
  ], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] })
  let forwardError = ''
  forward.stderr.on('data', chunk => { forwardError = (forwardError + chunk).slice(-1200) })
  let app
  try {
    app = await _electron.launch({
      executablePath: load('electron'),
      args: [source, '--serve', '--serve-json', '--serve-bind', '127.0.0.1',
        '--serve-port', portText, '--serve-pairing-address', '127.0.0.1', '--serve-refuse-public'],
      env, cwd: scratch, timeout: 35000
    })
    const ready = await readReady(app.process())
    assert.equal(forward.exitCode, null, forwardError)
    assert.equal(ready.pairing?.available, true)
    assert.equal(new URL(ready.boundEndpoint).port, portText)
    assert.match(ready.pairing.url, /^orca:\/\/pair\?code=/)
    const appState = await app.evaluate(({ app, BrowserWindow }) => ({
      product: app.getVersion(), architecture: process.arch, platform: process.platform,
      anyVisible: BrowserWindow.getAllWindows().some(window => window.isVisible() || window.isFocused())
    }))
    assert.deepEqual(appState, { product: '0.1.0', architecture: 'x64', platform: 'win32', anyVisible: false })
    const ticket = path.join(scratch, 'peer-ready.json')
    fs.writeFileSync(ticket, JSON.stringify({
      runtimeId: ready.runtimeId, accessLink: ready.pairing.url, head: initialHead, port, sourceCommit, ...appState
    }))
    execFileSync('scp.exe', ['-q', ...sshOptions, ticket, alias + ':' + remoteStage + '/peer-ready.json'], {
      windowsHide: true, timeout: 30000
    })
    fs.unlinkSync(ticket)
    process.stdout.write('Paired Windows endpoint ready in the isolated Linux loopback relay\n')
    const until = Date.now() + 60 * 60 * 1000
    const stop = path.join(scratch, 'stop')
    while (!fs.existsSync(stop) && Date.now() < until) {
      assert.equal(forward.exitCode, null, forwardError)
      await delay(500)
    }
    assert.equal(git('rev-parse', 'refs/heads/review-topic'), initialHead)
    fs.writeFileSync(path.join(scratch, 'peer-proof.json'), JSON.stringify({
      ...appState, sourceCommit, counterpartRefUnchanged: true
    }, null, 2) + '\n')
  } finally {
    try {
      if (app) await app.close()
    } finally {
      forward.kill()
    }
  }
}

main().catch(error => {
  process.stderr.write(error.message.replace(/orca:\/\/[^\s"']+/g, 'orca://[redacted]') + '\n')
  process.exitCode = 1
})
