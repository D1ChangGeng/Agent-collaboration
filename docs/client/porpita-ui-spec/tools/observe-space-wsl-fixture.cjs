const assert = require('node:assert/strict')
const { execFileSync } = require('node:child_process')

function prepareSpaceWslFixture(distro) {
  const run = (...args) => execFileSync('wsl.exe', ['--distribution', distro, '--exec', ...args], {
    windowsHide: true, encoding: 'utf8', timeout: 30000, stdio: ['ignore', 'pipe', 'pipe']
  }).trim()
  const fixtureRoot = run('/usr/bin/mktemp', '-d', '/tmp/porpita-ui-spec-XXXXXXXX')
  assert.match(fixtureRoot, /^\/tmp\/porpita-ui-spec-[a-z0-9]{8}$/i)
  const unc = linux => '\\\\wsl.localhost\\' + distro + linux.replaceAll('/', '\\')
  const prefix = '//wsl.localhost/' + distro
  const nativePath = value => {
    const normalized = value.replaceAll('\\', '/').replace(/^\/\/wsl\$\//i, '//wsl.localhost/')
    return normalized.toLowerCase().startsWith(prefix.toLowerCase() + '/')
      ? normalized.slice(prefix.length)
      : value
  }
  const git = (cwd, ...args) => run('/usr/bin/env', 'GIT_CONFIG_GLOBAL=/dev/null',
    'GIT_CONFIG_NOSYSTEM=1', '/usr/bin/git', '-C', nativePath(cwd), ...args.map(nativePath))
  const dispose = () => {
    assert.equal(run('/usr/bin/realpath', '--', fixtureRoot), fixtureRoot)
    run('/usr/bin/rm', '-rf', '--', fixtureRoot)
  }
  return { repo: unc(fixtureRoot + '/UI-spec-sample'), git, distro, dispose }
}

module.exports = { prepareSpaceWslFixture }
