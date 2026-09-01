import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import styled from 'styled-components';
import {
  PanelLeftClose,
  PanelLeft,
  Settings,
  Upload,
  Loader2,
  AlertCircle,
} from 'lucide-react';
import { Button, Tooltip } from '@radix-ui/themes';
import {
  playlistLabel,
  versionCountLabel,
  type Playlist,
  type Version,
  type DraftNote,
} from '@dna/core';
import { Logo } from './Logo';
import { UserAvatar } from './UserAvatar';
import { SplitButton, type SplitButtonMenuItem } from './SplitButton';
import {
  ExpandableSearch,
  type ExpandableSearchHandle,
} from './ExpandableSearch';
import { SquareButton } from './SquareButton';
import { VersionCard } from './VersionCard';
import { noteStatus, noteProvenance } from './noteStatus';
import { TranscriptionMenu } from './TranscriptionMenu';
import { SettingsModal } from './SettingsModal';
import { PublishDialog } from './PublishDialog';
import { AddVersionsInput } from './AddVersionsInput';
import {
  useGetVersionsForPlaylist,
  useGetUserByEmail,
  useGetPlaylistsForProject,
} from '../api';
import { usePlaylistMetadata, usePlaylistDraftNotes } from '../hooks';
import { useHotkeyAction, useHotkeyConfig } from '../hotkeys';
import { useFeatureFlags } from '../contexts';

interface SidebarProps {
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  onReplacePlaylist?: () => void;
  /** Switch to another playlist in the same project, without going back to the picker. */
  onPlaylistSelect?: (playlist: Playlist) => void;
  /** Project the open playlist belongs to — whose recent playlists the menu offers. */
  projectId?: number | null;
  playlistId: number | null;
  /** What to call the playlist on screen — see `playlistLabel`. */
  playlistTitle?: string;
  selectedVersionId?: number | null;
  /** Version the followed review session is showing. Marked, never selected. */
  followedVersionId?: number | null;
  onVersionSelect?: (version: Version) => void;
  userEmail: string;
  onLogout?: () => void;
}

const SidebarWrapper = styled.aside<{ $collapsed: boolean }>`
  position: fixed;
  left: 0;
  top: 0;
  height: 100vh;
  width: ${({ theme, $collapsed }) =>
    $collapsed ? theme.sizes.sidebar.collapsed : theme.sizes.sidebar.expanded};
  background: ${({ theme }) => theme.colors.sidebar.bg};
  border-right: 1px solid ${({ theme }) => theme.colors.sidebar.border};
  display: flex;
  flex-direction: column;
  transition: width ${({ theme }) => theme.transitions.base};
  z-index: 100;
  overflow: hidden;
`;

const Header = styled.div<{ $collapsed: boolean }>`
  padding: ${({ $collapsed }) => ($collapsed ? '12px 8px' : '12px 16px')};
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid ${({ theme }) => theme.colors.border.subtle};
  min-height: 64px;
  gap: ${({ $collapsed }) => ($collapsed ? '4px' : '0')};
`;

const HeaderActions = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
`;

const CollapseButton = styled.button`
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: ${({ theme }) => theme.radii.sm};
  border: none;
  background: transparent;
  color: ${({ theme }) => theme.colors.text.muted};
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.fast};
  flex-shrink: 0;

  &:hover {
    background: ${({ theme }) => theme.colors.bg.surfaceHover};
    color: ${({ theme }) => theme.colors.text.primary};
  }

  svg {
    width: 20px;
    height: 20px;
  }
`;

// Which playlist this is. It sits directly above the version list because that list, the
// transcription controls and the playlist menu all act on this one playlist, and none of them say
// so — once the picker closes, nothing on screen names what is being reviewed.
// One value for the space above the name and the space below it, so the name sits centred between
// the actions and the rule rather than crowded up against one of them.
const TITLE_BAR_SPACING = '10px';

const PlaylistTitleBar = styled.div`
  padding: ${TITLE_BAR_SPACING} 16px;
  border-bottom: 1px solid ${({ theme }) => theme.colors.border.subtle};
  display: flex;
  flex-direction: column;
  gap: ${TITLE_BAR_SPACING};
  min-width: 0;
`;

// The actions ride above the name rather than beside it: they are small and of fixed width, and
// the name below then keeps the full width of the rail, which it needs — playlist names are long
// and it is their tail that tells two of them apart.
const PlaylistTitleRow = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
`;

// Everything you can do to the list, packed against the left edge. It takes the row's spare width
// so the search stays pinned right, and so the Add pill has somewhere to open into.
const PlaylistActions = styled.div`
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
`;

