const { createRequire } = require('node:module')
const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')

const source = process.env.PORPITA_SPEC_SOURCE || 'D:/Chatgpt/Porpita'
const load = createRequire(path.join(source, 'package.json'))
const { _electron } = load('playwright')
const executablePath = process.env.PORPITA_SPEC_EXE || path.join(os.homedir(), 'AppData/Local/Programs/porpita/Porpita.exe')
const developmentEntry = process.env.PORPITA_SPEC_ENTRY || null
const runtimeKind = developmentEntry ? 'isolated source build' : 'installed app'
const output = process.argv[2]
const workbenchOnly = process.argv.includes('--workbench')
const completedOnboarding = process.argv.includes('--completed-profile')
const spaceBranchReview = process.argv.includes('--space-branch-review')
const spaceRemoteBranches = process.argv.includes('--space-remote-branches')
const spaceSshRecovery = process.argv.includes('--space-ssh-recovery')
const spacePhysicalPorpita = process.argv.includes('--space-physical-porpita')
const wslDistro = spaceBranchReview ? process.env.PORPITA_SPEC_WSL_DISTRO : undefined
const settingsCensus = process.argv.includes('--settings-census')
const toolsExtra = process.argv.includes('--tools-extra')
const episodeOnly = process.argv.includes('--episode')
const gitOnly = process.argv.includes('--git')
const chatOnly = process.argv.includes('--chat')
const connectionOnly = process.argv.includes('--connection')
const restartOnly = process.argv.includes('--restart')
const auxiliaryOnly = process.argv.includes('--auxiliary')
const closeout = process.argv.includes('--closeout')
const coreRecovery = process.argv.includes('--core-recovery')
const sessionSearchBaseline = process.argv.includes('--session-search-baseline')
const sessionSearch = sessionSearchBaseline || process.argv.includes('--session-search')
const sessionHistoryBaseline = process.argv.includes('--session-history-baseline')
const sessionHistory = sessionHistoryBaseline || process.argv.includes('--session-history')
const hostSearchBaseline = process.argv.includes('--host-search-baseline')
const hostDirectory = process.argv.includes('--sidebar-host-directory')
const workspacePortsFocused = process.argv.includes('--workspace-ports-focused')
const workspacePortsContinuity = workspacePortsFocused || process.argv.includes('--workspace-ports-continuity')
const workspaceUsageContinuity = workspacePortsContinuity || process.argv.includes('--workspace-usage-continuity')
const workspaceExplorerContinuity = workspaceUsageContinuity || process.argv.includes('--workspace-explorer-continuity')
const workspaceHostContinuity = workspaceExplorerContinuity || process.argv.includes('--workspace-host-continuity')
const hostSearch = hostSearchBaseline || hostDirectory || workspaceHostContinuity || process.argv.includes('--host-search')
const relatedSpec = ['index', 'split', 'explorer'].find((mode) => process.argv.includes(`--related-${mode}`))
const relatedBaseline = process.argv.includes('--related-baseline')
const workspaceContinuity = process.argv.includes('--workspace-continuity')
const sidebarHistory = process.argv.includes('--sidebar-unopened-history')
const sidebarRunState = process.argv.includes('--sidebar-run-state')
const sidebarSessionIndex = sidebarHistory || process.argv.includes('--sidebar-session-index')
const workspacePreview = workspaceContinuity || sidebarSessionIndex || process.argv.includes('--workspace-preview')
const previewDisabled = process.argv.includes('--workspace-preview-disabled')
const navigationReplay = spaceBranchReview || spaceRemoteBranches || spaceSshRecovery || spacePhysicalPorpita || sessionSearch || sessionHistory || hostSearch || workspacePreview ||
  sidebarRunState || previewDisabled || relatedSpec !== undefined
