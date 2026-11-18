const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')

const source = path.resolve(process.argv[2] || 'D:/Chatgpt/Porpita')
const out = path.resolve(process.argv[3] || path.join(__dirname, '..', 'source-index'))
const base = 'src/renderer/src'
const parser = createRequire(path.join(source, 'package.json'))('@babel/parser')
const relative = p => p.replaceAll('\\', '/')
const excluded = /(?:^|\/)(?:__tests__|__mocks__|__fixtures__|component-fixtures)(?:\/|$)|\.(?:test|spec|fixture|test-fixture|test-support|stories)\.[^/]+$/i
const has = p => fs.existsSync(path.join(source, p)) && fs.statSync(path.join(source, p)).isFile()
function walk(dir) {
  return fs.readdirSync(path.join(source, dir), { withFileTypes: true }).flatMap(d => {
    const p = relative(path.join(dir,d.name))
    if (excluded.test(p)) return []
    return d.isDirectory() ? walk(p) : [p]
  })
}
const files = new Map()
const primitiveUsages = []
const pending = walk(base).filter(p=>/\.(tsx?|jsx?|css)$/.test(p) && !p.endsWith('.d.ts'))
const css = []
const parseErrors = []
const roots = ['main.tsx','popout.tsx','space.tsx','web/main.tsx'].map(p=>base+'/'+p).filter(has)
function resolve(from, name) {
  if(!name || (!name.startsWith('.') && !name.startsWith('@/'))) return undefined
  const p = name.startsWith('@/') ? base + '/' + name.slice(2) : relative(path.normalize(path.join(path.dirname(from),name)))
  if (excluded.test(p)) return undefined
  const stem = p.replace(/\.[cm]?jsx?$/, '')
  return [...new Set([p, stem+'.tsx', stem+'.ts', p+'/index.tsx', p+'/index.ts'])].find(has)
}
function getName(n) {
  if (!n) return ''
  if (n.type==='JSXMemberExpression') return getName(n.object)+'.'+getName(n.property)
  return n.name ?? n.value ?? ''
}
function visit(n, fn) {
  if (!n || typeof n !== 'object' || !n.type) return
  fn(n)
  for(const key of Object.keys(n)) {
    if(['loc','comments','tokens','extra','leadingComments','trailingComments','innerComments'].includes(key)) continue
    const value=n[key]
    if(Array.isArray(value)) for(const child of value) visit(child, fn)
    else visit(value, fn)
  }
}
const interestingAttr = /^(on(?:Click|DoubleClick|ContextMenu|Mouse\w+|Pointer\w+|Drag\w*|Drop|Key\w+|Focus|Blur|Wheel|Scroll|Change|Input|Submit|OpenChange|ValueChange|Select|Resize|Composition\w+)|aria-(?:current|expanded|live|disabled|selected|invalid|busy)|disabled|data-state)$/
const namedPrimitive = /^(?:button|a|input|label|textarea|select|details|summary|dialog|progress|canvas|iframe|webview|[A-Z].*(?:Button|Menu|MenuItem|Popover|Tooltip|Dialog|Tab|Listbox|Alert|Sheet|Select|Input|Checkbox|Switch|Slider|Separator|ScrollArea|Progress|Spinner))$/
const stateNames = /(?:^|[A-Z])(Loading|Disabled|Pending|Error|Failure|Empty|Offline|Disconnected|Reconnecting|Denied|Streaming|Running|Restor(?:e|ing)|Retry|Collapsed|Expanded|Visible|Open|Active|Selected|Dirty|Stale)(?:[A-Z]|$)/
for (const p of pending) {
  const content=fs.readFileSync(path.join(source,p),'utf8')
  if(p.endsWith('.css')) {
    const lines=content.split(/\r?\n/)
    css.push({path:p,events:lines.flatMap((line,i)=>/@(?:keyframes|media \(prefers-reduced-motion)|\b(?:animation|transition)(?:-[\w-]+)?:/.test(line)?[{line:i+1,text:line.trim()}]:[])})
    continue
  }
  let ast
  try {
    ast=parser.parse(content,{sourceType:'unambiguous',plugins:['typescript',...(p.endsWith('x')?['jsx']:[])]})
  } catch(error) {
    parseErrors.push({path:p,error:String(error).split('\n')[0]})
    continue
  }
  const imports=new Set(), jsx=[], uses=[], motion=[], conditions=[], primitiveImports=new Map(), jsxSites=[]
  visit(ast.program,n=>{
    let spec
    if ((n.type==='ImportDeclaration' || n.type==='ExportNamedDeclaration' || n.type==='ExportAllDeclaration') && n.importKind!=='type' && n.exportKind!=='type' &&
        (!n.specifiers?.length || n.specifiers.some(s=>s.importKind!=='type'&&s.exportKind!=='type'))) spec=n.source?.value
    if(n.type==='CallExpression' && n.callee.type==='Import') spec=n.arguments[0]?.value
    if(n.type==='ImportExpression') spec=n.source.value
    const dependency=resolve(p,spec)
    if(dependency) imports.add(dependency)
    if (n.type==='ImportDeclaration' && dependency?.startsWith(base+'/components/ui/')) {
      for (const item of n.specifiers) {
        if (item.importKind!=='type') primitiveImports.set(item.local.name,dependency)
      }
    }
    if(n.type==='JSXOpeningElement'){
      const tag=getName(n.name)
      const attrs=n.attributes.filter(a=>a.type==='JSXAttribute')
      const events=attrs.map(a=>getName(a.name)).filter(a=>interestingAttr.test(a))
      jsx.push(tag)
      jsxSites.push({tag,line:n.loc.start.line,events})
      if(events.length || namedPrimitive.test(tag)) {
        const label=attrs.find(a=>['aria-label','title','data-testid'].includes(getName(a.name)))
        const text=label ? content.slice(label.value?.start??label.end,label.value?.end??label.end).replace(/\s+/g,' ').slice(0,140) : undefined
        uses.push({line:n.loc.start.line,tag,events,...(text?{label:text}:{})})
      }
    }
    if(n.type==='JSXExpressionContainer' && ['ConditionalExpression','LogicalExpression'].includes(n.expression.type)){
      const pred=n.expression.test??n.expression.left
      if(pred){
        const text=content.slice(pred.start,pred.end).replace(/\s+/g,' ').trim()
        if(text.length<=220&&(/[.]/.test(text)||stateNames.test(text[0]?.toUpperCase()+text.slice(1)))) conditions.push({line:pred.loc.start.line,text})
      }
    }
    if(n.type==='StringLiteral'||n.type==='TemplateElement'){
      const value=typeof n.value==='string'?n.value:n.value?.raw
      if(value?.length<=800 && /(?:^|\s|:)motion-(?:safe|reduce):|(?:^|\s|:)(?:animate|transition|duration|ease)-/.test(value)) {
        const classes=value.trim().split(/\s+/).filter(s=>/(?:animate|transition|duration|ease|motion-reduce|motion-safe)-/.test(s))
        motion.push({line:n.loc.start.line,classes})
      }
    }
  })
  for (const site of jsxSites) {
    const primitive = primitiveImports.get(site.tag.split('.')[0])
    if (primitive) primitiveUsages.push({path:p,primitive,...site})
  }
  files.set(p,{path:p,imports:[...imports].sort(),jsx:[...new Set(jsx)].sort(),uses,motion,conditions})
}
function closure(root, seen = new Set()) {
  if(seen.has(root)) return seen
  seen.add(root)
  for (const dep of files.get(root)?.imports??[]) if(files.has(dep)) closure(dep,seen)
  return seen
}
const reach = new Map(roots.map(root=>[root,closure(root)]))
const rows=[...files.values()].filter(f=>f.path.endsWith('.tsx')||f.path.endsWith('.jsx')||f.jsx.length||f.motion.length).map(f=>({...f,
  entrypoints: roots.filter(root=>reach.get(root).has(f.path))
})).sort((a,b)=>a.path.localeCompare(b.path,'en'))
const sourceIndex = rows.map(({path,entrypoints,jsx,uses,motion,conditions})=>({path,entrypoints,jsx,uses,motion,conditions}))
const requiredRoots=['main.tsx','popout.tsx','space.tsx']
if (requiredRoots.some(r=>!files.has(base+'/'+r))) throw new Error('Expected desktop roots missing')
fs.mkdirSync(out,{recursive:true})
function jsonl(name, entries){fs.writeFileSync(path.join(out,name),entries.map(entry=>JSON.stringify(entry)).join('\n')+'\n')}
jsonl('renderer.jsonl',sourceIndex)
jsonl('styles-motion.jsonl',css)
jsonl('primitive-usage.jsonl',primitiveUsages)
const keyFiles = [
  ['activeView',base+'/app-shell/AppWorkspaceShell.tsx',/activeView === '([^']+)'/g],
  ['modal',base+'/app-shell/AppRootSurfaces.tsx',/boundaryId="((?:modal|overlay)\.[^"]+)"/g],
  ['notice',base+'/app-shell/AppNotificationCards.tsx',/boundaryId="(overlay\.[^"]+)"/g],
  ['rightDock',base+'/components/right-sidebar/right-sidebar-panel-content.tsx',/effectiveTab === '([^']+)'/g],
  ['setting','src/renderer/src/components/settings/page',null],
]
const registry = {}
for (const [key,file,re] of keyFiles) {
  const paths=re?[file]:walk(file).filter(p=>/settings-.*-section-renderers\.tsx$/.test(p))
  const rx=re??/<SettingsSection\s+id="([^"]+)"/g
  registry[key]=paths.flatMap(p=>{
    const content=fs.readFileSync(path.join(source,p),'utf8')
    return [...content.matchAll(rx)].map(m=>({id:m[1],path:p,line:content.slice(0,m.index).split('\n').length}))
  })
}
const mainEntries = walk('src/main').filter(p=>/\.[cm]?tsx?$/.test(p)).flatMap(p=>{
  const lines=fs.readFileSync(path.join(source,p),'utf8').split(/\r?\n/)
  return lines.flatMap((s,i)=>/\bnew (?:BrowserWindow|Notification|Tray)\s*\(|\b(?:Menu\.buildFromTemplate|dialog\.show(?:OpenDialog|SaveDialog|MessageBox|ErrorBox)(?:Sync)?)\s*\(/.test(s)?[{path:p,line:i+1,text:s.trim()}]:[])
})
jsonl('native-host-candidates.jsonl',mainEntries)
const summary = {
  roots: roots.map(root=>({path:root,reachableModules:reach.get(root).size})),
  rendererModules:files.size, rendererRows:rows.length,
  noStaticEntryPoint:rows.filter(r=>!r.entrypoints.length).length,
  interactableCandidates:rows.reduce((a,r)=>a+r.uses.length,0),
  primitiveUseSites:primitiveUsages.length,
  styleFiles:css.length,
  nativeHostCandidates:mainEntries.length,
  parseErrors, registry,
  limits:['Static import reachability is not runtime reachability. Check registration, feature gates, same-name components, module aliases and nonliteral imports.', 'JSX/event/conditional/CSS candidates are discovery inputs. They include some internals and omit non-JSX behavior, guest UIs and OS-owned UI.']
}
fs.writeFileSync(path.join(out,'summary.json'),JSON.stringify(summary,null,2)+'\n')
console.log(JSON.stringify({...summary,registry:Object.fromEntries(Object.entries(registry).map(([k,v])=>[k,v.length]))},null,2))
if(parseErrors.length) process.exitCode=1
