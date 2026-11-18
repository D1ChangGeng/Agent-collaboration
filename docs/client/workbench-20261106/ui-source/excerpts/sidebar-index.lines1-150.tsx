import React, { useEffect, useMemo } from 'react'
import { useAppStore } from '@/store'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useSidebarResize } from '@/hooks/useSidebarResize'
import SidebarHeader from './SidebarHeader'
import SidebarNav from './SidebarNav'
import { setSidebarLiveWidth } from './sidebar-live-width'
import { SidebarSeamScrollbarStrip } from './SidebarSeamScrollbarStrip'
import SetupScriptPromptCard from './SetupScriptPromptCard'
import WorktreeList from './worktree-list/listing/WorktreeList'
import WslMovedProjectsSection from './WslMovedProjectsSection'
import SidebarToolbar from './SidebarToolbar'
import WorkspaceKanbanDrawer from './workspace-board/surface/WorkspaceKanbanDrawer'
import type { VirtualizedScrollAnchor } from '@/hooks/useVirtualizedScrollAnchor'
import { cn } from '@/lib/utils'
import { FolderPlus, Loader2 } from 'lucide-react'
import { ActivityThreadCollapseContext } from '@/components/activity/activity-thread-collapse-context'
import { useSidebarProjectDrop } from './project-admission/drop/useSidebarProjectDrop'
import { useWorkspaceBoardPanel } from './workspace-board/surface/useWorkspaceBoardPanel'
import { useWorkspaceRevealBodyRedirect } from './worktree-list/navigation/use-workspace-reveal-body-redirect'
import { resolveLeftSidebarStyleVariables } from '@/lib/left-sidebar-appearance'
import { lazyWithRetry } from '@/lib/lazy-with-retry'
import { LocalGitToolchainScanBanner } from './LocalGitToolchainScanBanner'
import { SeveredTerminalDaemonBanner } from './SeveredTerminalDaemonBanner'
import { StalledTerminalDaemonBanner } from './StalledTerminalDaemonBanner'
import { StartupWorktreeRefreshStatus } from './StartupWorktreeRefreshStatus'

// Keep the Agents activity pipeline out of the workspace view’s initial bundle.
const SidebarAgentsList = lazyWithRetry(() => import('./SidebarAgentsList'))

const WorktreeMetaDialog = lazyWithRetry(
  () => import('./workspace-card/metadata/WorktreeMetaDialog')
)
const RemoveFolderDialog = lazyWithRetry(() => import('./RemoveFolderDialog'))
const SleepTwinWorkspaceDialog = lazyWithRetry(
  () => import('./workspace-actions/sleep/SleepTwinWorkspaceDialog')
)
const WorktreeVisibilityDialog = lazyWithRetry(
  () => import('./workspace-visibility/dialog/WorktreeVisibilityDialog')
)
const OrcaYamlTrustDialog = lazyWithRetry(() => import('./OrcaYamlTrustDialog'))
const ForgetSshWorkspaceDialog = lazyWithRetry(
  () => import('./workspace-actions/deletion/ForgetSshWorkspaceDialog')
)
const AgentDashboardSidebarHost = lazyWithRetry(() => import('./AgentDashboardSidebarHost'))

const MIN_WIDTH = 220
const MAX_WIDTH = 500
// Why: start past the seam scrollbar strip so the list scrollbar stays grabbable from both sides of the seam.
export const WORKTREE_SIDEBAR_RESIZE_HANDLE_CLASS_NAME =
  'peer absolute -right-3.5 top-0 z-10 h-full w-2.5 cursor-col-resize'
// Why: an open drawer covers the outer side of the seam, so keep the inner overlap wide enough to grab.
const WORKTREE_SIDEBAR_RESIZE_HANDLE_UNDER_DRAWER_CLASS_NAME = '-right-1.5 w-3'
export const WORKTREE_SIDEBAR_RESIZE_HANDLE_LINE_CLASS_NAME =
  'pointer-events-none absolute -right-px top-0 z-10 h-full w-px bg-transparent transition-colors peer-hover:bg-ring/50 peer-active:bg-ring'

type SidebarProps = {
  worktreeScrollOffsetRef: React.MutableRefObject<number>
  worktreeScrollAnchorRef: React.MutableRefObject<VirtualizedScrollAnchor>
}

