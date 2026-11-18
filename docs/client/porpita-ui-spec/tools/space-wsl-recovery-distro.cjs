const assert = require('node:assert/strict')
const { execFileSync } = require('node:child_process')
const { randomBytes } = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')

const label = /^PorpitaSpec-[0-9a-f]{8}$/
const nameKey = value => value.toLowerCase()
const wsl = (args, options = {}) => execFileSync('wsl.exe', args, {
  windowsHide: true,
  timeout: 60_000,
  encoding: 'utf8',
  stdio: ['pipe', 'pipe', 'pipe'],
  env: { ...process.env, WSL_UTF8: '1' },
  ...options
}).replaceAll('\0', '').trim()
const registered = () => wsl(['--list', '--quiet']).split(/\r?\n/).map(nameKey)

const makeRootfs = [
  'set -euo pipefail',
  'stage=$(mktemp -d /tmp/porpita-spec-rootfs-XXXXXXXX)',
  "trap 'rm -rf -- \"$stage\"' EXIT",
  'binaries=(/bin/bash /bin/sh /usr/bin/git /usr/bin/env /usr/bin/mktemp /usr/bin/realpath /usr/bin/rm',
  ' /usr/bin/mkdir /usr/bin/stat /usr/bin/du /usr/bin/df /usr/bin/find /usr/bin/sort /usr/bin/awk /usr/bin/sed',
  ' /usr/bin/cat /usr/bin/uname /usr/bin/id /usr/bin/whoami /usr/bin/readlink /usr/bin/getent /usr/bin/dirname',
  ' /usr/bin/stty /usr/bin/tty /usr/bin/head /usr/bin/cut /usr/bin/grep /usr/bin/printf /usr/bin/which',
  ' /usr/bin/true /usr/bin/false /usr/bin/sleep /usr/bin/busybox /usr/bin/ls /usr/bin/cp /usr/bin/test)',
  'mkdir -p "$stage"/{etc,root,tmp,proc,sys,dev,run,mnt,usr/lib/git-core}',
  'chmod 1777 "$stage/tmp"',
  'for binary in "${binaries[@]}"; do',
  '  cp --parents --dereference "$binary" "$stage"',
  '  while IFS= read -r lib; do cp --parents --dereference "$lib" "$stage"; done < <(',
  "    { ldd \"$binary\" 2>/dev/null || true; } | awk '{ for(i=1;i<=NF;i++) if($i~/^\\//) { print $i; break } }')",
  'done',
  'cp -L /etc/os-release "$stage/etc/os-release"',
  'ln -s /usr/bin/git "$stage/usr/lib/git-core/git"',
  "printf 'root:x:0:0:root:/root:/bin/bash\\n' > \"$stage/etc/passwd\"",
  "printf 'root:x:0:\\n' > \"$stage/etc/group\"",
  "printf 'passwd: files\\ngroup: files\\nhosts: files dns\\n' > \"$stage/etc/nsswitch.conf\"",
  "printf '[boot]\\nsystemd=false\\n[user]\\ndefault=root\\n[automount]\\nenabled=false\\nmountFsTab=false\\n[interop]\\nappendWindowsPath=false\\n' > \"$stage/etc/wsl.conf\"",
  'tar --owner=0 --group=0 -cpf "$1" -C "$stage" .'
].join('\n')

function prepare(root) {
  assert.equal(process.platform, 'win32')
  fs.mkdirSync(root, { recursive: true })
  const distro = 'PorpitaSpec-' + randomBytes(4).toString('hex')
  assert.ok(!registered().includes(nameKey(distro)))
  const artifactRoot = path.join(fs.realpathSync(root), distro)
  fs.mkdirSync(artifactRoot)
  const archive = path.join(artifactRoot, 'rootfs.tar')
  const installRoot = path.join(artifactRoot, 'install')
  fs.mkdirSync(installRoot)
  const linuxArchive = wsl(['--distribution', 'Ubuntu', '--exec', 'wslpath', '-u', archive])
  wsl(['--distribution', 'Ubuntu', '--exec', '/bin/bash', '-s', '--', linuxArchive], { input: makeRootfs })
  wsl(['--import', distro, installRoot, archive, '--version', '2'])
  const manifest = path.join(artifactRoot, 'fixture.json')
  fs.writeFileSync(manifest, JSON.stringify({ distro, installRoot }, null, 2) + '\n', { flag: 'wx' })
  return manifest
}

function readFixture(manifest) {
  const fixture = JSON.parse(fs.readFileSync(manifest, 'utf8'))
  assert.match(fixture.distro, label)
  assert.equal(path.basename(path.dirname(manifest)), fixture.distro)
  assert.equal(path.resolve(fixture.installRoot), path.resolve(path.dirname(manifest), 'install'))
  return fixture
}

function dispose(manifest) {
  const { distro } = readFixture(manifest)
  if (registered().includes(nameKey(distro))) wsl(['--unregister', distro])
  assert.ok(!registered().includes(nameKey(distro)))
}

if (require.main === module) {
  const [operation, input] = process.argv.slice(2)
  assert.ok(input && (operation === 'prepare' || operation === 'dispose'))
  if (operation === 'prepare') console.log(prepare(path.resolve(input)))
  else dispose(path.resolve(input))
}

module.exports = { readFixture, wsl }
