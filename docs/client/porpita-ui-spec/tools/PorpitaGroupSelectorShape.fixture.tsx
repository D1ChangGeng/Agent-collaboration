import { useState } from 'react'
import { ChevronDown, Folder, List } from 'lucide-react'
import { DndContext, pointerWithin, useDroppable, useSensor, useSensors } from '@dnd-kit/core'
import { defineFixture } from '../../component-fixtures/component-fixture'
import { Button } from '../ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger
} from '../ui/dropdown-menu'
import { TabDragPointerSensor } from '../tab-group/tab-drag-pointer-sensor'
import TabBar from './TabBar'
import type { TerminalTab } from '../../../../shared/workspace-layout/terminal-tab-types'

const FIXTURE_OWNER = 'porpita-group-selector-specimen'
const GROUP_TRIGGER = 'group-trigger'
const GROUP_NAMES = [
  'Porpita · 桌面端国际化与交付验收',
  'ACS',
  'Remote lab',
  '一般工作',
  'Agent workspace accessibility',
  'Bug triage',
  'CLI Integration',
  'Plugin testing',
  'Diff and review',
  'Mixed platform QA',
  'Long-running terminal tools',
  'Release archive'
]
const TAB_NAMES = [
  'Workspace layout verification',
  'Native Chat approval and tool replay',
  '跨项目工作台恢复与多会话布局回放',
  'Settings and local service recovery'
]

