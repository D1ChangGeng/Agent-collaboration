const assert = require('node:assert/strict')
const { createRequire } = require('node:module')
const fs = require('node:fs')
const path = require('node:path')

const [source, out] = process.argv.slice(2).map(p => path.resolve(p))
const load = createRequire(path.join(source, 'package.json'))
const { chromium } = load('playwright')
const server = new URL(JSON.parse(fs.readFileSync(path.join(source, '.cache/fixtures/server.json'), 'utf8')).url)
assert.equal(server.hostname, '127.0.0.1')

async function main() {
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  const page = await browser.newPage({ viewport: { width: 1040, height: 520 }, deviceScaleFactor: 1 })
  page.setDefaultTimeout(6500)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const results = []
  fs.mkdirSync(out, { recursive: true })
  const label = '[aria-label^="Choose group:"]'
  const strip = '[data-shape-group]'
  const choose = () => page.locator(label)
  const list = () => page.getByRole('button', { name: 'Open work', exact: true })
  const shot = async (name, width, height) => {
    await page.screenshot({
      path: path.join(out, name+'.png'), animations: 'disabled', clip: { x: 0, y: 0, width, height }
    })
  }
  async function open(id, theme, reducedMotion = 'no-preference') {
    await page.emulateMedia({ reducedMotion })
    if (page.url() === 'about:blank') {
      await page.goto(new URL('/fixtures.html?worker=1', server).href, {
        waitUntil: 'domcontentloaded', timeout: 30000
      })
    }
    await page.waitForFunction(() => !!window.__orcaComponentFixtureHost, null, { timeout: 25000 })
    await page.evaluate(
      ([fixture, mode]) => window.__orcaComponentFixtureHost.render('tab-bar/PorpitaGroupSelectorShape:'+fixture, mode),
      [id, theme]
    )
    await page.waitForFunction(() => ['ready', 'error'].includes(document.documentElement.dataset.fixtureState))
    const error = await page.locator('html').getAttribute('data-fixture-error')
    assert.equal(error, null)
    await page.evaluate(() => document.fonts.ready)
  }
  async function current() {
    const row = page.locator(strip)
    return { group: await row.getAttribute('data-shape-group'), active: await row.getAttribute('data-shape-active') }
  }
  async function expectCurrent(group, active) {
    await page.waitForFunction(([g, a]) => {
      const row = document.querySelector('[data-shape-group]')
      return row?.dataset.shapeGroup === g && row.dataset.shapeActive === a
    }, [String(group), active])
  }
  async function record(id, action) {
    try {
      await action()
      results.push({ id, status: 'verified', ...await current() })
      console.log(id, results.at(-1).group, results.at(-1).active)
    } catch (error) {
      results.push({ id, status: 'failed', ...await current(), detail: String(error).split('\n')[0] })
      await shot('failed-interaction', 952, 400)
      throw error
    }
  }
  async function chooseWithKeyboard(arrow, destination) {
    await choose().focus()
    await page.keyboard.press('ArrowDown')
    await page.getByRole('menuitemradio', { name: destination }).waitFor()
    await page.keyboard.press(arrow)
    await page.waitForFunction(name => document.activeElement?.textContent?.trim() === name, destination)
    await page.keyboard.press('Enter')
  }
  try {
    for (const [id, width, count, groups, theme] of [
      ['small', 240, 1, 1, 'light'],
      ['compact', 420, 8, 4, 'light'],
      ['dense', 920, 30, 12, 'dark'],
      ['compactDense', 240, 30, 12, 'dark']
    ]) {
      await open(id, theme)
      await record(id, async () => {
        const metrics = await page.locator(strip).evaluate(row => {
          const tabStrip = row.querySelector('.terminal-tab-strip')
          const chooser = row.querySelector('[aria-label^="Choose group:"]')
          const active = row.querySelector('[data-tab-id][data-active="true"]')
          const tabRect = tabStrip.getBoundingClientRect(), activeRect = active.getBoundingClientRect()
          return {
            width: row.offsetWidth, chooser: chooser.offsetWidth, tabs: row.querySelectorAll('[data-tab-id]').length,
            stripWidth: tabStrip.clientWidth, stripScrollWidth: tabStrip.scrollWidth,
            activeVisible: Math.max(0, Math.round(Math.min(tabRect.right, activeRect.right) - Math.max(tabRect.left, activeRect.left)))
          }
        })
        assert.equal(metrics.width, width)
        assert.equal(metrics.tabs, count)
        assert.ok(metrics.chooser <= 132 && metrics.activeVisible > 70)
        if (count > 1) assert.ok(metrics.stripScrollWidth > metrics.stripWidth)
        await choose().focus()
        await page.keyboard.press('ArrowDown')
        assert.equal(await page.getByRole('menuitemradio').count(), groups)
        await page.keyboard.press('Escape')
        await page.waitForFunction(selector => document.activeElement?.matches(selector), label)
        results.push({ id: id+'-geometry', ...metrics, groups, theme })
      })
    }
    await open('compact', 'light')
    await record('keyboard-switch-and-restore', async () => {
      await page.locator('[data-tab-id="work-0-1"]').click()
      await expectCurrent(0, 'work-0-1')
      await chooseWithKeyboard('End', '一般工作')
      await expectCurrent(3, 'work-3-0')
      await chooseWithKeyboard('Home', 'Porpita · 桌面端国际化与交付验收')
      await expectCurrent(0, 'work-0-1')
    })
    await open('compactDense', 'dark', 'reduce')
    await record('keyboard-overflow-and-reveal', async () => {
      assert.equal(await page.getByRole('button', { name: /Scroll tabs/ }).count(), 0)
      await list().focus()
      await page.keyboard.press('Enter')
      const offscreenTab = page.locator('[data-shape-work-id="work-0-29"]')
      await offscreenTab.focus()
      await page.keyboard.press('Enter')
      await expectCurrent(0, 'work-0-29')
      await page.waitForFunction(() => {
        const strip = document.querySelector('.terminal-tab-strip')
        const active = strip.querySelector('[data-tab-id="work-0-29"]')
        const outer = strip.getBoundingClientRect(), inner = active.getBoundingClientRect()
        return strip.scrollLeft > 0 && inner.left >= outer.left - 2 && inner.left < outer.right
      })
      await shot('keyboard-overflow', 272, 84)
    })
    await open('compact', 'light')
    const drag = async (id, cancel) => {
      const sourceBox = await page.locator(`[data-tab-id="${id}"]`).boundingBox()
      const targetBox = await choose().boundingBox()
      assert.ok(sourceBox && targetBox)
      await page.mouse.move(sourceBox.x + 18, sourceBox.y + sourceBox.height / 2)
      await page.mouse.down()
      await page.mouse.move(targetBox.x + targetBox.width / 2, targetBox.y + targetBox.height / 2, { steps: 18 })
      await page.waitForFunction(selector => document.querySelector(selector)?.dataset.shapeHighlight === 'true', label)
      if (cancel) await page.keyboard.press('Escape')
      await page.mouse.up()
    }
    await record('pointer-cancel', async () => {
      await drag('work-0-0', true)
      assert.equal(await page.locator(strip).getAttribute('data-shape-move'), '')
      assert.equal(await page.getByRole('menuitemradio').count(), 0)
      await expectCurrent(0, 'work-0-0')
    })
    await record('pointer-drop-then-choose', async () => {
      await drag('work-0-0', false)
      await page.getByRole('menuitemradio', { name: 'ACS', exact: true }).waitFor()
      assert.equal(await page.locator(strip).getAttribute('data-shape-move'), 'work-0-0')
      await shot('drop-destination', 452, 188)
      await page.getByRole('menuitemradio', { name: 'ACS', exact: true }).click()
      await expectCurrent(0, 'work-0-1')
      await choose().click()
      await page.getByRole('menuitemradio', { name: 'ACS', exact: true }).click()
      await expectCurrent(1, 'work-1-0')
      await page.locator('[data-tab-id="work-0-0"]').waitFor()
    })
    await record('keyboard-move-to-group', async () => {
      await list().focus()
      await page.keyboard.press('Enter')
      await page.getByRole('menuitem', { name: 'Move current tab to group' }).focus()
      await page.keyboard.press('Enter')
      const destination = page.getByRole('menuitemradio', { name: 'Remote lab', exact: true })
      await destination.focus()
      await page.keyboard.press('Enter')
      await expectCurrent(1, 'work-0-0')
      await page.getByRole('status').filter({ hasText: /Moved ACS.* to Remote lab/ }).waitFor()
    })
    assert.deepEqual(errors, [])
  } finally {
    fs.writeFileSync(path.join(out, 'interaction.json'), JSON.stringify({ engine: browser.version(), results, errors }, null, 2)+'\n')
    await browser.close()
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
