import { execFileSync, spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { mkdirSync, rmSync } from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { sleep } from './electron-harness.mjs'

const THIS_DIR = path.dirname(fileURLToPath(import.meta.url))
const SERVER_SCRIPT = path.join(THIS_DIR, 'acs_loopback_server.py')
const AGENT_COLLAB_ROOT = 'D:\\Chatgpt\\Agent-collaboration'
const VENV_PYTHON = path.join(AGENT_COLLAB_ROOT, '.venv', 'Scripts', 'python.exe')

const ACTIVE_CORES = new Set()
let SHARED_DOCKER_PG = null

export async function findFreePort() {
  return await new Promise((resolve, reject) => {
    const srv = net.createServer()
    srv.unref()
    srv.on('error', reject)
    srv.listen(0, '127.0.0.1', () => {
      const addr = srv.address()
      const port = typeof addr === 'object' && addr ? addr.port : null
      srv.close((err) => {
        if (err) reject(err)
        else resolve(port)
      })
    })
  })
}

function runPythonSync(args, extraEnv = {}, { quiet = false } = {}) {
  return execFileSync(VENV_PYTHON, args, {
    cwd: AGENT_COLLAB_ROOT,
    env: {
      ...process.env,
      PYTHONPATH: AGENT_COLLAB_ROOT,
      PYTHONIOENCODING: 'utf-8',
      ...extraEnv
    },
    encoding: 'utf8',
    stdio: quiet ? ['ignore', 'pipe', 'pipe'] : undefined,
    timeout: 60000
  })
}

async function ensureSharedDockerPg() {
  if (SHARED_DOCKER_PG) return SHARED_DOCKER_PG

  let lastBindErr = null
  for (let attempt = 0; attempt < 4; attempt++) {
    const pgPort = await findFreePort()
    if (pgPort === 54329) continue
    const containerName = `porpita-e2e-pg-${randomUUID().slice(0, 12)}`
    const password = `e2e-${randomUUID().replace(/-/g, '')}`

    try {
      execFileSync(
        'wsl',
        [
          'docker',
          'run',
          '--rm',
          '-d',
          '--name',
          containerName,
          '-p',
          `127.0.0.1:${pgPort}:5432`,
          '-e',
          'POSTGRES_USER=acs',
          '-e',
          `POSTGRES_PASSWORD=${password}`,
          '-e',
          'POSTGRES_DB=acs_e2e',
          'postgres:16-alpine',
          '-c',
          'fsync=off',
          '-c',
          'synchronous_commit=off',
          '-c',
          'full_page_writes=off'
        ],
        { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 45000 }
      )
    } catch (err) {
      lastBindErr = err
      try {
        execFileSync('wsl', ['docker', 'rm', '-f', containerName], { stdio: 'ignore', timeout: 15000 })
      } catch {
        // ignore
      }
      await sleep(250)
      continue
    }

    const baseDsn = `postgresql://acs:${password}@127.0.0.1:${pgPort}/acs_e2e`
    const deadline = Date.now() + 30000
    let lastErr = null
    while (Date.now() < deadline) {
      try {
        runPythonSync(
          [
            '-c',
            'import psycopg, sys; conn = psycopg.connect(sys.argv[1], connect_timeout=2); conn.execute("SELECT 1"); conn.close()',
            baseDsn
          ],
          {},
          { quiet: true }
        )
        lastErr = null
        break
      } catch (err) {
        lastErr = err
        await sleep(300)
      }
    }
    if (lastErr) {
      try {
        execFileSync('wsl', ['docker', 'rm', '-f', containerName], { stdio: 'ignore', timeout: 15000 })
      } catch {
        // ignore
      }
      throw new Error(`Ephemeral PostgreSQL container ${containerName} failed to become ready: ${lastErr.message}`)
    }

    SHARED_DOCKER_PG = { containerName, pgPort, baseDsn }
    return SHARED_DOCKER_PG
  }
  throw new Error(`Failed to start ephemeral PostgreSQL container after 4 attempts: ${lastBindErr?.message || 'unknown error'}`)
}

async function teardownSharedDockerPg() {
  if (!SHARED_DOCKER_PG) return
  const { containerName } = SHARED_DOCKER_PG
  SHARED_DOCKER_PG = null
  try {
    execFileSync('wsl', ['docker', 'rm', '-f', containerName], {
      stdio: 'ignore',
      timeout: 20000
    })
  } catch {
    // Best-effort removal
  }
}

async function provisionPostgres() {
  const externalDsn = process.env.ACS_E2E_PG_DSN
  let baseDsn = externalDsn
  let kind = 'schema'
  if (!baseDsn) {
    const shared = await ensureSharedDockerPg()
    baseDsn = shared.baseDsn
    kind = 'docker-schema'
  }

  const schema = `e2e_${randomUUID().replace(/-/g, '').slice(0, 16)}`
  runPythonSync([
    '-c',
    `import psycopg, sys; conn = psycopg.connect(sys.argv[1], autocommit=True); conn.execute(f'CREATE SCHEMA "{sys.argv[2]}"'); conn.close()`,
    baseDsn,
    schema
  ])
  const sep = baseDsn.includes('?') ? '&' : '?'
  const dsn = `${baseDsn}${sep}options=-c%20search_path%3D${schema}`
  return {
    kind,
    schema,
    baseDsn,
    dsn,
    teardown: async () => {
      try {
        runPythonSync(
          [
            '-c',
            `import psycopg, sys; conn = psycopg.connect(sys.argv[1], autocommit=True); conn.execute(f'DROP SCHEMA IF EXISTS "{sys.argv[2]}" CASCADE'); conn.close()`,
            baseDsn,
            schema
          ],
          {},
          { quiet: true }
        )
      } catch {
        // Best-effort schema cleanup
      }
    }
  }
}

export async function startLoopbackAcsCore({ mode = 'full' } = {}) {
  const tempDir = path.join(os.tmpdir(), `porpita-acs-e2e-${randomUUID().slice(0, 12)}`)
  const stateDir = path.join(tempDir, 'state')
  mkdirSync(stateDir, { recursive: true })

  const pg = await provisionPostgres()
  let serverProc = null
  let httpPort = null
  let adminToken = null
  let stderrChunks = []

  const core = {
    mode,
    tempDir,
    stateDir,
    pg,
    get port() {
      return httpPort
    },
    get baseUrl() {
      return `http://127.0.0.1:${httpPort}`
    },
    get apiUrl() {
      return `http://127.0.0.1:${httpPort}/api/communication/v1`
    },
    info: null,
    tokens: null,
    addresses: null,
    nativeLinkFixture: null,
    async request(method, relPath, { token = null, headers = {}, body = undefined, rawBody = undefined } = {}) {
      const target = relPath.startsWith('http')
        ? relPath
        : relPath.startsWith('/__e2e')
          ? `${this.baseUrl}${relPath}`
          : `${this.apiUrl}${relPath.startsWith('/') ? relPath : '/' + relPath}`
      const hdrs = { ...headers }
      if (token) hdrs.Authorization = `Bearer ${token}`
      let payload = rawBody
      if (body !== undefined && rawBody === undefined) {
        payload = JSON.stringify(body)
        if (!hdrs['Content-Type'] && !hdrs['content-type']) {
          hdrs['Content-Type'] = 'application/json'
        }
      }
      const res = await fetch(target, {
        method,
        headers: hdrs,
        body: payload,
        signal: AbortSignal.timeout(30000)
      })
      const text = await res.text()
      let json = null
      try {
        json = text ? JSON.parse(text) : null
      } catch {
        json = null
      }
      return { status: res.status, headers: res.headers, text, json }
    },
    async adminPost(relPath, body = {}) {
      const res = await this.request('POST', relPath, { token: adminToken, body })
      if (res.status >= 400) {
        throw new Error(`Admin POST ${relPath} failed (${res.status}): ${res.text}`)
      }
      return res.json
    },
    peerSend(opts) {
      return this.adminPost('/__e2e/peer-send', opts)
    },
    dispatchPending() {
      return this.adminPost('/__e2e/dispatch-pending', {})
    },
    emitNotice(opts = {}) {
      return this.adminPost('/__e2e/emit-notice', opts)
    },
    revokeToken(actor = 'client') {
      return this.adminPost('/__e2e/revoke-token', { actor })
    },
    restoreToken(actor = 'client') {
      return this.adminPost('/__e2e/restore-token', { actor })
    },
    setFault(opts) {
      return this.adminPost('/__e2e/fault', opts)
    },
    async startServer({ newMode = mode, fixedPort = null } = {}) {
      if (serverProc && serverProc.exitCode === null) {
        throw new Error('ACS loopback server is already running')
      }
      httpPort = fixedPort || (await findFreePort())
      stderrChunks = []
      serverProc = spawn(
        VENV_PYTHON,
        [
          SERVER_SCRIPT,
          'serve',
          '--dsn',
          pg.dsn,
          '--state',
          stateDir,
          '--port',
          String(httpPort),
          '--mode',
          newMode
        ],
        {
          cwd: AGENT_COLLAB_ROOT,
          env: {
            ...process.env,
            PYTHONPATH: AGENT_COLLAB_ROOT,
            PYTHONIOENCODING: 'utf-8',
            NO_PROXY: '127.0.0.1,localhost'
          },
          stdio: ['ignore', 'pipe', 'pipe']
        }
      )
      serverProc.stderr.on('data', (chunk) => {
        if (stderrChunks.length < 32) stderrChunks.push(chunk.toString('utf8'))
      })

      const deadline = Date.now() + 60000
      while (Date.now() < deadline) {
        if (serverProc.exitCode !== null) {
          throw new Error(
            `ACS loopback server exited early (${serverProc.exitCode}): ${stderrChunks.join('')}`
          )
        }
        try {
          const res = await fetch(`${this.apiUrl}/meta`, {
            signal: AbortSignal.timeout(3000)
          })
          if (res.status === 200) {
            const infoRes = await this.request('GET', '/__e2e/info', { token: adminToken })
            if (infoRes.status === 200) {
              this.info = infoRes.json
              this.tokens = infoRes.json.tokens
              this.addresses = infoRes.json.addresses
              this.nativeLinkFixture = infoRes.json.native_link_fixture
              return
            }
          }
        } catch {
          // Server still starting
        }
        await sleep(150)
      }
      throw new Error(`ACS loopback server did not become ready in 60s: ${stderrChunks.join('')}`)
    },
    async stopServer() {
      if (!serverProc) return
      const proc = serverProc
      serverProc = null
      if (proc.exitCode !== null) return
      const exited = new Promise((resolve) => proc.once('exit', resolve))
      try {
        if (process.platform === 'win32') {
          execFileSync('taskkill', ['/pid', String(proc.pid), '/T', '/F'], {
            stdio: 'ignore',
            timeout: 5000
          })
        } else {
          proc.kill('SIGTERM')
        }
      } catch {
        try {
          proc.kill('SIGKILL')
        } catch {
          // ignore
        }
      }
      await Promise.race([exited, sleep(5000)])
    },
    async restartServer(opts = {}) {
      const prevPort = httpPort
      await this.stopServer()
      await this.startServer({ fixedPort: opts.reusePort ? prevPort : null, newMode: opts.mode || mode })
    },
    async cleanup() {
      ACTIVE_CORES.delete(core)
      await this.stopServer().catch(() => {})
      await pg.teardown().catch(() => {})
      for (let i = 0; i < 12; i++) {
        try {
          rmSync(tempDir, { recursive: true, force: true })
          break
        } catch {
          await sleep(300)
        }
      }
    }
  }

  ACTIVE_CORES.add(core)

  try {
    const setupOut = runPythonSync([SERVER_SCRIPT, 'setup', '--dsn', pg.dsn, '--state', stateDir])
    const setupJson = JSON.parse(setupOut.trim().split('\n').pop())
    adminToken = setupJson.tokens.admin
    await core.startServer({ newMode: mode })
    return core
  } catch (err) {
    await core.cleanup().catch(() => {})
    throw err
  }
}

export async function cleanupAllAcsCores() {
  for (const core of [...ACTIVE_CORES]) {
    await core.cleanup().catch(() => {})
  }
  await teardownSharedDockerPg().catch(() => {})
}