function GroupControl({
  group,
  groups,
  open,
  setOpen,
  moving,
  select
}: {
  group: number
  groups: string[]
  open: boolean
  setOpen: (open: boolean) => void
  moving: string | undefined
  select: (index: number) => void
}): React.JSX.Element {
  const { setNodeRef, isOver } = useDroppable({ id: GROUP_TRIGGER, disabled: groups.length < 2 })
  return (
    <div ref={setNodeRef} className="flex shrink-0 items-center" data-shape-drop-target="">
      <DropdownMenu onOpenChange={setOpen} open={open}>
        <DropdownMenuTrigger asChild>
          <Button
            variant={isOver ? 'secondary' : 'ghost'}
            size="sm"
            className="mx-1 max-w-[min(132px,31cqw)] min-w-0 gap-1 px-1.5"
            aria-label={`Choose group: ${groups[group]}`}
            data-shape-highlight={isOver}
          >
            <Folder className="size-3 shrink-0" />
            <span className="min-w-0 truncate">{groups[group]}</span>
            <ChevronDown className="size-3 shrink-0" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="start"
          className="max-w-[min(320px,calc(100vw-16px))] max-h-(--radix-dropdown-menu-content-available-height) overflow-y-auto"
        >
          {moving ? <DropdownMenuLabel>Move {moving}</DropdownMenuLabel> : null}
          <DropdownMenuRadioGroup
            value={String(group)}
            onValueChange={(value) => select(Number(value))}
          >
            {groups.map((name, index) => (
              <DropdownMenuRadioItem
                value={String(index)}
                key={name}
                disabled={Boolean(moving && index === group)}
              >
                <span className="break-words">{name}</span>
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

type Row = { id: string; title: string; group: number }

function Shape({ count, groupCount }: { count: number; groupCount: number }): React.JSX.Element {
  const groups = GROUP_NAMES.slice(0, groupCount)
  const [rows, setRows] = useState<Row[]>(() =>
    groups.flatMap((name, group) =>
      Array.from({ length: group === 0 ? count : 1 }, (_, index) => ({
        id: `work-${group}-${index}`,
        title:
          group === 0
            ? `${TAB_NAMES[index % TAB_NAMES.length]} ${index + 1}`
            : `${name} · 交付回放`,
        group
      }))
    )
  )
  const [group, setGroup] = useState(0)
  const [recent, setRecent] = useState<Record<number, string>>({ 0: 'work-0-0' })
  const [pendingMove, setPendingMove] = useState<string | null>(null)
  const [chooserOpen, setChooserOpen] = useState(false)
  const [announce, setAnnounce] = useState('')
  const sensors = useSensors(
    useSensor(TabDragPointerSensor, { activationConstraint: { distance: 6 } })
  )
  const visible = rows.filter((row) => row.group === group)
  const active = visible.find((row) => row.id === recent[group])?.id ?? visible[0]?.id ?? null
  const select = (id: string): void => {
    const selected = rows.find((row) => row.id === id)
    if (selected) {
      setGroup(selected.group)
      setRecent((previous) => ({ ...previous, [selected.group]: id }))
    }
  }
  const openMove = (id: string): void => {
    setPendingMove(id)
    setChooserOpen(true)
  }
  const changeGroup = (index: number): void => {
    if (pendingMove) {
      setPendingMove(null)
      const moved = rows.find((row) => row.id === pendingMove)
      if (moved && moved.group !== index) {
        setRows((previous) => [
          ...previous.filter((row) => row.id !== moved.id),
          { ...moved, group: index }
        ])
        setAnnounce(`Moved ${moved.title} to ${groups[index]}`)
      }
      return
    }
    setGroup(index)
  }
  const tabs: TerminalTab[] = visible.map((row, sortOrder) => ({
    id: row.id,
    worktreeId: FIXTURE_OWNER,
    ptyId: null,
    title: row.title,
    customTitle: null,
    color: null,
    sortOrder,
    createdAt: 0
  }))
  return (
    <DndContext
      sensors={sensors}
      collisionDetection={pointerWithin}
      onDragEnd={({ active: dragged, over }) => {
        if (over?.id === GROUP_TRIGGER) openMove(String(dragged.id))
      }}
    >
      <div
        className="@container/tab-strip flex h-9 min-w-0 items-stretch border-b border-border bg-card"
        data-shape-group={group}
        data-shape-active={active ?? ''}
        data-shape-move={pendingMove ?? ''}
      >
        <GroupControl
          group={group}
          groups={groups}
          open={chooserOpen}
          moving={rows.find((row) => row.id === pendingMove)?.title}
          setOpen={(open) => {
            setChooserOpen(open)
            if (!open) setPendingMove(null)
          }}
          select={changeGroup}
        />
        <TabBar
          tabs={tabs}
          worktreeId={FIXTURE_OWNER}
          activeTabId={active}
          activeTabType="terminal"
          groupId="porpita-selector-research"
          expandedPaneByTabId={{}}
          showAgentLaunchItems={false}
          onActivate={select}
          onClose={noop}
          onCloseOthers={noop}
          onCloseToRight={noop}
          onCloseToLeft={noop}
          onNewTerminalTab={noop}
          onNewBrowserTab={noop}
          onSetCustomTitle={noop}
          onSetTabColor={noop}
          onTogglePaneExpand={noop}
        />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              className="my-auto mr-1 shrink-0"
              size="icon-xs"
              variant="ghost"
              aria-label="Open work"
            >
              <List className="size-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="end"
            className="max-w-[min(340px,calc(100vw-16px))] max-h-(--radix-dropdown-menu-content-available-height) overflow-y-auto"
          >
            {active && groupCount > 1 ? (
              <DropdownMenuItem
                onSelect={() => window.requestAnimationFrame(() => openMove(active))}
              >
                Move current tab to group
              </DropdownMenuItem>
            ) : null}
            {rows.map((row) => (
              <DropdownMenuItem
                key={row.id}
                onSelect={() => select(row.id)}
                data-shape-work-id={row.id}
              >
                <span className="break-words">{row.title}</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <span className="sr-only" role="status">
        {announce}
      </span>
    </DndContext>
  )
}

function noop(): void {}

// The Orca fixture frame adds 16px of padding to each edge.
export const small = defineFixture({ width: 272, render: () => <Shape count={1} groupCount={1} /> })
export const compact = defineFixture({
  width: 452,
  render: () => <Shape count={8} groupCount={4} />
})
export const dense = defineFixture({
  width: 952,
  render: () => <Shape count={30} groupCount={12} />
})
export const compactDense = defineFixture({
  width: 272,
  render: () => <Shape count={30} groupCount={12} />
})
