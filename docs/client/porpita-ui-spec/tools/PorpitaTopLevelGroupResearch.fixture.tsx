import { useState } from 'react'
import { DndContext } from '@dnd-kit/core'
import { defineFixture } from '../../component-fixtures/component-fixture'
import { Button } from '../ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '../ui/dropdown-menu'
import TabBar from './TabBar'
import type { TerminalTab } from '../../../../shared/workspace-layout/terminal-tab-types'

const OWNER = 'porpita-top-level-research-only'
const groups = [
  { id: 'general', name: 'General', titles: ['Cross-project delivery review', 'Release checklist and handover', 'Shared documentation'] },
  { id: 'porpita', name: 'Porpita', titles: ['Root Session and Route Manager', 'Workspace layout verification', 'Explorer · Windows test repo', 'Native Chat approval and tool replay'] },
  { id: 'acs', name: 'ACS', titles: ['Runtime coordination and rollout', 'Connection recovery observations', 'Protocol and scope review'] },
  { id: 'remote', name: 'Remote lab', titles: ['Multi-host workspace comparison', 'Remote repository status'] }
]
const samples = groups.flatMap(group => group.titles.map((title, index) => ({ id: group.id+'-'+index, title, group: group.id })))
const noop = (): void => {}

function Prototype({ mode }: { mode: 'selector' | 'strip' }): React.JSX.Element {
  const [active, setActive] = useState('porpita-0')
  const activeGroup = samples.find(row => row.id === active)?.group ?? 'porpita'
  const openGroup = groups.find(group => group.id === activeGroup) ?? groups[1]
  const showGroup = (id: string) => setActive(samples.find(row => row.group === id)?.id ?? active)
  const visible = samples.filter(row => row.group === activeGroup)
  // TerminalTab is the established Orca fixture carrier for exercising the existing TabBar.
  // These are layout labels only, with no PTY, provider, file or service.
  const tabs: TerminalTab[] = visible.map((row, i) => ({
    id: row.id, worktreeId: OWNER, ptyId: null, title: row.title, customTitle: null,
    color: null, sortOrder: i, createdAt: 0
  }))
  return (
    <DndContext>
      <div className="@container/tab-strip flex h-9 min-w-0 items-stretch border-b border-border bg-card"
        data-probe-mode={mode} data-probe-group={activeGroup} data-probe-active={active}>
        {mode === 'selector' ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="mx-1 self-center" aria-label={'Choose group: '+openGroup.name}>
                {openGroup.name} ▾
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {groups.map(group => <DropdownMenuItem key={group.id} onSelect={() => showGroup(group.id)}>{group.name}</DropdownMenuItem>)}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          <div className="flex shrink-0 items-center border-r border-border" aria-label="Visible group labels">
            {groups.map(group =>
              <Button key={group.id} size="xs" variant={group.id === activeGroup ? 'secondary' : 'ghost'}
                aria-pressed={group.id === activeGroup} onClick={() => showGroup(group.id)}>
                {group.name}
              </Button>
            )}
          </div>
        )}
        <TabBar tabs={tabs} worktreeId={OWNER} activeTabId={active} activeTabType="terminal"
          groupId="porpita-research" expandedPaneByTabId={{}} showAgentLaunchItems={false}
          onActivate={setActive} onClose={noop} onCloseOthers={noop} onCloseToRight={noop}
          onCloseToLeft={noop} onNewTerminalTab={noop} onNewBrowserTab={noop}
          onSetCustomTitle={noop} onSetTabColor={noop} onTogglePaneExpand={noop}/>
      </div>
    </DndContext>
  )
}

export const selectorNarrow = defineFixture({width:420,render:()=><Prototype mode="selector"/>})
export const stripNarrow = defineFixture({width:420,render:()=><Prototype mode="strip"/>})
export const selectorWide = defineFixture({width:920,render:()=><Prototype mode="selector"/>})
export const stripWide = defineFixture({width:920,render:()=><Prototype mode="strip"/>})
export const selectorKeyboard = defineFixture({
  width:420,render:()=><Prototype mode="selector"/>,
  interact: async frame => {
    const control = frame.querySelector<HTMLButtonElement>('[aria-label^="Choose group"]')
    if(!control) throw new Error('Group chooser is missing')
    // The renderer opens the actual DropdownMenu and fires the actual item selection.
    control.focus()
    control.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}))
    for(let i=0;i<20;i++) {
      const item=[...document.querySelectorAll<HTMLElement>('[role=menuitem]')].find(el=>el.innerText==='Remote lab')
      if(item) {
        item.click()
        await new Promise(resolve=>setTimeout(resolve,50))
        if(frame.querySelector('[data-probe-group=remote]')) return
        break
      }
      await new Promise(resolve=>setTimeout(resolve,25))
    }
    throw new Error('Group chooser selection did not activate the Remote lab specimen')
  }
})
