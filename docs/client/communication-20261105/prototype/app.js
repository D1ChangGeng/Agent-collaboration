/* Pigi's website presentation, adapted to an offline ACS peer-message client.
 * See ADOPTION.md for exact source/variant and the narrow ACS extensions. */
(function () {
  'use strict';
  const { ACTOR, messages: initialMessages } = ACSFixture;
  const { project, peerMessages, canReply, missingParents } = ACSGraph;
  const icons = window.STUDY_ICONS;
  const ui = window.PIGI_UI;
  const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const icon = (name, size = 16, cls = '') => `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false" class="tabler-icon ${cls}">${icons[name] || icons.message}</svg>`;
  const button = (action, label, glyph, extra = '') => `<button type="button" data-action="${action}" aria-label="${label}" title="${label}" class="${ui.TOOLBAR_BUTTON.classes} ${extra}">${icon(glyph)}</button>`;
  const inline = str => escape(str).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
  function markdown(text) {
    const chunks = text.split(/(```[\s\S]*?```)/g);
    return chunks.map(chunk => chunk.startsWith('```') ? `<pre><code>${escape(chunk.replace(/^```[^\n]*\n/, '').replace(/```$/, ''))}</code></pre>` : chunk.split(/\n\n+/).filter(Boolean).map(block => {
      if (block.startsWith('### ')) return `<h3>${inline(block.slice(4))}</h3>`;
      if (block.startsWith('## ')) return `<h2>${inline(block.slice(3))}</h2>`;
      const lines = block.split('\n');
      if (lines.every(l => l.startsWith('- '))) return `<ul>${lines.map(l => `<li>${inline(l.slice(2))}</li>`).join('')}</ul>`;
      if (lines.every(l => /^\d+\. /.test(l))) return `<ol>${lines.map(l => `<li>${inline(l.replace(/^\d+\. /,''))}</li>`).join('')}</ol>`;
      return `<p>${inline(block).replace(/\n/g,'<br>')}</p>`;
    }).join('')).join('');
  }
  if (document.body.dataset.sourceTrial === 'true') { renderSourceTrial(); return; }
  const params = new URLSearchParams(location.search);
  const state = {
    peer: ['Root','Runtime','Reviewer'].includes(params.get('peer')) ? params.get('peer') : 'Root',
    focus: params.get('view') === 'focus' ? (params.get('m') || 'm1') : null,
    partial: params.get('range') === 'partial', sidebar: params.get('sidebar') !== 'closed',
    context: false, rangeMenu: false, messages: initialMessages.slice(), replyTo: [], mode: 'invoke',
    drafts: {}, reads: {}, returns: [], fullAnchor: null, selected: null, notice: '',
  };
  const app = document.getElementById('app');
  try { Object.assign(state.drafts, JSON.parse(localStorage.getItem('acs-study-drafts') || '{}')); } catch (_) {}
  const allLoaded = () => peerMessages(state.messages, ACTOR, state.peer).filter(m => !state.partial || m.sequence >= 3);
  const visible = () => project(allLoaded(), ACTOR, state.peer, state.focus);
  const message = id => state.messages.find(m => m.id === id);
  function saveDraft() {
    const field = document.getElementById('composer');
    if (field) state.drafts[state.peer] = { text: field.value, replyTo: state.replyTo.slice(), mode: state.mode };
    try { localStorage.setItem('acs-study-drafts', JSON.stringify(state.drafts)); } catch (_) {}
  }
  function anchor() {
    const scroller = document.getElementById('transcript');
    if (!scroller) return null;
    const rect = scroller.getBoundingClientRect();
    const node = [...scroller.querySelectorAll('[data-message-id]')].find(n => n.getBoundingClientRect().bottom > rect.top + 2);
    return { id: node?.dataset.messageId, offset: node ? node.getBoundingClientRect().top - rect.top : 0, scrollTop: scroller.scrollTop };
  }
  function restore(a) {
    if (!a) return;
    const scroller = document.getElementById('transcript'), node = document.getElementById(`message-${a.id}`);
    if (node) scroller.scrollTop += node.getBoundingClientRect().top - scroller.getBoundingClientRect().top - a.offset;
    else scroller.scrollTop = a.scrollTop || 0;
  }
  function url() {
    const p = new URLSearchParams();
    if (state.peer !== 'Root') p.set('peer', state.peer);
    if (state.focus) { p.set('view','focus'); p.set('m',state.focus); }
    if (state.partial) p.set('range','partial');
    if (!state.sidebar) p.set('sidebar','closed');
    try { history.replaceState(null, '', `${location.pathname}${p.size ? '?' + p : ''}`); } catch (_) {}
  }
  function gotoFocus(id) {
    saveDraft();
    if (!state.focus) state.fullAnchor = anchor();
    state.focus = id; state.selected = id; state.returns = [];
    render();
  }
  function jumpOriginal(id) {
    const target = allLoaded().find(m => m.id === id);
    if (!target) { announce(`原文 ${id} 不在已加载范围；可从“已加载范围”补读更早消息。`); return; }
    saveDraft();
    state.returns.push({ focus: state.focus, anchor: anchor(), selected: state.selected });
    state.focus = null; state.selected = id; render();
    const node = document.getElementById(`message-${id}`);
    document.getElementById('transcript').scrollTop += node.getBoundingClientRect().top - document.getElementById('transcript').getBoundingClientRect().top - 32;
    node.focus({ preventScroll: true });
  }
  function returnFromOriginal() {
    const previous = state.returns.pop();
    if (!previous) return;
    saveDraft(); state.focus = previous.focus; state.selected = previous.selected;
    render(); restore(previous.anchor);
  }
  function exitFocus() {
    saveDraft(); state.focus = null; state.selected = null; state.returns = [];
    render(); restore(state.fullAnchor);
  }
  function announce(text) {
    state.notice = text;
    const el = document.getElementById('notice');
    if (el) { el.textContent = text; el.hidden = false; }
  }
  function switchPeer(peer) {
    if (state.peer === peer) return;
    saveDraft();
    state.reads[state.peer]={ focus:state.focus, returns:state.returns.slice(), fullAnchor:state.fullAnchor, selected:state.selected, anchor:anchor(), partial:state.partial, notice:state.notice };
    state.peer = peer;
    const read=state.reads[peer] || {};
    state.focus=read.focus || null; state.returns=read.returns || []; state.fullAnchor=read.fullAnchor || null; state.selected=read.selected || null; state.partial=read.partial || false; state.notice=read.notice || '';
    const d = state.drafts[peer] || {}; state.replyTo = (d.replyTo || []).filter(id => canReply(message(id), ACTOR, peer)); state.mode = d.mode || 'invoke';
    render();restore(read.anchor);
  }
  function renderSidebar() {
    const row = (name, glyph, action, extra = '', selected = false) => `<button type="button" data-action="${action}" ${extra} class="flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-sm ${selected ? 'bg-[var(--system-accent)]/10 text-foreground' : 'text-sidebar-foreground/85 hover:bg-muted'}">${icon(glyph,15,'shrink-0 text-muted-foreground')}<span class="truncate">${name}</span>${selected ? '<span class="ml-auto size-1.5 rounded-full bg-system-accent"></span>' : ''}</button>`;
    return `<aside id="sidebar" aria-label="项目、Route 与联系人" class="flex shrink-0 flex-col bg-[var(--sidebar-solid)]" ${state.sidebar ? '' : 'hidden'}>
      <div class="flex h-11 shrink-0 items-center justify-between px-4"><span class="text-sm font-medium tracking-wide">ACS <span class="ml-1 text-xs font-normal text-muted-foreground">Client</span></span>${button('sidebar','收起侧栏','layout-sidebar-left-collapse')}</div>
      <div class="flex flex-col gap-0.5 px-2">${row('新消息','plus','new-message')}${row('在此往来中查找','search','search')}</div>
      <div class="mt-4 flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto px-2">
        <p class="px-2 pb-1 text-xs text-sidebar-foreground/55">项目</p>
        ${row('Agent collaboration','folder','project')}
        <p class="mt-5 px-2 pb-1 text-xs text-sidebar-foreground/55">Route</p>
        ${row('Collaboration runtime','git-branch','route')}
        <p class="mt-5 flex items-center justify-between px-2 pb-1 text-xs text-sidebar-foreground/55"><span>联系人</span><span class="text-2xs">我的往来</span></p>
        ${row('Root','message','peer','data-peer="Root"',state.peer==='Root')}
        ${row('Runtime','terminal-2','peer','data-peer="Runtime"',state.peer==='Runtime')}
        ${row('Reviewer','user','peer','data-peer="Reviewer"',state.peer==='Reviewer')}
      </div>
      <div class="px-4 pb-2 text-xs text-muted-foreground"><div class="mb-2 flex items-center gap-2">${icon('user',14)}<span>client-agent</span></div><div class="border-t border-border pt-2 text-2xs">演示数据 · 本地交互</div></div>
      <div class="px-2 pb-2">${row(document.documentElement.classList.contains('dark')?'切换浅色':'切换深色','moon','theme')}</div>
    </aside>`;
  }
  function renderRefs(m, own) {
    if (!m.reply_to.length) return '';
    const loadedIds = new Set(allLoaded().map(m => m.id));
    const first = message(m.reply_to[0]);
    const short = first ? first.content.replace(/\n/g,' ').slice(0,42) : '';
    return `<div class="reply-links ${own ? 'self-end' : ''}"><button type="button" data-action="original" data-id="${m.reply_to[0]}" class="reply-preview" title="跳转原文" aria-label="查看回复原文：${escape(short || m.reply_to[0])}">${icon('corner-up-left',13)}<span>${loadedIds.has(m.reply_to[0]) ? `回复 ${first.from===ACTOR?'你':escape(first.from)} · ${escape(short)}${short.length===42?'…':''}` : `回复的原文未加载`}</span></button>${m.reply_to.length>1 ? `<div class="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><span>同时关联</span>${m.reply_to.slice(1).map(id => {const p=message(id);const summary=p?p.content.replace(/\n/g,' ').slice(0,25):id;return `<button type="button" data-action="original" data-id="${id}" aria-label="查看同时关联的原文：${escape(summary)}" class="hover:text-foreground underline underline-offset-2">${loadedIds.has(id)?`${p.from===ACTOR?'你':escape(p.from)} · ${escape(summary)}…`:'原文未加载'}</button>`;}).join('')}</div>` : ''}</div>`;
  }
  function messageActions(m, own) {
    const accessible=escape(m.content.replace(/\n/g,' ').slice(0,64));
    return `<div class="message-actions group/actions relative flex items-center ${own?'justify-end':'justify-start'} gap-1 transition-opacity">
      <span class="mr-1 text-xs text-muted-foreground" title="消息序号 #${m.sequence}">${own?'你':escape(state.peer)}</span>
      <button type="button" data-action="focus" data-id="${m.id}" aria-label="聚焦回复：${accessible}" class="${ui.ACTION_BUTTON.classes} gap-1 text-xs" title="仅看此消息与已加载的显式后继">${icon('focus-2',14)}<span>聚焦回复</span></button>
      ${own ? '' : `<button type="button" data-action="reply" data-id="${m.id}" aria-label="回复 ${escape(state.peer)}：${accessible}" class="${ui.ACTION_BUTTON.classes} gap-1 text-xs">${icon('corner-up-left',14)}<span>回复</span></button>`}
      <button type="button" data-action="copy" data-id="${m.id}" aria-label="复制${own?'你的':escape(state.peer)+'的'}消息：${accessible}" title="复制正文" class="${ui.ACTION_BUTTON.classes}">${icon('copy',14)}</button>
    </div>`;
  }
  function renderMessage(m) {
    const own = m.from === ACTOR;
    const longOwn = own && m.content.length > 300;
    // UserMessage and AssistantMessage markup/class strings come from Pigi.
    return `<article id="message-${m.id}" data-message-id="${m.id}" tabindex="-1" class="message-row ${state.selected===m.id?'selected-message':''} ${own?'own':'incoming'}" aria-label="${own?'你':escape(state.peer)}的消息 #${m.sequence}">
      ${own ? `<div class="group flex justify-end pb-2 pt-6"><div class="flex ${longOwn?'w-full max-w-full':'max-w-[85%]'} flex-col items-end">${renderRefs(m,true)}<div class="${longOwn?'w-full':'w-fit'} max-w-full overflow-clip rounded-2xl bg-muted px-3.5 py-2"><div class="${longOwn?'markdown-body':'whitespace-pre-wrap'} break-words text-[15px] leading-6 text-foreground">${longOwn?markdown(m.content):escape(m.content)}</div></div><div class="flex w-full items-center justify-end gap-2">${messageActions(m,true)}</div></div></div>` : `<div class="group flex justify-start pt-2"><div class="w-full min-w-0 text-[15px] text-foreground">${renderRefs(m,false)}<div class="markdown-body">${markdown(m.content)}</div>${messageActions(m,false)}</div></div>`}
    </article>`;
  }
  function renderContext() {
    const selected = message(state.selected || state.focus);
    return `<aside id="context-panel" aria-label="阅读上下文" class="context-panel border-l border-border bg-[var(--sidebar-solid)]" ${state.context?'':'hidden'}>
      <div class="flex h-11 items-center justify-between border-b border-border px-4"><span class="text-sm font-medium">阅读上下文</span>${button('context','关闭上下文','x')}</div>
      <div class="space-y-5 p-4 text-sm"><div><p class="mb-1 text-xs text-muted-foreground">当前读取关系</p><p>client-agent ↔ ${escape(state.peer)}</p></div><div><p class="mb-1 text-xs text-muted-foreground">阅读范围</p><p>${state.focus ? `从 #${message(state.focus)?.sequence || state.focus} 及其显式后继，当前 ${visible().length} 条` : `完整往来中的已加载消息，当前 ${visible().length} 条`}</p></div><div><p class="mb-1 text-xs text-muted-foreground">${selected?'选中消息':'消息关系'}</p>${selected?`<p class="mb-2">#${selected.sequence} · ${escape(selected.id)}</p><p class="text-xs text-muted-foreground">${selected.reply_to.length?'显式关联 '+selected.reply_to.map(id=> '#'+(message(id)?.sequence || id)).join('、'):'这条消息未声明 reply_to。'}</p>`:'<p class="text-xs text-muted-foreground">从消息上的“聚焦回复”进入局部阅读。聚焦不会自动设置发送的回复目标。</p>'}</div><div class="border-t border-border pt-4 text-xs leading-6 text-muted-foreground">列表只呈现当前 actor 与所选 peer 的实际往来。这里没有全项目私信视图。<br>序号用于排序，不表示时间。</div></div>
    </aside>`;
  }
  function renderComposer() {
    const d = state.drafts[state.peer] || {};
    const text = d.text || '';
    return `<form id="composer-form" class="shrink-0 px-5" aria-label="发往 ${escape(state.peer)} 的消息">
      <div class="relative mx-auto w-full" style="max-width:820px"><div class="flex ${ui.CHAT_CARD.classes} min-h-28">
        <div class="flex min-h-7 items-center gap-2 px-4 pt-3 text-xs text-muted-foreground"><span>发往 <strong class="font-medium text-foreground">${escape(state.peer)}</strong></span><span class="text-foreground/20">/</span>${state.replyTo.length ? state.replyTo.map(id=>`<button type="button" data-action="clear-reply" class="reply-chip flex items-center gap-1 rounded-chip bg-muted px-2 py-0.5 text-foreground">${icon('corner-up-left',12)}回复 #${message(id).sequence}${icon('x',12)}</button>`).join(''):'<span>新消息</span>'}</div>
        <textarea id="composer" aria-label="消息正文" rows="2" placeholder="写给 ${escape(state.peer)}…" class="min-h-16 w-full resize-none bg-transparent px-4 pb-2 pt-2 text-sm leading-6 text-foreground placeholder:text-muted-foreground/70">${escape(text)}</textarea>
        <div class="flex min-w-0 items-center justify-between gap-2 px-2.5 pb-2.5 pt-0"><div class="flex min-w-0 flex-1 items-center gap-1.5 overflow-hidden px-1"><span id="compose-mode-hint" class="truncate pl-1 text-xs text-muted-foreground">${state.mode==='invoke'?'发送并唤起对方':'仅投递，不唤起对方'}</span></div>
          <label class="flex shrink-0 items-center gap-1 text-xs text-muted-foreground"><span class="sr-only">发送方式</span><select id="send-mode" class="max-w-36 rounded-control-sm bg-background py-1 pl-2 pr-1 text-xs text-foreground" aria-label="发送方式"><option value="invoke" ${state.mode==='invoke'?'selected':''}>发送并唤起</option><option value="message_only" ${state.mode==='message_only'?'selected':''}>仅投递</option></select></label>
          <button id="send-button" type="submit" aria-label="${state.mode==='invoke'?'演示发送并唤起':'演示仅投递'}" title="${state.mode==='invoke'?'发送并唤起':'仅投递'} · 本地演示" class="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground disabled:bg-muted-foreground/30 disabled:text-muted-foreground" ${text.trim()?'':'disabled'}>${icon('arrow-up')}</button>
        </div></div></div>
      <div class="mx-auto flex w-full items-center justify-between gap-4 bg-background px-4 pb-3 pt-1.5 text-xs text-muted-foreground" style="max-width:820px"><span class="truncate">演示数据 · 发送仅添加到本地往来</span><span class="shrink-0 text-2xs">Ctrl ↵ 发送</span></div>
    </form>`;
  }
  function rangeMenu() {
    if (!state.rangeMenu) return '';
    const list = allLoaded(), missing = missingParents(list);
    return `<section class="range-popover ${ui.DIALOG_SURFACE.classes} p-4" aria-label="已加载范围"><div class="mb-2 flex items-center justify-between"><strong class="font-medium">已加载范围</strong>${button('range','关闭范围说明','x')}</div><p class="mb-2 text-xs leading-6 text-muted-foreground">${list.length?`序号 #${list[0].sequence}–#${list.at(-1).sequence} · ${list.length} 条`:'暂无消息'}。${state.partial?'这次仅加载了后段消息。':'截至这次读取的末条；后续仍可能有新消息。'}${missing.length?` ${missing.length} 个原文不在本次范围内。`:''}</p><button type="button" data-action="toggle-range" class="${ui.BUTTON_BASE.classes} ${ui.BUTTON_FILLED.classes} h-8 px-3 text-xs">${state.partial?'补读更早消息（演示）':'切换部分加载示例'}</button></section>`;
  }
  function render() {
    const active=document.activeElement;
    const activeControl=active?.dataset?.action ? {action:active.dataset.action,id:active.dataset.id,peer:active.dataset.peer} : null;
    if (state.focus && !allLoaded().some(m=>m.id===state.focus)) state.focus = null;
    const list = visible();
    const focusMessage = message(state.focus);
    const showReturn = state.returns.length > 0;
    app.innerHTML = `<div class="study-window group/view relative mx-auto w-full max-w-none overflow-hidden bg-background"><div class="flex h-full">${renderSidebar()}<main class="relative flex min-w-0 flex-1 flex-col overflow-hidden border-l-[0.5px] border-foreground/27 bg-background">
      <header class="relative z-10 flex h-11 shrink-0 items-center gap-2 border-b-[0.5px] border-foreground/27 px-3">${state.sidebar?'':button('sidebar','展开侧栏','layout-sidebar-left-expand')}<div class="flex min-w-0 items-center gap-1.5">${icon('message',16,'shrink-0 text-foreground')}<span class="truncate text-sm font-medium text-foreground">${escape(state.peer)}</span><span class="ml-2 hidden text-xs text-muted-foreground min-[900px]:inline">你与 ${escape(state.peer)} 的往来</span></div><div class="flex-1"></div><div class="flex shrink-0 items-center gap-0.5">${button('search','在此往来中查找','search')}${button('context','阅读上下文','list-details',state.context?'text-foreground':'')}</div></header>
      <div class="scope-toolbar relative flex shrink-0 items-center gap-2 border-b border-border px-5 text-xs"><div class="mx-auto flex w-full max-w-[820px] items-center gap-2">${showReturn?`<button type="button" data-action="return-original" class="flex items-center gap-1 text-system-accent">${icon('arrow-left',14)}返回刚才</button><span class="text-foreground/20">/</span><span class="text-muted-foreground">原文 #${message(state.selected)?.sequence || ''}</span>`:state.focus?`<button type="button" data-action="exit-focus" class="flex items-center gap-1 text-muted-foreground hover:text-foreground">${icon('arrow-left',14)}完整往来</button><span class="text-foreground/20">/</span><span class="flex items-center gap-1 text-foreground">${icon('focus-2',14)}聚焦 #${focusMessage?.sequence} 的回复</span><span class="text-muted-foreground">${list.length} 条</span>`:'<span class="font-medium text-foreground">完整往来</span><span class="text-muted-foreground">按序号排列</span>'}<div class="flex-1"></div><button type="button" data-action="range" aria-expanded="${state.rangeMenu}" class="flex shrink-0 items-center gap-1 text-muted-foreground hover:text-foreground">已加载范围 ${icon('chevron-down',12)}</button></div>${rangeMenu()}</div>
      ${state.focus?`<div class="focus-summary shrink-0 px-5 text-xs text-muted-foreground"><div class="mx-auto flex w-full max-w-[820px] items-center gap-2 py-2">${icon('git-branch',13)}<span>此消息及已加载的关联回复</span><span class="ml-auto text-2xs" title="显式后继范围，按序号排列">${list.map(m=>'#'+m.sequence).join(' · ')}</span></div></div>`:''}
      <div class="relative flex min-h-0 flex-1"><div class="flex min-w-0 flex-1 flex-col"><div id="transcript" class="h-full min-h-0 flex-1 overflow-y-auto" tabindex="0" aria-label="与 ${escape(state.peer)} 的往来"><div class="mx-auto flex w-full flex-col" style="max-width:860px;padding-inline:20px;padding-top:24px;padding-bottom:32px">${state.partial?`<div class="mb-3 flex items-center gap-2 border-b border-border pb-3 text-xs text-muted-foreground">${icon('history',14)}<span>较早消息尚未加载</span><button type="button" data-action="toggle-range" class="ml-auto underline underline-offset-2">补读更早消息</button></div>`:''}${list.length?list.map(renderMessage).join(''):`<div class="py-12 text-sm text-muted-foreground"><p class="mb-2 text-foreground">还没有与 ${escape(state.peer)} 的本地演示往来</p><p>从下方写一条新消息。这里只显示当前 actor 与这位联系人的消息。</p></div>`}<div class="mt-6 flex items-center gap-2 text-xs text-muted-foreground"><span class="h-px flex-1 bg-border"></span><span>${state.focus?'已加载范围内的聚焦结果':'截至这次读取'}</span><span class="h-px flex-1 bg-border"></span></div></div></div>
      <div id="notice" role="status" class="notice mx-5 mb-2 rounded-control-sm bg-muted px-3 py-2 text-xs text-muted-foreground" ${state.notice?'':'hidden'}>${escape(state.notice)}</div>${renderComposer()}</div>${renderContext()}</div>
    </main></div></div><dialog id="search-dialog" class="${ui.DIALOG_SURFACE.classes} p-0"><form method="dialog" class="flex h-11 items-center justify-between border-b border-border px-4"><span class="text-sm">查找当前已加载的往来</span><button type="submit" aria-label="关闭查找" class="${ui.TOOLBAR_BUTTON.classes}">${icon('x')}</button></form><div class="p-4"><input id="search-input" type="search" placeholder="搜索消息正文…" aria-label="搜索消息正文" class="w-full rounded-control border bg-transparent px-3 py-2 text-sm"><div id="search-results" class="mt-3 flex max-h-80 flex-col gap-1 overflow-y-auto text-sm text-muted-foreground">输入关键词查看结果。</div></div></dialog>`;
    const composer = document.getElementById('composer');
    composer.addEventListener('input', () => { document.getElementById('send-button').disabled = !composer.value.trim(); saveDraft(); });
    document.getElementById('send-mode').addEventListener('change', e=> { state.mode=e.target.value; saveDraft(); document.getElementById('compose-mode-hint').textContent=state.mode==='invoke'?'发送并唤起对方':'仅投递，不唤起对方'; document.getElementById('send-button').setAttribute('aria-label',state.mode==='invoke'?'演示发送并唤起':'演示仅投递'); });
    document.getElementById('composer-form').addEventListener('submit', e=>{ e.preventDefault(); send(); });
    document.getElementById('search-input').addEventListener('input', e=>search(e.target.value));
    if(activeControl){
      const next=[...document.querySelectorAll('[data-action]')].find(n=>n.dataset.action===activeControl.action && n.dataset.id===activeControl.id && n.dataset.peer===activeControl.peer && n.getClientRects().length);
      next?.focus({preventScroll:true});
    }
    url();
  }
  function send() {
    const field = document.getElementById('composer'), text = field.value.trim();
    if (!text) return;
    const reply = state.replyTo.filter(id=>canReply(message(id),ACTOR,state.peer));
    const sequence = Math.max(...state.messages.map(m=>m.sequence),0)+1;
    state.messages.push({id:`local-${sequence}`,sequence,from:ACTOR,to:state.peer,content:text,reply_to:reply});
    const outside = !!state.focus && !reply.some(id=>visible().some(m=>m.id===id));
    state.replyTo=[]; state.drafts[state.peer]={text:'',replyTo:[],mode:state.mode};
    state.notice=`已添加本地演示消息 #${sequence} · ${state.mode==='invoke'?'发送并唤起（演示）':'仅投递（演示）'}。${outside?'新消息不在当前聚焦范围，可返回完整往来查看。':''}`;
    render(); document.getElementById('transcript').scrollTop=document.getElementById('transcript').scrollHeight; document.getElementById('composer').focus(); saveDraft();
  }
  function search(query) {
    const results=document.getElementById('search-results');
    if (!query.trim()) { results.textContent='输入关键词查看结果。'; return; }
    const matches=allLoaded().filter(m=>m.content.toLowerCase().includes(query.toLowerCase()));
    results.innerHTML=matches.length?matches.map(m=>`<button type="button" data-action="search-result" data-id="${m.id}" class="rounded-control px-2 py-2 text-left hover:bg-muted"><span class="mb-1 block text-xs text-muted-foreground">#${m.sequence} · ${m.from===ACTOR?'你':escape(state.peer)}</span><span class="line-clamp-2 text-foreground">${escape(m.content.slice(0,120))}</span></button>`).join(''):'已加载范围内没有匹配消息。';
  }
  document.addEventListener('click', async e=>{
    const el=e.target.closest('[data-action]'); if(!el) return;
    const id=el.dataset.id;
    switch(el.dataset.action) {
      case 'peer': switchPeer(el.dataset.peer); break;
      case 'route': switchPeer('Runtime'); announce('Route 导航已选中 Runtime 联系人；读取边界仍是当前 actor 与 Runtime。'); break;
      case 'project': state.context=true; render(); announce('当前项目：Agent collaboration。项目入口只组织联系人。'); break;
      case 'focus': gotoFocus(id); break;
      case 'exit-focus': exitFocus(); break;
      case 'original': jumpOriginal(id); break;
      case 'return-original': returnFromOriginal(); break;
      case 'reply': if(canReply(message(id),ACTOR,state.peer)){const a=anchor();saveDraft();state.replyTo=[id];render();restore(a);document.getElementById('composer').focus({preventScroll:true});} break;
      case 'clear-reply': { const a=anchor();saveDraft();state.replyTo=[];render();restore(a);break; }
      case 'sidebar': { const a=anchor();saveDraft();state.sidebar=!state.sidebar;render();restore(a);break; }
      case 'context': { const a=anchor();saveDraft();state.context=!state.context;render();restore(a);break; }
      case 'range': { const a=anchor();saveDraft();state.rangeMenu=!state.rangeMenu;render();restore(a);break; }
      case 'toggle-range': { const a=anchor();saveDraft();state.partial=!state.partial;state.rangeMenu=false;if(state.partial && state.focus==='m1')state.focus='m3';render();restore(a);break; }
      case 'new-message': { const a=anchor();saveDraft();state.replyTo=[];render();restore(a);document.getElementById('composer').focus({preventScroll:true}); break; }
      case 'search': document.getElementById('search-dialog').showModal();document.getElementById('search-input').focus();break;
      case 'search-result': document.getElementById('search-dialog').close();jumpOriginal(id);break;
      case 'theme': { const a=anchor();saveDraft();document.documentElement.classList.toggle('dark');render();restore(a);break; }
      case 'copy': try { await navigator.clipboard.writeText(message(id).content); announce(`已复制消息 #${message(id).sequence}。`); } catch(_){const a=anchor();saveDraft();render();restore(a);const n=document.querySelector(`#message-${id} ${message(id).from===ACTOR?'.whitespace-pre-wrap':'.markdown-body'}`);const range=document.createRange();range.selectNodeContents(n);const s=getSelection();s.removeAllRanges();s.addRange(range);announce('正文已选中，可按 Ctrl C 复制。');} break;
    }
  });
  document.addEventListener('keydown',e=>{
    if(e.ctrlKey && e.key==='Enter' && e.target.id==='composer'){e.preventDefault();send();}
    if(e.key==='Escape' && !document.getElementById('search-dialog').open){if(state.returns.length)returnFromOriginal();else if(state.focus)exitFocus();}
    if(e.altKey && e.key==='1'){e.preventDefault();if(state.focus)exitFocus();}
    if(e.altKey && e.key==='2'){e.preventDefault();gotoFocus(allLoaded().find(m=>m.id==='m1')?.id || allLoaded()[0]?.id);}
  });
  const draft=state.drafts[state.peer] || {};state.replyTo=(draft.replyTo||[]).filter(id=>canReply(message(id),ACTOR,state.peer));state.mode=draft.mode||'invoke';
  render();
  window.ACSStudy={ getState:()=>({...state,visibleIds:visible().map(m=>m.id)}), focus:gotoFocus, full:exitFocus, jump:jumpOriginal, return:returnFromOriginal, peer:switchPeer, anchor };
  function renderSourceTrial() {
    // This uses the original AppWindow/Sidebar/Transcript/UserMessage/
    // AssistantMessage/ChatInput geometry without the ACS reading extensions.
    const turn='<p>Panel height now animates on the compositor and the transcript re-measures once, when the gesture ends.</p>';
    document.getElementById('app').innerHTML=`<div class="mb-4 flex items-center justify-between text-xs text-muted-foreground"><span>Pigi · original website presentation trial · 7f8e1c6</span><a href="index.html" class="underline underline-offset-2">ACS study</a></div><div class="relative mx-auto w-full max-w-none overflow-hidden rounded-xl border border-[var(--window-border)] bg-background shadow-[var(--window-shadow)]" style="height:800px;max-width:1200px"><div class="pointer-events-none absolute left-5 top-5 z-10 flex gap-2"><span class="traffic-light bg-[#ff5f57]"></span><span class="traffic-light bg-[#febc2e]"></span><span class="traffic-light bg-[#28c840]"></span></div><div class="flex h-full"><aside class="flex shrink-0 flex-col bg-[var(--sidebar-solid)]" style="width:244px"><div class="h-11 shrink-0"></div><div class="flex flex-col gap-0.5 px-2"><div class="flex h-8 items-center gap-2 rounded-md px-2 text-sm text-sidebar-foreground/85">${icon('plus')}New chat</div><div class="flex h-8 items-center gap-2 rounded-md px-2 text-sm text-sidebar-foreground/85">${icon('folder-plus')}Open project</div></div><div class="mt-4 flex min-h-0 flex-1 flex-col gap-0.5 overflow-hidden px-2"><p class="px-2 pb-1 text-xs text-sidebar-foreground/55">Projects</p><div class="flex h-8 items-center gap-2 rounded-md px-2 text-sm text-sidebar-foreground/85">${icon('chevron-right',14)}${icon('folder',15)}pigi</div><div class="flex h-8 items-center gap-2 rounded-md bg-[var(--system-accent)]/10 pl-8 pr-2 text-sm text-foreground"><span class="truncate">fix transcript flicker</span></div><div class="flex h-8 items-center gap-2 rounded-md px-2 text-sm text-sidebar-foreground/85">${icon('chevron-right',14)}${icon('folder',15)}pi-extension</div><div class="flex h-8 items-center gap-2 rounded-md px-2 text-sm text-sidebar-foreground/85">${icon('chevron-right',14)}${icon('folder',15)}docs-site</div></div><div class="px-2 pb-2"><div class="flex h-8 items-center gap-2 rounded-md px-2 text-sm text-sidebar-foreground/85">${icon('settings')}Settings</div></div></aside><div class="relative flex min-w-0 flex-1 flex-col overflow-hidden border-l-[0.5px] border-foreground/27 bg-background"><div class="relative z-10 flex h-11 shrink-0 items-center gap-2 border-b-[0.5px] border-foreground/27 px-3">${icon('notebook')}<span class="text-sm font-medium text-foreground">fix transcript flicker</span><div class="flex-1"></div><div class="${ui.TOOLBAR_BUTTON.classes}">${icon('binary-tree-2')}</div><div class="${ui.TOOLBAR_BUTTON.classes}">${icon('terminal-2')}</div><div class="${ui.TOOLBAR_BUTTON.classes}">${icon('filter-2')}</div></div><div class="relative min-h-0 flex-1"><div class="h-full overflow-y-auto"><div class="mx-auto flex w-full flex-col" style="max-width:860px;padding-inline:20px;padding-top:24px;padding-bottom:32px"><div class="group flex justify-end pb-2 pt-6"><div class="flex max-w-[85%] flex-col items-end"><div class="w-fit max-w-full overflow-clip rounded-2xl bg-muted px-3.5 py-2"><div class="whitespace-pre-wrap break-words text-[15px] leading-6 text-foreground">the transcript flickers while the terminal panel animates open</div></div></div></div><div class="group flex justify-start mt-2"><div class="w-full min-w-0 text-[15px] text-foreground"><div class="markdown-body">${turn}</div></div></div></div></div></div><div class="shrink-0 px-5"><div class="relative mx-auto w-full" style="max-width:820px"><div class="flex ${ui.CHAT_CARD.classes} min-h-28"><div class="min-h-16 flex-initial px-4 pb-2 pt-4 text-sm leading-5 text-muted-foreground/70">Ask for follow-up changes</div><div class="flex min-w-0 items-center justify-between gap-2 px-2.5 pb-2.5 pt-0"><div class="flex min-w-0 flex-1 items-center gap-1.5 overflow-hidden px-1">${icon('plus')}</div><div class="flex shrink-0 items-baseline gap-1.5 pl-2"><span class="text-sm text-foreground">DeepSeek V4.1 Flash</span><span class="text-xs text-muted-foreground">max</span>${icon('chevron-down',14)}</div><span class="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted-foreground text-background">${icon('arrow-up')}</span></div></div></div><div class="mx-auto flex w-full items-center justify-between gap-4 bg-background px-4 pb-3 pt-1.5 text-sm text-muted-foreground" style="max-width:820px"><span class="flex items-center gap-1.5">${icon('git-branch')}main</span><span>1.2%/1000k (auto)</span></div></div></div></div></div>`;
  }
})();
