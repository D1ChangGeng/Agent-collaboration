import { createRequire } from 'node:module'
import { existsSync, statSync } from 'node:fs'
import path from 'node:path'

const cache = new Map()

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function getBuildEntryStats(porpitaRoot) {
  const required = [
    path.join(porpitaRoot, 'out', 'main', 'index.js'),
    path.join(porpitaRoot, 'out', 'main', 'daemon-entry.js'),
    path.join(porpitaRoot, 'out', 'preload', 'index.js'),
    path.join(porpitaRoot, 'out', 'renderer', 'index.html'),
    path.join(porpitaRoot, 'out', 'renderer', 'space.html')
  ]
  const stats = []
  for (const file of required) {
    if (!existsSync(file)) return null
    const st = statSync(file)
    if (!st.isFile() || st.size <= 0) return null
    stats.push(`${file}:${st.size}:${st.mtimeMs}`)
  }
  return stats.join('|')
}

/**
 * Wait until Porpita's out/ build artifacts exist, are non-empty, and stay stable
 * across two consecutive checks (protects against concurrent electron-vite builds).
 */
export async function waitForPorpitaBuildReady(porpitaRoot, timeoutMs = 45000) {
  const resolvedRoot = path.resolve(porpitaRoot)
  const deadline = Date.now() + timeoutMs
  let prevSig = null
  while (Date.now() < deadline) {
    try {
      const sig = getBuildEntryStats(resolvedRoot)
      if (sig && sig === prevSig) {
        return true
      }
      prevSig = sig
    } catch {
      prevSig = null
    }
    await sleep(250)
  }
  const finalSig = getBuildEntryStats(resolvedRoot)
  if (!finalSig) {
    throw new Error(
      `Porpita build artifacts in ${path.join(resolvedRoot, 'out')} not ready within ${timeoutMs}ms`
    )
  }
  return true
}

/**
 * Zero-install module resolution via createRequire(path.join(porpitaRoot, 'package.json')).
 * Resolves playwright and electron directly from Porpita's pnpm store without duplicating node_modules.
 */
export function loadPorpitaDeps(porpitaRoot) {
  const resolvedRoot = path.resolve(porpitaRoot)
  if (cache.has(resolvedRoot)) {
    return cache.get(resolvedRoot)
  }
  const pkgPath = path.join(resolvedRoot, 'package.json')
  if (!existsSync(pkgPath)) {
    throw new Error(`Porpita package.json not found at ${pkgPath}`)
  }
  const mainEntry = path.join(resolvedRoot, 'out', 'main', 'index.js')
  if (!existsSync(mainEntry)) {
    throw new Error(`Porpita built main entry not found at ${mainEntry}`)
  }
  const req = createRequire(pkgPath)
  const playwright = req('playwright')
  const electronExe = req('electron')
  if (!playwright?._electron) {
    throw new Error('Failed to resolve playwright._electron from Porpita package.json')
  }
  if (typeof electronExe !== 'string' || !existsSync(electronExe)) {
    throw new Error(`Resolved electron executable not found: ${String(electronExe)}`)
  }
  const deps = {
    porpitaRoot: resolvedRoot,
    mainEntry,
    playwright,
    _electron: playwright._electron,
    electronExe,
    requireFromPorpita: req
  }
  cache.set(resolvedRoot, deps)
  return deps
}