// The ShotGrid id, on the name's own line and in brackets after it. It is what people paste into
// a ticket or a URL when they need to say which playlist they mean — worth having in reach, not
// worth a line or a weight of its own.
const PlaylistIdText = styled.span`
  font-size: 11px;
  font-weight: 500;
  font-family: ${({ theme }) => theme.fonts.mono};
  color: ${({ theme }) => theme.colors.text.muted};
  margin-left: 4px;
  white-space: nowrap;
`;

// The name gets a card of its own, like the versions below it. Bare text could only ever line up
// with one of the two columns the sidebar keeps — the edges every box starts at, or the text
// inside those boxes, 13px further in — and looked adrift of whichever one it missed. In a box it
// is on both: this edge with the buttons and cards, its text with their text.
const PlaylistTitleCard = styled.div`
  padding: 10px 12px;
  background: ${({ theme }) => theme.colors.bg.surface};
  border: 1px solid ${({ theme }) => theme.colors.border.subtle};
  border-radius: ${({ theme }) => theme.radii.lg};
  min-width: 0;
`;

const PlaylistTitleText = styled.span`
  font-size: 13px;
  font-weight: 600;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.primary};
  // Playlist names are long and end in the part that distinguishes them ("… - 08/25/26"), so the
  // tail is worth more than the head. Two lines keep it readable in a 280px rail; the tooltip has
  // the whole thing for anything longer.
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.35;
  word-break: break-word;
`;

const ScrollableContent = styled.div`
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
`;

const Footer = styled.div<{ $collapsed: boolean }>`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: ${({ $collapsed }) => ($collapsed ? '12px 8px' : '12px 16px')};
  border-top: 1px solid ${({ theme }) => theme.colors.border.subtle};
  gap: 8px;
`;

const SettingsButton = styled.button`
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  height: 32px;
  font-size: 14px;
  font-weight: 500;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.secondary};
  background: transparent;
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.md};
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.fast};
  white-space: nowrap;

  &:hover {
    background: ${({ theme }) => theme.colors.bg.surfaceHover};
    color: ${({ theme }) => theme.colors.text.primary};
    border-color: ${({ theme }) => theme.colors.border.strong};
  }

  &:active {
    background: ${({ theme }) => theme.colors.bg.overlay};
    transform: translateY(1px);
  }
`;

const CollapsedToolbar = styled.div`
  display: flex;
  justify-content: center;
  padding: 12px 8px;
  border-bottom: 1px solid ${({ theme }) => theme.colors.border.subtle};
`;

const CollapsedFooter = styled.div`
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 8px;
  border-top: 1px solid ${({ theme }) => theme.colors.border.subtle};
  gap: 12px;
`;

const VersionCardList = styled.div`
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 16px;
`;

const VersionListContainer = styled.div`
  position: relative;
`;

const RefetchOverlay = styled.div`
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: ${({ theme }) => theme.colors.bg.base}cc;
  z-index: 10;
`;

const StateContainer = styled.div`
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
  gap: 12px;
  color: ${({ theme }) => theme.colors.text.muted};
  text-align: center;
`;

const LoadingSpinner = styled(Loader2)`
  width: 24px;
  height: 24px;
  color: ${({ theme }) => theme.colors.accent.main};
  animation: spin 1s linear infinite;

  @keyframes spin {
    from {
      transform: rotate(0deg);
    }
    to {
      transform: rotate(360deg);
    }
  }
`;

const ErrorIcon = styled(AlertCircle)`
  width: 24px;
  height: 24px;
  color: ${({ theme }) => theme.colors.status.error};
`;

const StateText = styled.span`
  font-size: 13px;
`;