if (!output) throw new Error('Provide an evidence directory')
fs.mkdirSync(output, { recursive: true })
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'porpita-ui-spec-'))
const userData = path.join(temporary, 'profile')
const home = path.join(userData, 'home')
const wslFixture = wslDistro ? require('./observe-space-wsl-fixture.cjs').prepareSpaceWslFixture(wslDistro) : null
const repo = wslFixture?.repo ?? path.join(temporary, workspaceExplorerContinuity ? 'Release-review' : 'UI-spec-sample')
const sessionFolder = path.join(temporary, 'UI-spec-folder')
for (const dir of [path.join(home, 'AppData/Local'), path.join(home, 'AppData/Roaming'), repo]) fs.mkdirSync(dir, { recursive: true })
const env = Object.fromEntries(Object.entries(process.env).filter(([key,value]) =>
  value !== undefined && !/^(HOME|USERPROFILE|HOMEDRIVE|HOMEPATH|APPDATA|LOCALAPPDATA|CLAUDE_CONFIG_DIR|ELECTRON_RUN_AS_NODE|ORCA_.*|PORPITA_.*|ACS_.*|CODEX_.*|OPENAI_.*|ANTHROPIC_.*|GH_.*|GITHUB_.*|GITLAB_.*|AWS_.*|AZURE_.*)$/i.test(key)
))
Object.assign(env, {
  HOME: home, USERPROFILE: home,
  APPDATA: path.join(home, 'AppData/Roaming'), LOCALAPPDATA: path.join(home, 'AppData/Local'),
  ORCA_BACKGROUND_LAUNCH: '1', ORCA_E2E_HEADLESS: '1',
  ORCA_E2E_USER_DATA_DIR: userData, ORCA_E2E_HOME_DIR: home,
  GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: path.join(home,'gitconfig'),
  LANG: 'en_US.UTF-8'
})
const write = (name, value) => fs.writeFileSync(path.join(output,name), JSON.stringify(value,null,2)+'\n')
const delay = (ms) => new Promise(resolve=>setTimeout(resolve,ms))
let physicalFixture
const sanitize = t => {
  const masked = String(t).replaceAll(temporary, '<isolated>').replaceAll(temporary.replaceAll('\\','/'),'<isolated>').replaceAll(os.homedir(),'<home>')
  return physicalFixture?.redact(masked) ?? masked
}
function seedRepo(){
  const git = (...args) => wslFixture ? wslFixture.git(repo, ...args) :
    execFileSync('git',args,{cwd:repo,env,windowsHide:true,stdio:['ignore','pipe','pipe']})
  git('init','-q','-b','main')
  fs.writeFileSync(path.join(repo,'notes.md'),'# Design sample\n\nA disposable workbench note.\n')
  fs.writeFileSync(path.join(repo,'preview.html'),'<!doctype html><title>UI Spec Preview</title><h1>UI Spec Preview</h1>')
  git('add','.')
  git('-c','user.name=Porpita UI Spec','-c','user.email=ui-spec@example.invalid','-c','commit.gpgsign=false','commit','-qm','Seed sample')
  fs.appendFileSync(path.join(repo,'notes.md'),'\nChanged in test repository.\n')
}
async function main() {
  seedRepo()
  const historyReplay = sessionHistory ? require('./observe-session-history.cjs') : null
  const hostReplay = hostSearch ? require('./observe-host-search.cjs') : null
  const remoteBranchReplay = spaceRemoteBranches ? require('./observe-space-remote-checkout.cjs') : null
  const sshRecoveryReplay = spaceSshRecovery ? require('./observe-space-ssh-recovery.cjs') : null
  const physicalReplay = spacePhysicalPorpita ? require('./observe-physical-porpita.cjs') : null
  physicalFixture = await physicalReplay?.configure({ source, temporary, home, repo, env })
  const relatedReplay = relatedSpec ? require('./observe-related-workspace.cjs') : null
  const previewReplay = workspacePreview ? require('./observe-workspace-preview.cjs') : null
  const runStateReplay = sidebarRunState ? require('./observe-session-index-run-state.cjs') : null
  const runStateFixture = runStateReplay?.configure({ temporary, source, env })
  const historyFixtures = (remoteBranchReplay ?? hostReplay ?? historyReplay ?? relatedReplay ?? previewReplay)?.seed({
    home, repo, folder: sessionFolder, temporary, mode: relatedSpec, sidebarSessionIndex, sidebarHistory,
    workspaceExplorerContinuity, workspacePortsFocused
  })
  if (sessionSearch || workspacePreview || relatedSpec === 'explorer') {
    fs.mkdirSync(sessionFolder)
    fs.writeFileSync(path.join(sessionFolder,'notes.md'),
      relatedSpec === 'explorer' ? '# Local folder notes\n' : '# Session search fixture\n')
  }
  if (sessionSearch || workspacePreview) {
    const git = (...args) => execFileSync('git',args,{cwd:sessionFolder,env,windowsHide:true,stdio:['ignore','pipe','pipe']})
    git('init','-q','-b','main')
    git('add','notes.md')
    git('-c','user.name=Porpita UI Spec','-c','user.email=ui-spec@example.invalid','-c','commit.gpgsign=false','commit','-qm','Seed second project')
  }
  if (workbenchOnly || restartOnly || closeout) {
    fs.writeFileSync(path.join(home,'notes.md'), '# Local specimen\n\nDisposable editor text.\n')
    fs.writeFileSync(path.join(home,'preview.html'), '<!doctype html><title>Porpita specimen</title><h1>Local HTML specimen</h1>')
  }
  if (completedOnboarding || auxiliaryOnly || navigationReplay) {
    const specLocale = process.env.PORPITA_SPEC_LOCALE === 'zh' ? 'zh' : 'en'
    fs.writeFileSync(path.join(userData,'orca-data.json'), JSON.stringify({
      settings:{telemetry:{optedIn:false},showArtifactsButton:true,showSkillsButton:true,browserDefaultUrl:null,
        ...(spaceBranchReview || process.argv.includes('--resource-selection-continuity') ? {workspaceDir:path.join(path.dirname(repo),'managed-worktrees')} : {}),
        ...(navigationReplay ? {uiLanguage:specLocale, theme:specLocale === 'zh' ? 'dark' : 'light', agentDefaultSurface:'chat', nativeChatProviders:{codex:true}} : {}),
        ...(hostSearch || sidebarSessionIndex ? {aiVaultSearch: { enabled: !workspacePortsFocused, historyDays: null }} : {}),
        ...(auxiliaryOnly ? {experimentalAgentDashboardPopout:true,experimentalAgentDashboardMode:'popout',uiLanguage:'en'} : {})},
      onboarding:{flowVersion:4,closedAt:1,outcome:'completed',lastCompletedStep:5},
      ui:{contextualToursAutoEligible:false,browserImportHintHidden:true,codexTerminalServerIsolationNoticeSeen:true,hideDefaultBranchWorkspace:false}
    }))
  }
  const sshRecoveryFixture = sshRecoveryReplay?.seed(
    path.join(userData, 'orca-data.json'), process.env.PORPITA_SPEC_PHYSICAL_SSH_FIXTURE
  )
  physicalReplay?.seed(path.join(userData, 'orca-data.json'), physicalFixture)
  const launch = () => _electron.launch({ executablePath, env, cwd: temporary,
    args:['--force-device-scale-factor=1', ...(developmentEntry ? [developmentEntry] : [])],
    timeout: workspaceExplorerContinuity ? 60000 : 25000 })
  let app = await launch()
  const steps = []
  let state
  const tick = performance.now()
  const bounded = async (p,ms,msg) => {
    let timer
    try { return await Promise.race([p,new Promise((_,rej)=>{timer=setTimeout(()=>rej(new Error(msg)),ms)})]) }
    finally { clearTimeout(timer) }
  }
  try {
    let page = await app.firstWindow({ timeout: navigationReplay ? 65000 : 18000 })
    let win = await app.browserWindow(page)
    await page.waitForLoadState('domcontentloaded', { timeout: 28000 })
    await win.evaluate(w=>w.setContentSize(1280,800))
    state = await app.evaluate(({ app, BrowserWindow }) => ({
      home: app.getPath('home'), profile: app.getPath('userData'), version: app.getVersion(),
      electronVersion: process.versions.electron,
      windows: BrowserWindow.getAllWindows().map(w => ({ visible: w.isVisible(), focused: w.isFocused() }))
    }))
    if (path.resolve(state.home).toLowerCase() !== path.resolve(home).toLowerCase() ||
        path.resolve(state.profile).toLowerCase() !== path.resolve(userData).toLowerCase() ||
        !state.windows.length || state.windows.some(w => w.visible || w.focused)) throw new Error('Profile or window isolation failed')
    page.setDefaultTimeout(3500)
    await page.locator('body').waitFor({ timeout: 15000 })
    let cdp = await page.context().newCDPSession(page)
    let frame
    let sequence = null
    const frameReceiver = v=>{
      frame = v
      if(sequence && sequence.frames.length < 100) sequence.frames.push({
        data:v.data, rendererTimestamp:v.metadata.timestamp??null, receivedAtMs:performance.now()-tick
      })
      cdp.send('Page.screencastFrameAck',{sessionId:v.sessionId}).catch(()=>{})
    }
    const startFrames = async () => {
      cdp.on('Page.screencastFrame',frameReceiver)
      await cdp.send('Page.enable')
      await cdp.send('Page.startScreencast',{format:'jpeg',quality:88,maxWidth:1280,maxHeight:800,everyNthFrame:1})
    }
    await startFrames()
    const facts = () => page.evaluate(() => ({
      size:[innerWidth,innerHeight], dpr:devicePixelRatio, lang:document.documentElement.lang,
      userLocale:navigator.language, theme:document.documentElement.classList.contains('dark')?'dark':'light',
      motion:matchMedia('(prefers-reduced-motion: reduce)').matches?'reduce':'default',
      focus:document.activeElement?.getAttribute('aria-label')||document.activeElement?.textContent?.slice(0,120)||null,
      section:[...document.querySelectorAll('section[data-settings-section]')].map(x=>x.getAttribute('data-settings-section')),
      text:document.body.innerText.slice(0,8500),
      dialogs:[...document.querySelectorAll('[role=dialog]')].filter(x=>x.getClientRects().length).map(x=>x.innerText.slice(0,2200)),
      buttons:[...document.querySelectorAll('button,[role=tab],[role=menuitem]')].filter(b=>b.getClientRects().length).map(b=>({text:b.innerText, label:b.getAttribute('aria-label'),title:b.title, test:b.getAttribute('data-testid')})).slice(0,155)
    }))
    async function capture(id){
      await page.evaluate(async()=>{ await document.fonts.ready })
      const data=await facts()
      let imageMethod='CDP screenshot', imageFile=id+'.png'
      try {
        await page.screenshot({path:path.join(output,imageFile),scale:'css',timeout:3500})
      } catch {
        if (frame) {
          imageMethod='CDP screencast frame (timestamp may precede state snapshot)'
          imageFile=id+'.jpg'
          fs.writeFileSync(path.join(output,imageFile), Buffer.from(frame.data,'base64'))
        } else { imageMethod='no frame'; imageFile=null }
      }
      const sanitized=JSON.parse(JSON.stringify(data,(_key,value)=>typeof value==='string'?sanitize(value):value))
      write(id+'.json',{...sanitized, imageFile,imageMethod,offsetMs:Math.round(performance.now()-tick)})
      console.log(id, data.size.join('x'),data.section.join(','),data.dialogs.map(d=>d.split('\n')[0]).join('|'))
    }
    const button = (name) => page.getByRole('button',{name,exact:typeof name==='string'}).first()
    const click = name => button(name).click()
    async function step(id, trigger, action, assertion){
      const start=performance.now()
      try {
        await action()
        if(assertion) await assertion()
        await delay(330)
        await capture(id)
        steps.push({id,trigger,elapsedMs:Math.round(performance.now()-start),result:'captured'})
      } catch(e) {
        steps.push({id,trigger,result:'not reached',reason:sanitize(e.message).split('\n').slice(0,11).join('\n')})
        console.log(id,'not reached',sanitize(e.message).split('\n')[0])
      }
    write('run.json',{version:state.version,windowIsolation:state.windows,profile:completedOnboarding||navigationReplay?'disposable, seeded completed onboarding':'disposable, fresh',source:runtimeKind,steps})
    }
    async function episode(id, actions) {
      sequence = {frames:[], actions:[]}
      if(frame) sequence.frames.push({data:frame.data,rendererTimestamp:frame.metadata.timestamp??null,receivedAtMs:performance.now()-tick})
      try {
        for (const [name,run] of actions) {
          const startMs = performance.now()-tick
          await run()
          sequence.actions.push({name,startMs,endMs:performance.now()-tick})
        }
      } finally {
        const episodeDir = path.join(output,id)
        fs.mkdirSync(episodeDir,{recursive:true})
        const {actions,frames}=sequence
        sequence=null
        const timeline=frames.map(({data,...entry},i)=>{
          const file=String(i).padStart(3,'0')+'.jpg'
          fs.writeFileSync(path.join(episodeDir,file),Buffer.from(data,'base64'))
          return {...entry,file}
        })
        fs.writeFileSync(path.join(episodeDir,'timeline.json'),JSON.stringify({actions,frames:timeline,limits:'CDP frames sampled on hidden Windows renderer. Receiver time includes capture and transport; frame count is not FPS.'},null,2)+'\n')
      }
    }
    if (!completedOnboarding && !auxiliaryOnly && !navigationReplay) {
      await page.getByRole('heading',{name:/How do you want to work with agents|如何.*智能体/i}).first().waitFor({timeout:12000}).catch(()=>{})
      await delay(1100)
      await step('02-onboarding','fresh isolated launch',async()=>{},()=>button(/稍后设置|Set up later/i).waitFor())
      await step('03-onboarding-skip','Set up later or Esc',async()=>{
        if(await button(/稍后设置|Set up later/i).count()) await click(/稍后设置|Set up later/i)
        else await page.keyboard.press('Escape')
      })
      if(await page.getByRole('dialog').count()) {
        const skip = page.getByRole('dialog').getByRole('button',{name:/^跳过$|^Skip$/i}).first()
        if(await skip.count()) await skip.click().catch(()=>{})
      }
    }
    if (closeout) {
      await require('./observe-closeout.cjs')({
        page, win, app, click, button, step, steps, write, delay, repo, phase: 'trust'
      })
    }
    async function dismissStartupPrompts(){
      for(let attempt=0;attempt<6;attempt++){
        let dismissed=false
        for(const name of [/让智能体询问|Let agents ask|Ask in agent/i,/跳过导览|Skip tour|Close tour/i]) {
          const target=button(name)
          if (await target.isVisible()) {
            await target.click().catch(()=>{})
            dismissed=true
          }
        }
        if(!dismissed && attempt>=2) break
        await delay(300)
      }
    }
    await delay(1600)
    await dismissStartupPrompts()
    if(await button(/继续使用终端|Keep using terminal/i).isVisible()) await click(/继续使用终端|Keep using terminal/i).catch(()=>{})
    async function restartWorkspaceDesktop() {
      const child = app.process()
      const exited = new Promise(resolve => child.once('exit', resolve))
      await cdp.send('Page.stopScreencast').catch(() => {})
      await cdp.detach().catch(() => {})
      await app.evaluate(({ app }) => { setTimeout(() => app.quit(), 100) }).catch(() => {})
      if ((await bounded(exited, 22000, 'Desktop quit did not finish')) !== 0) {
        throw new Error('Desktop quit did not exit cleanly')
      }
      app = await launch()
      if (app.process().pid === child.pid) throw new Error('Expected a new desktop process')
      page = await app.firstWindow({ timeout: 35000 })
      await page.waitForLoadState('domcontentloaded', { timeout: 28000 })
      win = await app.browserWindow(page)
      await win.evaluate(w => w.setContentSize(1280, 800))
      const restarted = await app.evaluate(({ app, BrowserWindow }) => ({
        profile: app.getPath('userData'), hidden: BrowserWindow.getAllWindows().every(w => !w.isVisible() && !w.isFocused())
      }))
      if (!restarted.hidden || path.resolve(restarted.profile).toLowerCase() !== path.resolve(userData).toLowerCase()) {
        throw new Error('Restarted desktop did not use the hidden isolated profile')
      }
      page.setDefaultTimeout(4500)
      cdp = await page.context().newCDPSession(page)
      frame = null
      await startFrames()
      return { app, page, win }
    }
    if (previewDisabled) {
      await step('preview-disabled', 'Verify the regular desktop shell with the Workspace and sidebar Sessions preview flag unset', async () => {
        await page.locator('[data-contextual-tour-target=sidebar-navigation] button').first().waitFor({ timeout: 20000 })
        if (await button(/^(Workspaces [(]preview[)]|工作空间（预览）)$/i).count() ||
            await page.locator('[data-workspace-preview],[data-session-index]').count() ||
            await page.locator('[data-worktree-sidebar-layout]').getByRole('button', { name: /^(Sessions|会话)$/ }).count()) {
          throw new Error('Preview UI is available without the build flag')
        }
      })
      if (steps.at(-1)?.result !== 'captured') throw new Error('Preview isolation check failed; see run.json')
      return
    }
    if (navigationReplay) {
      const countBefore = steps.length
      try {
        const replay = spacePhysicalPorpita ? physicalReplay.observe : spaceSshRecovery ? sshRecoveryReplay.observe : spaceRemoteBranches ? remoteBranchReplay.observe : workspaceHostContinuity ? hostReplay.observe :
          runStateReplay?.observe ?? previewReplay?.observe ?? relatedReplay?.observe ??
          hostReplay?.observe ?? historyReplay?.observe ?? require('./observe-session-search.cjs')
        await (spaceBranchReview ? require('./observe-space-branch-review.cjs').observeSpaceBranchReview : replay)({
          page, win, app, state, click, button, step, episode, write, repo, folder:sessionFolder,
          baseline: relatedSpec ? relatedBaseline : hostSearch ? hostSearchBaseline : sessionHistory ? sessionHistoryBaseline : sessionSearchBaseline,
          mode: relatedSpec,
          runtime: {electron: _electron, executablePath, developmentEntry, source, env, bounded, sanitize},
          fixtures: physicalFixture ?? sshRecoveryFixture ?? runStateFixture ?? historyFixtures, locale: process.env.PORPITA_SPEC_LOCALE === 'zh' ? 'zh' : 'en',
          gitForSpace: wslFixture?.git,
          continuity: workspaceContinuity, sidebarSessionIndex, sidebarHistory, hostDirectory,
          workspaceHostContinuity, workspaceExplorerContinuity, workspaceUsageContinuity,
          workspacePortsContinuity, workspacePortsFocused, userData, restartWorkspaceDesktop
        })
        if (steps.length === countBefore || steps.slice(countBefore).some(({result}) => result !== 'captured')) {
          throw new Error('At least one session navigation assertion failed; see run.json')
        }
      } finally {
        await cdp.send('Page.stopScreencast').catch(()=>{})
        await cdp.detach().catch(()=>{})
      }
      return
    }
    if (closeout || coreRecovery) {
      await require('./observe-closeout.cjs')({
        page, win, app, click, button, step, steps, write, delay, repo,
        phase: closeout ? 'workbench' : 'core'
      })
      await cdp.send('Page.stopScreencast').catch(()=>{})
      await cdp.detach().catch(()=>{})
      if (steps.filter(row=>row.id.startsWith('i2-')).some(row=>row.result!=='captured')) {
        throw new Error('At least one iteration-2 assertion failed; see run.json')
      }
      return
    }
    if(auxiliaryOnly) {
      async function openAuxiliary(id, trigger, open, file) {
        const mainPage=page, mainCdp=cdp, mainFrame=frame
        let auxCdp
        try {
          await step(id,trigger,async()=>{
            const existing = new Set(app.windows())
            const [created] = await Promise.all([
              app.waitForEvent('window',{predicate:w=>!existing.has(w),timeout:10000}),
              open()
            ])
            page=created
            await page.waitForLoadState('domcontentloaded',{timeout:20000})
            if(!new URL(page.url()).pathname.endsWith('/'+file)) throw new Error('Unexpected auxiliary renderer')
            const auxiliary=await app.browserWindow(page)
            const hidden=await auxiliary.evaluate(w=>!w.isVisible()&&!w.isFocused())
            if(!hidden) throw new Error('Auxiliary renderer is not hidden')
            await auxiliary.evaluate(w=>w.setContentSize(1100,700))
            cdp=await page.context().newCDPSession(page)
            auxCdp=cdp
            frame=null
            await startFrames()
          },()=>page.locator('body').waitFor())
        } finally {
          if(auxCdp) {
            await auxCdp.send('Page.stopScreencast').catch(()=>{})
            await auxCdp.detach().catch(()=>{})
          }
          page=mainPage; cdp=mainCdp; frame=mainFrame
        }
      }
      await openAuxiliary('53-space-window','Resource Manager > Space > Review',async()=>{
        const resource=button(/资源管理器|Resource Manager/i)
        await resource.waitFor({timeout:10000})
        await resource.click()
        const popover=page.locator('[data-slot=popover-content]').filter({hasText:/Workspace disk|Space|空间/i}).first()
        await popover.waitFor({timeout:8500})
        await popover.getByRole('button',{name:/^(查看|审查|评审|审阅|检查|审核|复核|Review)$/i}).last().click({timeout:8500})
      },'space.html')
      await page.keyboard.press('Escape')
      await openAuxiliary('54-dashboard-window','Open the seeded Agent Dashboard sidebar entry in pop-out mode',
        ()=>click(/智能体仪表盘|Agent Dashboard/i),'popout.html')
      await cdp.send('Page.stopScreencast').catch(()=>{})
      await cdp.detach().catch(()=>{})
      return
    }
    if(restartOnly) {
      await step('50-before-restart','Open a Markdown file from Explorer before ordinary Quit',async()=>{
        await page.getByText('notes.md',{exact:true}).first().dblclick()
      },()=>page.getByText('Disposable editor text.',{exact:true}).waitFor({timeout:10000}))
      if(steps.at(-1)?.result!=='captured') throw new Error('Restart fixture did not reach its initial editor')
      const quit = app.evaluate(({app})=>{ setTimeout(()=>app.quit(),100) })
      await quit.catch(()=>{})
      const exitCode=await bounded(new Promise(resolve=>{
        const child=app.process()
        if(child.exitCode!==null) resolve(child.exitCode)
        else child.once('exit',(code)=>resolve(code))
      }),20000,'Ordinary Electron quit did not settle')
      if(exitCode!==0) throw new Error('Ordinary Electron quit ended with exit code '+exitCode)
      await step('51-after-restart','Reopen the same isolated profile and verify active editor',async()=>{
        app=await launch()
        page=await app.firstWindow({timeout:20000})
        await page.waitForLoadState('domcontentloaded',{timeout:24000})
        win=await app.browserWindow(page)
        await win.evaluate(w=>w.setContentSize(1280,800))
        const windowState=await app.evaluate(({app,BrowserWindow})=>({profile:app.getPath('userData'),
          safe:BrowserWindow.getAllWindows().every(w=>!w.isVisible()&&!w.isFocused())}))
        if(!windowState.safe||path.resolve(windowState.profile).toLowerCase()!==path.resolve(userData).toLowerCase()) throw new Error('Restart profile or window isolation failed')
        page.setDefaultTimeout(4500)
        cdp=await page.context().newCDPSession(page)
        frame=null
        await startFrames()
      },()=>page.getByText('Disposable editor text.',{exact:true}).waitFor({timeout:12000}))
      await step('52-resume-editor','Dismiss optional feature tip and return to restored document',async()=>{
        const tip=page.getByRole('dialog').filter({hasText:/搜索所有智能体会话|Search every agent session/i}).first()
        if(await tip.isVisible()) await tip.getByRole('button',{name:/关闭|Close/i}).first().click()
      },async()=>{
        await page.getByRole('dialog').first().waitFor({state:'hidden'})
        await page.getByText('Disposable editor text.',{exact:true}).waitFor()
      })
      await cdp.send('Page.stopScreencast').catch(()=>{})
      await cdp.detach().catch(()=>{})
      return
    }
    if(connectionOnly) {
      await step('44-source-collaboration','Open current build Collaboration without configuring Core',()=>click(/协作消息|Collaboration messages|^Collaboration$/i),
        ()=>page.getByRole('dialog').filter({hasText:/协作消息|Collaboration/i}).first().waitFor({timeout:10000}))
      await page.keyboard.press('Escape')
      await dismissStartupPrompts()
      await step('45-source-general','Open current build General settings',()=>click(/^(设置|Settings)$/),
        ()=>page.locator('section[data-settings-section=general]').first().waitFor({timeout:10000}))
      await click(/返回应用|Back to app/i).catch(()=>{})
      await step('46-source-mobile','Open the current build Mobile pairing entry',()=>click(/Porpita 手机端|Porpita Mobile|Orca Mobile/i),
        ()=>page.getByRole('heading',{name:/Pair a device|配对.*设备/i}).first().waitFor({timeout:10000}))
      await cdp.send('Page.stopScreencast').catch(()=>{})
      await cdp.detach().catch(()=>{})
      return
    }
    if(chatOnly) {
      await step('40-chat-enabled','Enable Chat UI from settings in the disposable profile',async()=>{
        await click(/^(设置|Settings)$/)
        await click(/^(聊天界面|Chat UI)$/i)
        await page.locator('section[data-settings-section=chat]').getByRole('button',{name:/^(开启|Enable|Turn on)$/i}).first().click()
      })
      await click(/返回应用|Back to app/i).catch(()=>{})
      await step('41-chat-agent-menu','Open New Tab and reveal Codex launch modes',async()=>{
        await click(/^(新标签页|New tab)$/i)
        await page.getByRole('menuitem').filter({hasText:/^Codex(?:\s|$)/}).first().waitFor({timeout:8000})
      })
      await step('42-chat-empty','Choose the Chat launch mode; do not send a message',async()=>{
        const row=page.getByRole('menuitem').filter({hasText:/^Codex(?:\s|$)/}).first()
        const nested=row.getByRole('button',{name:/Codex.*(?:Chat|聊天)|(?:Chat|聊天).*Codex/i}).first()
        const explicit=page.getByRole('menuitem',{name:/Codex.*(?:Chat|聊天)|(?:Chat|聊天).*Codex/i}).first()
        if(await explicit.isVisible()) await explicit.click()
        else if(await nested.isVisible()) await nested.click()
        else await row.click()
        const submenu=page.getByRole('menuitem',{name:/^聊天$|^Chat UI$|Open in Chat|在聊天中打开/i}).first()
        if(await submenu.isVisible()) await submenu.click()
        const start=button(/启动聊天|Launch chat|开始聊天/i)
        if(await start.isVisible()) await start.click()
        await dismissStartupPrompts()
      },()=>page.locator('[data-native-chat-root=true]').first().waitFor({timeout:10000}))
      await cdp.send('Page.stopScreencast').catch(()=>{})
      await cdp.detach().catch(()=>{})
      return
    }
    if(gitOnly) {
      await app.evaluate(({dialog},fixture)=> {
        // Only the OS folder choice is supplied by the harness. App intake and
        // validation are driven by the real Add Project control.
        dialog.showOpenDialog=async()=>({canceled:false,filePaths:[fixture]})
      },repo)
      await step('37-git-worktree','Add Project > Browse folder; picker supplies disposable repository',async()=>{
        await click(/^(添加项目|Add project)$/i)
        await click(/浏览文件夹|Browse folder/i)
        await delay(1500)
        const tip=button(/^(知道了|Got it)$/i)
        if(await tip.isVisible()) await tip.click().catch(()=>{})
        await dismissStartupPrompts()
      },()=>button(/^(源代码管理|源代码控制|Source Control)/i).waitFor({timeout:9000}))
      await step('37a-content-search','Use Explorer content search in the disposable Git checkout',async()=>{
        const content=page.getByText(/^(内容|Content)$/i).first()
        await content.click()
        const field=page.locator('[data-file-search-input=true]').first()
        await field.fill('Changed in test repository')
        await field.press('Enter')
      },()=>page.getByText(/Changed in test repository/).first().waitFor({timeout:8000}))
      await step('37b-vault','Open the Agents history dock without an account',()=>click(/^(智能体|Agents)(?:\s|$)/i))
      await step('37c-checks','Open Checks for the temporary repository',()=>click(/^(检查项|检查|Checks)(?:\s|$|\()/i))
      await step('38-git-changes','Open Source Control and wait for the modified fixture file',()=>click(/^(源代码管理|源代码控制|Source Control)/i),
        ()=>page.getByText('notes.md',{exact:true}).first().waitFor({timeout:9000}))
      await step('39-git-diff','Open the fixture diff from the changes list',()=>page.getByText('notes.md',{exact:true}).last().click(),
        ()=>page.locator('.monaco-diff-editor').first().waitFor({timeout:9000}))
      await step('39a-project-settings','Visit the registered fixture project settings',async()=>{
        await click(/^(设置|Settings)$/)
        await page.locator('aside button').getByText('UI-spec-sample',{exact:true}).first().click({timeout:8000})
      },()=>page.locator('section[data-settings-section^=repo-]').first().waitFor({timeout:8000}))
      await cdp.send('Page.stopScreencast').catch(()=>{})
      await cdp.detach().catch(()=>{})
      return
    }
    if(episodeOnly) {
      await step('30-theme','Select the Dark appearance control',async()=>{
        await click(/^(设置|Settings)$/)
        await click(/^(外观|Appearance)$/)
        await page.locator('section[data-settings-section=appearance]').getByText(/^(深色|Dark)$/).first().click()
      },()=>page.waitForFunction(()=>document.documentElement.classList.contains('dark')))
      await click(/返回应用|Back to app/i).catch(()=>{})
      await step('34-dock-episode','Close, open, and rapidly reverse the dock via its toggle',async()=>{
        const toggle=button(/切换右侧边栏|Toggle right sidebar/i)
        await toggle.waitFor({timeout:9000})
        const clickToggle=()=>toggle.click()
        await episode('dock-episode',[
          ['hold current view',()=>delay(200)],
          ['toggle closed',clickToggle],
          ['allow closed frame',()=>delay(350)],
          ['toggle open',clickToggle],
          ['short hold',()=>delay(70)],
          ['reverse toggle',clickToggle],
          ['allow settled frame',()=>delay(700)],
        ])
      })
      await step('35-activity','Open activity via the sidebar activity button',()=>click(/查看活动|View activity/i))
      await step('36-board','Open the Worktree board',()=>click(/工作区看板|Workspace board/i))
      await page.keyboard.press('Escape')
      await cdp.send('Page.stopScreencast').catch(()=>{})
      await cdp.detach().catch(()=>{})
      return
    }
    if(settingsCensus) {
      await click(/^(设置|Settings)$/)
      await page.locator('section[data-settings-section]').first().waitFor({timeout:15000})
      const nav = page.locator('aside button').filter({visible:true})
      const navLabels = (await nav.allTextContents()).map(x=>x.trim()).filter(Boolean)
      const visited = new Set()
      for(const [index,label] of navLabels.entries()){
        if(visited.has(label) || /返回应用|Back to app|^~$/.test(label)) continue
        visited.add(label)
        const el = nav.getByText(label,{exact:true}).first()
        const btn = nav.filter({hasText:label}).first()
        await step('setting-'+String(index).padStart(2,'0'),'Settings navigation: '+label,async()=>{
          if(await el.count()) await el.click({timeout:4000})
          else await btn.click({timeout:4000})
        },()=>page.locator('aside button[aria-current="page"]').first().waitFor())
      }
      await cdp.send('Page.stopScreencast').catch(()=>{})
      await cdp.detach().catch(()=>{})
      return
    }
    await step('04-shell','Dismiss contextual tour; leave trust to the agent',async()=>{},()=>button(/^(新标签页|New tab)$/i).waitFor({timeout:10000}))
    if (!workbenchOnly) {
    await step('05-collaboration-unconfigured','Collaboration titlebar button',()=>click(/协作消息|Collaboration messages/i),
      ()=>page.getByRole('dialog').first().waitFor())
    await page.keyboard.press('Escape')
    await step('06-settings','Settings button',()=>click(/^(设置|Settings)$/),()=>page.locator('section[data-settings-section]').first().waitFor())
    const desired = {
      '07-general':[/^(通用|常规|General)$/,'general'],
      '08-appearance':[/^(外观|Appearance)$/,'appearance'],
      '09-settings-shortcuts':[/^(快捷键|Keyboard shortcuts|Shortcuts)$/i,'shortcuts'],
      '10-plugin-manager':[/^(插件|Plugins)(\s.*)?$/i,'plugins'],
      '11-settings-browser':[/^(浏览器|Browser)$/i,'browser'],
      '12-settings-chat':[/^(Chat UI|聊天界面|原生聊天)$/i,'chat'],
      '13-settings-hosts':[/^(SSH|SSH 主机|SSH Hosts)$/i,'ssh'],
      '14-settings-automations':[/^(自动化|Automations)$/i,'automations']
    }
    for(const [id,[name,target]] of Object.entries(desired)){
      await step(id,'Settings navigation: '+target,()=>click(name),()=>page.locator('section[data-settings-section="'+target+'"]').first().waitFor())
    }
    if(await button(/返回应用|回到应用|Back to app/i).count()) await click(/返回应用|回到应用|Back to app/i)
    else await page.keyboard.press('Escape')
    await step('15-search','Sidebar search',()=>click(/搜索工作树和浏览器选项卡|Search worktrees and browser tabs/i),()=>page.getByRole('dialog').first().waitFor())
    await page.keyboard.press('Escape')
    await step('16-tasks','Sidebar Tasks',()=>click(/^(任务|Tasks)$/),
      ()=>page.locator('[data-contextual-tour-target="tasks-source-filters"]').waitFor({timeout:13000}))
    await step('17-automations','Sidebar Automations',()=>click(/^(自动化|Automations)$/))
    await step('18-mobile','Sidebar Mobile',()=>click(/Porpita 手机端|Porpita Mobile|Orca Mobile/i))
    await click(/关闭 Porpita 手机|Close (Porpita|Orca) Mobile/i).catch(()=>{})
    await click(/显示活动工作区|Reveal active workspace/i).catch(()=>{})
    }
    await dismissStartupPrompts()
    if (workbenchOnly && !completedOnboarding) {
      await step('19a-explorer','Inspect a seeded local folder',async()=>{},
        ()=>page.getByText('notes.md',{exact:true}).first().waitFor({timeout:7500}))
      await step('19b-editor','Double click the local file',async()=>page.getByText('notes.md',{exact:true}).first().dblclick(),
        ()=>page.getByText(/Disposable editor text/i).first().waitFor({timeout:7500}))
      await step('19c-html','Double click the local HTML file',async()=>page.getByText('preview.html',{exact:true}).first().dblclick(),
        ()=>page.getByText('preview.html',{exact:true}).last().waitFor())
      await step('20-explorer-search','Explorer content mode',()=>click(/搜索文件内容|Search file contents/i),
        ()=>page.getByRole('textbox').first().waitFor())
    }
    if (toolsExtra) {
      await click(/^(设置|Settings)$/).catch(()=>{})
      await step('30-appearance','Go to Appearance; set dark theme in the test profile',async()=>{
        await click(/^(外观|Appearance)$/)
        await click(/^(深色|Dark)$/)
      },()=>page.waitForFunction(()=>document.documentElement.classList.contains('dark')))
      await click(/返回应用|回到应用|Back to app/i).catch(()=>{})
      await step('31-dark-workbench','Return to the same workbench in dark theme',async()=>{},
        ()=>button(/^(新标签页|New tab)$/i).waitFor())
      await step('32-tasks-settled','Open Tasks and wait for its Source Bar',()=>click(/^(任务|Tasks)$/),
        ()=>page.locator('[data-contextual-tour-target="tasks-source-filters"]').waitFor({timeout:13000}))
      await click(/关闭任务|Close tasks/i).catch(()=>{})
      await page.keyboard.press('Escape')
      await dismissStartupPrompts()
    }
    if (completedOnboarding) {
      await step('19d-artifacts','Open enabled Artifacts sidebar entry',()=>click(/^(工件|Artifacts)(\s.*)?$/i))
      await step('19e-skills','Open enabled Skills sidebar entry',()=>click(/^(技能|Skills)(\s.*)?$/i))
      await click(/关闭技能|Close Skills/i).catch(()=>{})
    }
    if (!workbenchOnly) {
    const fixture = await page.evaluate(async p=>await window.api.repos.add({path:p}),repo)
    await step('19-fixture-project','Open disposable Git repository in Sidebar (seeded via app IPC)',async()=>{
      if('error' in fixture) throw new Error(fixture.error)
      const row=page.getByText('UI-spec-sample',{exact:true})
      await row.first().waitFor({timeout:8000})
      const worktree=page.locator('[data-worktree-id^="'+fixture.repo.id+'::"]').first()
      if(!await worktree.isVisible()) await row.first().click({timeout:8000})
      await worktree.click({timeout:8000})
    },()=>page.waitForFunction(repoId=>Array.from(document.querySelectorAll('[data-worktree-id]')).some(row=>row.getAttribute('data-worktree-id')?.startsWith(repoId+'::')&&row.querySelector('[data-worktree-card-active=true]')),fixture.repo?.id,{timeout:4500}))
    await step('20-explorer-search','Explorer content mode',()=>click(/搜索文件内容|Search file contents/i))
    await step('21-source-control','Source Control activity button',()=>click(/^(源代码管理|源代码控制|Source Control)/i),
      ()=>page.getByText('notes.md',{exact:true}).first().waitFor())
    await step('21b-diff','Open changed file from Source Control',async()=>page.getByText('notes.md',{exact:true}).first().click(),
      ()=>page.locator('.monaco-diff-editor').first().waitFor({timeout:8000}))
    }
    await step('22-new-tab','New Tab menu',()=>click(/^(新标签页|New tab)$/i),
      ()=>page.getByRole('menuitem',{name:/新浏览器选项卡|New Browser Tab/i}).first().waitFor())
    if (toolsExtra) {
      // The existing home-page preference belongs to this disposable profile.
      await page.evaluate(async()=>window.api.settings.set({browserDefaultUrl:null}))
      await step('33-browser-blank','Choose New Browser Tab from the menu',async()=>{
        const item=page.getByRole('menuitem',{name:/新浏览器选项卡|New Browser Tab/i}).first()
        if(!await item.isVisible()) await click(/^(新标签页|New tab)$/i)
        await item.click()
      },()=>page.locator('[data-orca-browser-address-bar=true]').first().waitFor({timeout:10000}))
    }
    await page.keyboard.press('Escape')
    const currentTerminal=page.getByText(/^(Terminal|终端) [0-9]+$/).first()
    if(await currentTerminal.isVisible()) await currentTerminal.click().catch(()=>{})
    await step('23-terminal-split','Split Terminal Right button',()=>click(/向右拆分终端|Split Terminal Right/i),
      ()=>page.waitForFunction(()=>document.querySelectorAll('.xterm').length>=2,null,{timeout:5000}))
    await step('24a-right-dock-before','Right dock before toggle',async()=>{},()=>button(/切换右侧边栏|Toggle right sidebar/i).waitFor())
    await step('24-right-dock-closed','Toggle Right Sidebar',()=>click(/切换右侧边栏|Toggle right sidebar/i))
    await step('24b-right-dock-reopened','Reverse the right dock toggle',()=>click(/切换右侧边栏|Toggle right sidebar/i))
    await step('25-narrow','Resize hidden desktop viewport',()=>win.evaluate(w=>w.setContentSize(820,580)))
    await page.emulateMedia({reducedMotion:'reduce'})
    await step('26-reduced-dock','Toggle Right Sidebar with reduced motion',()=>click(/切换右侧边栏|Toggle right sidebar/i))
    await page.emulateMedia({reducedMotion:'no-preference'})
    await win.evaluate(w=>w.setContentSize(1280,800))
    await step('27-add-project','Open Add Project without submitting',()=>click(/^(添加项目|Add project)$/i),
      ()=>page.getByRole('dialog').first().waitFor({timeout:10000}))
    await page.keyboard.press('Escape')
    await step('28-new-worktree','Open New Workspace without submitting',()=>click(/^(新工作区|New workspace)$/i),
      ()=>page.getByRole('dialog').first().waitFor({timeout:10000}))
    await page.keyboard.press('Escape')
    await cdp.send('Page.stopScreencast').catch(()=>{})
    await cdp.detach().catch(()=>{})
  } finally {
    if (state) write('run.json',{version:state.version,windowIsolation:state.windows,profile:completedOnboarding||navigationReplay?'disposable, seeded completed onboarding':'disposable, fresh',source:runtimeKind,steps})
    const child = app.process()
    await bounded(app.close(),4500,'Electron close timed out').catch(()=>{
      if(child.exitCode===null) child.kill()
    })
  }
}
main().catch(error=>{console.error(sanitize(error.stack||error.message));process.exitCode=1}).finally(async()=>{
  try {
    wslFixture?.dispose()
    await physicalFixture?.connection.close()
  } catch (error) {
    console.error(sanitize(error.message))
    process.exitCode = 1
  }
  if (navigationReplay) process.exit(process.exitCode || 0)
})
