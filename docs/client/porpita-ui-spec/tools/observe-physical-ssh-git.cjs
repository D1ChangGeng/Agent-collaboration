const assert = require('node:assert/strict')
const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const branch = 'spec-ssh-review'
const stamp = '2026-01-01T00:00:00Z'
const remoteRootPattern = /^\/tmp\/porpita-ssh-review-[A-Za-z0-9]{8}$/
const aliasPattern = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$/
const protectedRemote = [
  'set -euo pipefail',
  'export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0',
  'export GIT_AUTHOR_DATE=' + stamp + ' GIT_COMMITTER_DATE=' + stamp,
  'export LC_ALL=C'
].join('\n')

function onSsh(alias, script, root) {
  assert.match(alias, aliasPattern)
  if (root) assert.match(root, remoteRootPattern)
  return execFileSync('ssh.exe', [
    '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ClearAllForwardings=yes',
    '-o', 'RequestTTY=no', '-o', 'PermitLocalCommand=no', '-o', 'ConnectTimeout=5',
    alias, 'bash -s --' + (root ? ' ' + root : '')
  ], { input: protectedRemote + '\n' + script + '\n', windowsHide: true, encoding: 'utf8', timeout: 30000 }).trim()
}

function scopedGit(cwd, args) {
  return execFileSync('git', ['-C', cwd, ...args], {
    env: { ...process.env, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: path.join(cwd, 'empty-git-config'),
      GIT_AUTHOR_DATE: stamp, GIT_COMMITTER_DATE: stamp, GIT_TERMINAL_PROMPT: '0' },
    windowsHide: true, encoding: 'utf8'
  }).trim()
}

function prepare(alias, output) {
  fs.mkdirSync(output, { recursive: true })
  const [root, head, kernel, virtualization] = onSsh(alias, [
    'root=$(mktemp -d /tmp/porpita-ssh-review-XXXXXXXX)',
    "trap 'rm -rf -- \"$root\"' ERR",
    'git init -q --template= --object-format=sha1 -b main "$root/repo"',
    "git -C \"$root/repo\" -c 'user.name=Porpita Spec' -c user.email=spec@example.invalid commit -q --allow-empty --no-gpg-sign -m 'Branch review fixture'",
    'git -C "$root/repo" branch ' + branch,
    'git -C "$root/repo" worktree add -q "$root/Before" ' + branch,
    'printf "%s\\n" "$root"',
    'git -C "$root/repo" rev-parse HEAD',
    'uname -srm',
    'systemd-detect-virt || true'
  ].join('\n')).split(/\r?\n/)
  assert.match(root, remoteRootPattern)
  assert.match(head, /^[a-f0-9]{40}$/)
  try {
    const shadow = fs.mkdtempSync(path.join(fs.realpathSync(output), 'shadow-'))
    scopedGit(shadow, ['init', '-q', '--template=', '--object-format=sha1', '-b', 'main'])
    scopedGit(shadow, ['-c','user.name=Porpita Spec','-c','user.email=spec@example.invalid',
      'commit','-q','--allow-empty','--no-gpg-sign','-m','Branch review fixture'])
    scopedGit(shadow, ['branch', branch])
    assert.equal(scopedGit(shadow, ['rev-parse', 'refs/heads/' + branch]), head)
    const [movedHead, movedPath] = onSsh(alias, [
      'git -C "$1/repo" worktree move "$1/Before" "$1/Checkout Moved"',
      'git -C "$1/repo" rev-parse refs/heads/' + branch,
      "git -C \"$1/repo\" worktree list --porcelain | sed -n 's/^worktree .*\\/Checkout Moved$/<fixture>\\/Checkout Moved/p'"
    ].join('\n'), root).split(/\r?\n/)
    assert.equal(movedHead, head)
    assert.equal(movedPath, '<fixture>/Checkout Moved')
    const manifest = path.join(output, 'fixture.json')
    fs.writeFileSync(manifest, JSON.stringify({ alias, root, head, shadow, kernel, virtualization, branch,
      repoPath: root + '/repo', worktreePath: root + '/Checkout Moved' }, null, 2), { flag: 'wx' })
    console.log(manifest)
  } catch (error) {
    onSsh(alias, 'rm -rf -- "$1"', root)
    throw error
  }
}

function finish(manifest) {
  const fixture = JSON.parse(fs.readFileSync(manifest, 'utf8'))
  assert.equal(fixture.branch, branch)
  const { alias, root, head, shadow, kernel, virtualization } = fixture
  try {
    const [remoteHead, currentBranch] = onSsh(alias, [
      'git -C "$1/repo" rev-parse refs/heads/' + branch,
      'git -C "$1/Checkout Moved" branch --show-current'
    ].join('\n'), root).split(/\r?\n/)
    assert.equal(remoteHead, head)
    assert.equal(currentBranch, branch)
    assert.equal(scopedGit(shadow, ['rev-parse', 'refs/heads/' + branch]), head)
    fs.writeFileSync(path.join(path.dirname(manifest), 'physical-ssh-checks.json'),
      JSON.stringify({ kernel, virtualization, transport: 'OpenSSH over network to registered workstation',
        separateSshInvocations: true, actualWorktreeMoved: true, lastCheckout: '<fixture>/Checkout Moved',
        sameNamedLocalRefHadSameHead: true, bothRefsPreserved: true }, null, 2) + '\n')
  } finally {
    onSsh(alias, 'rm -rf -- "$1"', root)
  }
}

const [operation, aliasOrManifest, output] = process.argv.slice(2)
if (operation === 'prepare') prepare(aliasOrManifest, path.resolve(output))
else if (operation === 'finish') finish(path.resolve(aliasOrManifest))
else throw new Error('Use prepare <registered-ssh-alias> <scratch-directory> or finish <fixture.json>')
