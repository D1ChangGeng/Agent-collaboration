const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { createServer } = require('node:net')
const { createRequire } = require('node:module')
const path = require('node:path')

const rootPattern = /^\/tmp\/porpita-ui72-build\.[A-Za-z0-9]{8}$/
const aliasPattern = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/
const hostKeyPattern = /^SHA256:[A-Za-z0-9+/]+$/
const validPort = value => Number.isInteger(value) && value > 0 && value <= 65535
const quote = value => "'" + String(value).replaceAll("'", "'\\''") + "'"

function prepareConnection(source, file) {
  const fixture = JSON.parse(readFileSync(file, 'utf8'))
  assert.match(fixture.root, rootPattern)
  assert.match(fixture.alias, aliasPattern)
  assert.match(fixture.fingerprint, hostKeyPattern)
  assert.match(fixture.sshCell, /^ssh-cell(?:-r[0-9]+)?$/)
  assert.ok(validPort(fixture.pairPort) && validPort(fixture.sshPort))
  assert.equal(fixture.repoPath, fixture.root + '/' + fixture.sshCell + '/home/project')
  assert.ok(path.isAbsolute(fixture.identityFile) && path.isAbsolute(fixture.templatePath))
  const load = createRequire(path.join(source, 'package.json'))
  const { runProcessSync, spawnProcess } = load('@orca/process-host')
  const options = [
    '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'RequestTTY=no',
    '-o', 'PermitLocalCommand=no', '-o', 'ConnectTimeout=6', '-o', 'ConnectionAttempts=1'
  ]
  const forwards = []

  function remote(script, args = []) {
    const command = ['bash -s --', fixture.root, ...args.map(quote)].join(' ')
    const result = runProcessSync({
      program: 'ssh.exe',
      args: [...options, '-o', 'ClearAllForwardings=yes', fixture.alias, command],
      input: 'set -euo pipefail\n' + script + '\n',
      timeoutMs: 30000
    })
    if (result.code !== 0) {
      throw new Error('Physical SSH command failed: ' + result.stderr.trim().slice(0, 1400))
    }
    return result.stdout.trim()
  }

  function copy(relative, destination) {
    assert.match(relative, /^[a-zA-Z0-9._/-]+$/)
    assert.ok(!relative.split('/').some(part => !part || part === '..'))
    const result = runProcessSync({
      program: 'scp.exe',
      args: ['-q', ...options, '-o', 'ClearAllForwardings=yes', fixture.alias + ':' + fixture.root + '/' + relative, destination],
      timeoutMs: 30000
    })
    if (result.code !== 0) throw new Error('Could not copy the scoped Git input from the test host')
  }

  async function forward(port, localPort = 0) {
    assert.ok(validPort(port) && (localPort === 0 || validPort(localPort)))
    let enabled = true
    const sockets = new Set()
    const server = createServer(socket => {
      if (!enabled) {
        socket.destroy()
        return
      }
      sockets.add(socket)
      const child = spawnProcess({
        program: 'ssh.exe',
        args: [...options, '-W', '127.0.0.1:' + port, fixture.alias],
        stdio: 'pipe'
      })
      child.stderr.resume()
      child.stdin.on('error', () => socket.destroy())
      child.on('error', () => socket.destroy())
      child.on('exit', () => socket.destroy())
      socket.on('error', () => socket.destroy())
      socket.on('close', () => {
        sockets.delete(socket)
        child.kill()
      })
      socket.pipe(child.stdin)
      child.stdout.pipe(socket)
    })
    await new Promise((resolve, reject) => {
      server.once('error', reject)
      server.listen(localPort, '127.0.0.1', resolve)
    })
    const handle = {
      port: server.address().port,
      setEnabled(value) {
        enabled = value
        if (!value) for (const socket of sockets) socket.destroy()
      },
      close() {
        handle.setEnabled(false)
        return new Promise(resolve => server.close(resolve))
      }
    }
    forwards.push(handle)
    return handle
  }

  return {
    fixture,
    remote,
    copy,
    forward,
    async close() {
      await Promise.all(forwards.map(tunnel => tunnel.close()))
    }
  }
}

module.exports = { prepareConnection, quote }