function Sidebar({
  worktreeScrollOffsetRef,
  worktreeScrollAnchorRef
}: SidebarProps): React.JSX.Element {
  const sidebarOpen = useAppStore((s) => s.sidebarOpen)
  const sidebarWidth = useAppStore((s) => s.sidebarWidth)
  const setSidebarWidth = useAppStore((s) => s.setSidebarWidth)
  const repos = useAppStore((s) => s.repos)
  const startupWorktreeRefreshCompleted = useAppStore((s) => s.startupWorktreeRefreshCompleted)
  const settings = useAppStore((s) => s.settings)
  const sidebarBody = useAppStore((s) => s.sidebarBody ?? 'workspaces')
  const showAgentDashboard = settings?.experimentalAgentDashboardPopout === true
  const agentDashboardDrawerOpen = useAppStore((s) => s.agentDashboardDrawerOpen)
  const setAgentDashboardDrawerOpen = useAppStore((s) => s.setAgentDashboardDrawerOpen)
  const agentReadFilter = useAppStore((s) => s.agentsReadFilter)
  const setAgentReadFilter = useAppStore((s) => s.setAgentsReadFilter)
  const agentGroupBy = useAppStore((s) => s.agentsGroupBy)
  const setAgentGroupBy = useAppStore((s) => s.setAgentsGroupBy)
  const [agentQuery, setAgentQuery] = React.useState('')
  const [agentOptionsTarget, setAgentOptionsTarget] = React.useState<HTMLDivElement | null>(null)
  const agentsScrollTopRef = React.useRef(0)
  // Retain collapse state and scroll geometry across Agents-list unmounts.
  const [agentsCollapsedGroupKeys, setAgentsCollapsedGroupKeys] = React.useState<
    ReadonlySet<string>
  >(() => new Set())
  const agentsCollapseState = useMemo(
    () => ({
      collapsedGroupKeys: agentsCollapsedGroupKeys,
      onToggleGroupCollapse: (groupKey: string) =>
        setAgentsCollapsedGroupKeys((prev) => {
          const next = new Set(prev)
          if (next.has(groupKey)) {
            next.delete(groupKey)
          } else {
            next.add(groupKey)
          }
          return next
        })
    }),
    [agentsCollapsedGroupKeys]
  )
  const fetchAllWorktrees = useAppStore((s) => s.fetchAllWorktrees)
  const activeModal = useAppStore((s) => s.activeModal)
  const statusBarVisible = useAppStore((s) => s.statusBarVisible)
  const leftSidebarStyle = useMemo(() => resolveLeftSidebarStyleVariables(settings), [settings])
  const { dropOwnerRef, dropHandlers, affordance } = useSidebarProjectDrop()
  const {
    workspaceBoardOpen,
    workspaceBoardRenderedOpen,
    workspaceBoardDragPreviewOpen,
    workspaceBoardMenuOpen,
    toggleWorkspaceBoard,
    handleWorkspaceBoardOpenChange,
    setWorkspaceBoardMenuOpen,
    closeWorkspaceBoard,
    previewWorkspaceBoardFromDrag,
    solidifyWorkspaceBoardFromDrag,
    cancelWorkspaceBoardDragPreview
  } = useWorkspaceBoardPanel()

  const repoCount = repos.length
  const previousRepoCountRef = React.useRef(repoCount)
  useEffect(() => {
    const repoCountChanged = previousRepoCountRef.current !== repoCount
    previousRepoCountRef.current = repoCount
    // Why: App owns the initial all-host scan; partial startup catalogs must not trigger broad scans or stale-state purges.
    if (startupWorktreeRefreshCompleted && repoCountChanged && repoCount > 0) {
      void fetchAllWorktrees()
    }
  }, [repoCount, startupWorktreeRefreshCompleted, fetchAllWorktrees])

  useEffect(() => {
    if (!sidebarOpen && workspaceBoardRenderedOpen) {
      closeWorkspaceBoard()
    }
  }, [closeWorkspaceBoard, sidebarOpen, workspaceBoardRenderedOpen])

  useEffect(() => {
    if (!showAgentDashboard && agentDashboardDrawerOpen) {
      setAgentDashboardDrawerOpen(false)
    }
  }, [agentDashboardDrawerOpen, setAgentDashboardDrawerOpen, showAgentDashboard])

  const { containerRef, onResizeStart, isResizing } = useSidebarResize<HTMLDivElement>({
    isOpen: sidebarOpen,
    width: sidebarWidth,
    minWidth: MIN_WIDTH,
    maxWidth: MAX_WIDTH,
    deltaSign: 1,
