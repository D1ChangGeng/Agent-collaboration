const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { pathToFileURL } = require('node:url');
const root = __dirname;
async function build() {
  const source = path.join(root,'..','sources','pigi');
  const vendor = path.join(root,'vendor','pigi');
  if (!fs.existsSync(vendor)) fs.cpSync(source,vendor,{recursive:true});
  const uiModule = await import(pathToFileURL(path.join(vendor,'website/src/lib/appUi.ts')).href);
  const ui=Object.fromEntries(Object.entries(uiModule).filter(([,v])=>v && typeof v.classes==='string'));
  const names=['plus','folder','folder-plus','chevron-right','chevron-down','notebook','message','terminal-2','filter-2','binary-tree-2','settings','user','moon','search','x','arrow-up','arrow-left','corner-up-left','focus-2','copy','git-branch','list-details','history','layout-sidebar-left-collapse','layout-sidebar-left-expand'];
  const icons={};
  const tabler=path.join(root,'node_modules','@tabler','icons');
  for(const name of names){
    const candidates=[path.join(tabler,'icons/outline',name+'.svg'),path.join(tabler,'outline',name+'.svg')];
    const file=candidates.find(fs.existsSync);
    if(!file)throw new Error('Missing Tabler icon '+name);
    icons[name]=fs.readFileSync(file,'utf8').match(/<svg[^>]*>([\s\S]*)<\/svg>/)[1].trim();
  }
  fs.mkdirSync(path.join(root,'dist'),{recursive:true});
  const cli=path.join(root,'node_modules','@tailwindcss','cli','dist','index.mjs');
  execFileSync(process.execPath,[cli,'-i',path.join(root,'styles.css'),'-o',path.join(root,'dist/styles.css'),'--minify'],{cwd:root,stdio:'inherit'});
  const css=fs.readFileSync(path.join(root,'dist/styles.css'),'utf8');
  const scripts=['graph.js','fixture.js','app.js'].map(f=>fs.readFileSync(path.join(root,f),'utf8')).join('\n');
  function html(sourceTrial=false){
    return `<!doctype html>\n<html lang="${sourceTrial?'en':'zh-CN'}" class="${sourceTrial?'':'dark'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark light"><title>${sourceTrial?'Pigi · source presentation trial':'Root · ACS 通讯阅读研究'}</title><style>${css}</style></head><body${sourceTrial?' data-source-trial="true"':''}><div id="app"></div><script>window.PIGI_UI=${JSON.stringify(ui)};window.STUDY_ICONS=${JSON.stringify(icons)};\n${scripts.replace(/<\/script/gi,'<\\/script')}</script></body></html>`;
  }
  fs.writeFileSync(path.join(root,'dist/index.html'),html());
  fs.writeFileSync(path.join(root,'dist/source-trial.html'),html(true));
  fs.copyFileSync(path.join(vendor,'LICENSE'),path.join(root,'dist/LICENSE-PIGI'));
  const pigiNotices=path.join(vendor,'licenses/THIRD_PARTY_NOTICES.md');
  if(fs.existsSync(pigiNotices))fs.copyFileSync(pigiNotices,path.join(root,'dist/NOTICE-PIGI.md'));
  fs.copyFileSync(path.join(tabler,'LICENSE'),path.join(root,'dist/LICENSE-TABLER'));
  fs.copyFileSync(path.join(root,'node_modules/tailwindcss/LICENSE'),path.join(root,'dist/LICENSE-TAILWIND'));
  fs.copyFileSync(path.join(root,'ADOPTION.md'),path.join(root,'dist/ADOPTION.md'));
  console.log(`Built offline index.html (${fs.statSync(path.join(root,'dist/index.html')).size.toLocaleString()} bytes) and source-trial.html.`);
}
build().catch(e=>{console.error(e);process.exitCode=1;});