export function Sidebar({
  collapsed,
  onCollapsedChange,
  onReplacePlaylist,
  onPlaylistSelect,
  projectId,
  playlistId,
  playlistTitle,
  selectedVersionId,
  followedVersionId,
  onVersionSelect,
  userEmail,
  onLogout,
}: SidebarProps) {
  const [isSearchExpanded, setIsSearchExpanded] = useState(false);
  const [isAddVersionExpanded, setIsAddVersionExpanded] = useState(false);
  const [isPublishDialogOpen, setIsPublishDialogOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const versionRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<ExpandableSearchHandle>(null);

  // Either pill takes the whole title row when it opens, so the label and the playlist menu
  // step aside for whichever one it is.
  const rowExpanded = isSearchExpanded || isAddVersionExpanded;

  const { getLabel } = useHotkeyConfig();
  const { transcriptionEnabled, inReviewEnabled } = useFeatureFlags();

  const toggleSettings = useCallback(() => {
    setIsSettingsOpen((prev) => !prev);
  }, []);

  useHotkeyAction('openSettings', toggleSettings);
  useHotkeyAction('toggleSidebar', () => onCollapsedChange(!collapsed));
  useHotkeyAction('focusSearch', () => searchRef.current?.focus());

  const {
    data: versions,
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
  } = useGetVersionsForPlaylist(playlistId);

  const { data: user } = useGetUserByEmail(userEmail);
  const { data: playlistMetadata } = usePlaylistMetadata(playlistId);
  // Same query the login picker runs, so switching from here costs nothing once either has
  // loaded it: the backend returns the project's most recent playlists, newest first.
  const { data: recentPlaylists } = useGetPlaylistsForProject(
    projectId ?? null
  );
  const { data: draftNotes } = usePlaylistDraftNotes(playlistId);

  const publishDialogNotes = useMemo(
    () =>
      (draftNotes ?? []).filter((n: DraftNote) => {
        const hasContent =
          Boolean(n.content?.trim()) || Boolean(n.attachment_ids?.length);
        const needsPublishing =
          !n.published || n.edited || Boolean(n.attachment_ids?.length);
        return hasContent && needsPublishing;
      }),
    [draftNotes]
  );

  const inReviewVersionId = playlistMetadata?.in_review;

  // Bring the followed version into view only when it is out of sight. The
  // review session changes clip constantly, so scrolling on every change would
  // pull the list around under someone who is reading it; a row already on
  // screen needs no help. The delay lets a freshly rendered row register first.
  useEffect(() => {
    if (followedVersionId == null) {
      return;
    }

    const timer = setTimeout(() => {
      const element = versionRefs.current.get(followedVersionId);
      const container = scrollContainerRef.current;
      if (!element || !container) {
        return;
      }

      const row = element.getBoundingClientRect();
      const view = container.getBoundingClientRect();
      if (row.top >= view.top && row.bottom <= view.bottom) {
        return;
      }

      element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 50);

    return () => clearTimeout(timer);
  }, [followedVersionId]);

  // The other recent playlists on the show, switchable in one click. The picker stays on the end
  // of the list because it is still the only way to reach an older playlist or another project —
  // it is the fallback now, not the way through.
  const playlistMenuItems: SplitButtonMenuItem[] = [
    ...(recentPlaylists ?? [])
      .filter((playlist) => playlist.id !== playlistId)
      .map((playlist) => ({
        label: playlistLabel(playlist),
        meta: versionCountLabel(playlist.version_count),
        onSelect: () => onPlaylistSelect?.(playlist),
      })),
    {
      label: 'Other Playlist…',
      onSelect: onReplacePlaylist,
      separatorBefore: (recentPlaylists?.length ?? 0) > 0,
    },
  ];

  const handleSearchVersionSelect = (version: Version) => {
    onVersionSelect?.(version);

    setTimeout(() => {
      const versionElement = versionRefs.current.get(version.id);
      if (versionElement && scrollContainerRef.current) {
        versionElement.scrollIntoView({
          behavior: 'smooth',
          block: 'center',
        });
      }
    }, 50);
  };

  const renderVersionList = () => {
    if (!playlistId) {
      return (
        <StateContainer>
          <StateText>Select a playlist to view versions</StateText>
        </StateContainer>
      );
    }

    if (isLoading) {
      return (
        <StateContainer>
          <LoadingSpinner />
          <StateText>Loading versions...</StateText>
        </StateContainer>
      );
    }

    if (isError) {
      return (
        <StateContainer>
          <ErrorIcon />
          <StateText>{error?.message || 'Failed to load versions'}</StateText>
        </StateContainer>
      );
    }

    if (!versions || versions.length === 0) {
      return (
        <StateContainer>
          <StateText>No versions in this playlist</StateText>
        </StateContainer>
      );
    }

    const isRefetching = isFetching && !isLoading;

    return (
      <VersionListContainer>
        {isRefetching && (
          <RefetchOverlay>
            <LoadingSpinner />
          </RefetchOverlay>
        )}
        <VersionCardList>
          {versions.map((version) => (
            <div
              key={version.id}
              ref={(el) => {
                if (el) {
                  versionRefs.current.set(version.id, el);
                } else {
                  versionRefs.current.delete(version.id);
                }
              }}
            >
              <VersionCard
                version={version}
                artistName={version.user?.name}
                department={version.task?.pipeline_step?.name}
                thumbnailUrl={version.thumbnail}
                selected={version.id === selectedVersionId}
                inReview={inReviewEnabled && inReviewVersionId === version.id}
                followed={
                  followedVersionId != null && version.id === followedVersionId
                }
                noteStatus={noteStatus(
                  noteProvenance(
                    draftNotes?.find((n) => n.version_id === version.id)
                  )
                )}
                onClick={() => onVersionSelect?.(version)}
              />
            </div>
          ))}
        </VersionCardList>
      </VersionListContainer>
    );
  };

  return (
    <SidebarWrapper $collapsed={collapsed}>
      <Header $collapsed={collapsed}>
        <Logo showText={!collapsed} width={collapsed ? 32 : 120} />
        <HeaderActions>
          {!collapsed && (
            <>
              <Button
                size="2"
                variant="solid"
                onClick={() => setIsPublishDialogOpen(true)}
              >
                Publish
              </Button>
              <UserAvatar
                name={user?.name ?? userEmail}
                size="2"
                onLogout={onLogout}
              />
            </>
          )}
          <Tooltip
            content={`${collapsed ? 'Expand' : 'Collapse'} Sidebar (${getLabel('toggleSidebar')})`}
          >
            <CollapseButton
              onClick={() => onCollapsedChange(!collapsed)}
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {collapsed ? <PanelLeft /> : <PanelLeftClose />}
            </CollapseButton>
          </Tooltip>
        </HeaderActions>
      </Header>

      {!collapsed && (
        <PlaylistTitleBar>
          <PlaylistTitleRow>
            {/* Two ways of acting on the list below, side by side at the left edge. Either one
                opens into the whole row, so the other stands down while it is open. */}
            {!isSearchExpanded && (
              <PlaylistActions>
                {!rowExpanded && (
                  <SplitButton
                    menuItems={playlistMenuItems}
                    onClick={() => refetch()}
                  >
                    Reload Playlist
                  </SplitButton>
                )}
                <AddVersionsInput
                  playlistId={playlistId}
                  onExpandedChange={setIsAddVersionExpanded}
                />
              </PlaylistActions>
            )}

            {!isAddVersionExpanded && (
              <ExpandableSearch
                ref={searchRef}
                placeholder="Search versions..."
                versions={versions}
                selectedVersionId={selectedVersionId}
                onVersionSelect={handleSearchVersionSelect}
                onExpandedChange={setIsSearchExpanded}
              />
            )}
          </PlaylistTitleRow>

          {playlistTitle && (
            <Tooltip content={playlistTitle}>
              <PlaylistTitleCard>
                <PlaylistTitleText>
                  {playlistTitle}
                  {/* `playlistLabel` already falls back to "Playlist <id>" for an unnamed playlist,
                    so printing the id here too would just say it twice. */}
                  {playlistId !== null &&
                    !playlistTitle.includes(String(playlistId)) && (
                      <PlaylistIdText>(#{playlistId})</PlaylistIdText>
                    )}
                </PlaylistTitleText>
              </PlaylistTitleCard>
            </Tooltip>
          )}
        </PlaylistTitleBar>
      )}

      {collapsed && (
        <CollapsedToolbar>
          {transcriptionEnabled && (
            <TranscriptionMenu playlistId={playlistId} collapsed />
          )}
        </CollapsedToolbar>
      )}

      <ScrollableContent ref={scrollContainerRef}>
        {!collapsed && renderVersionList()}
      </ScrollableContent>

      {collapsed ? (
        <CollapsedFooter>
          <SquareButton
            variant="cta"
            onClick={() => setIsPublishDialogOpen(true)}
          >
            <Upload />
            Publish
          </SquareButton>
          <Tooltip content={`Settings (${getLabel('openSettings')})`}>
            <SquareButton variant="neutral" onClick={toggleSettings}>
              <Settings />
              Settings
            </SquareButton>
          </Tooltip>
          <SettingsModal
            userEmail={userEmail}
            open={isSettingsOpen}
            onOpenChange={setIsSettingsOpen}
          />
        </CollapsedFooter>
      ) : (
        <Footer $collapsed={collapsed}>
          {transcriptionEnabled && (
            <TranscriptionMenu playlistId={playlistId} />
          )}
          <Tooltip content={`Settings (${getLabel('openSettings')})`}>
            <SettingsButton onClick={toggleSettings}>
              <Settings size={16} />
              Settings
            </SettingsButton>
          </Tooltip>
          <SettingsModal
            userEmail={userEmail}
            open={isSettingsOpen}
            onOpenChange={setIsSettingsOpen}
          />
        </Footer>
      )}

      {playlistId && (
        <PublishDialog
          open={isPublishDialogOpen}
          onClose={() => setIsPublishDialogOpen(false)}
          playlistId={playlistId}
          userEmail={userEmail}
          notes={publishDialogNotes}
          versions={versions || []}
        />
      )}
    </SidebarWrapper>
  );
}
