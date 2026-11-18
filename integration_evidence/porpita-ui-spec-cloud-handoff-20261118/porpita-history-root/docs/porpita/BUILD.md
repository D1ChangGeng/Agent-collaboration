# Porpita source build

This is the developer build procedure. Installed users receive the private runtimes and do not run these commands.

## Locked inputs

- Orca source baseline: `26179069b664b2fc172963564ed419d97892b6c9`.
- ACS baseline: `e5d71968a13e67e3dc51e318867d4ed9a1f946ac`, with the exact runtime overlays in `config/scripts/porpita/core-source.lock.json`.
- Runtime payloads: CPython 3.13.15, PostgreSQL 18.6, Codex 0.166.0, OpenCode 1.18.31 and Microsoft VC143 x64 14.44.35112.
- The 49 third-party Python libraries and six Core build dependencies have whole-wheel SHA-256 locks. Their licenses are retained in the extracted distributions.
- Node-pty native resources use the immutable official archive in `native-resources.lock.json`. Its node-pty patch and Node runtime pin match this source. Porpita server/application JavaScript and Windows launchers/addons are built from this tree.

## Windows x64

Use Node with the repository's supported version, pnpm 12.14.0, Python 3.14+ for build helpers, UV, Git, Rust 1.89 MSVC, Visual Studio 2022 Build Tools with x64/ARM64 tools and the Windows SDK. These are build requirements, not installed application prerequisites. The Windows server template also contains cross-platform native dependency slots; packaging verifies all nine targets.

From the Porpita source checkout:

```powershell
npm exec --yes --package pnpm@12.14.0 -- pnpm install --frozen-lockfile
python config/scripts/porpita/prepare-private-runtime.py --acs-source <ACS-checkout> --install
node config/scripts/porpita/prepare-native-resources.mjs
node config/scripts/native-build/windows/build-windows-process-tree-addon.mjs --arch=x64
node config/scripts/native-build/windows/build-windows-process-tree-addon.mjs --arch=arm64
npm exec --yes --package pnpm@12.14.0 -- pnpm run build:desktop
npm exec --yes --package pnpm@12.14.0 -- pnpm run build:orcad-template
$env:ELECTRON_BUILDER_CACHE = Join-Path (Get-Location) '.build-tools/electron-builder-cache'
npm exec --yes --package pnpm@12.14.0 -- pnpm exec electron-builder --config config/electron-builder.config.cjs --win --x64 --publish never
```

`prepare-private-runtime.py` reads an immutable ACS source archive, applies only the locked overlays in an isolated copy, and keeps the supplied ACS working tree unchanged. The Python library tree is extracted from verified wheels into new staging directories. It verifies both Harness executables and their source licenses, assembles the private VC Runtime, checks normal DLL import closure, and executes the staged Core/Python/PostgreSQL smoke. Promotion moves only verified generated payloads inside the source checkout and retains the previous payload under `.build-tools`.

The binary, Harness, Python, Core and native-resource preparation components can also be run separately. Each has `--help` or a lock beside it. Staging paths and hashes are printed for review. Application profiles and service databases are outside these build payload directories.

Close development application instances before rebuilding native addons. A verified terminal daemon from the same test profile can retain a native DLL after the window quits; stop that owned test daemon before packaging. Keep unrelated application processes running.

`build:electron-vite` regenerates renderer output. Run `build:web-from-renderer` afterward before packaging; `build:desktop` already includes this step. Packaging refuses a missing Web manifest, incomplete service template or native payload. Run the complete build after source changes instead of weakening these checks.

Outputs are under `dist`. Local prototypes are unsigned unless an explicitly configured Porpita signing service is available. Publishing is disabled by the product profile and `--publish never`.

## Other source targets

The inherited macOS/Linux build paths, native computer integrations, terminal/editor capabilities and service target matrix remain in source. Public platform launchers use Porpita paths. This Windows machine has not qualified macOS/Linux desktop execution or ARM64 execution; nine-target template verification is a resource/build check, not an execution result on those platforms. A Windows-only bundled local Runtime must not be described as a tested macOS/Linux local-service distribution.

## Evidence boundaries

`CURRENT_TASK_STATE.md` records the current implementation and actual verification scope. `docs/porpita/evidence/20261109` contains development proof and prototype installer records. A development model exchange or successful package build does not satisfy the final same-installer functional acceptance matrix.

The clean ACS source snapshot for the Porpita overlays is `4f750ec173a0422a56b9989a43acf973cbc980d9` (`codex/porpita-acs-runtime`). The recipe accepts checkout line-ending differences only if it can recover the exact bytes pinned by each overlay digest. A rebuild from that clean checkout produced wheel SHA-256 `03710d29736dd5489900acae3c03a82b1f0eaf5c23ba7a9077efd8975efe4845`, identical to the wheel in prototype 06.

