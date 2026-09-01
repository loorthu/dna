import { useState, useEffect, type ReactNode } from 'react';
import styled from 'styled-components';
import type { Playlist, Version } from '@dna/core';
import { Sidebar } from './Sidebar';

interface LayoutProps {
  children: ReactNode;
  onReplacePlaylist?: () => void;
  /** Switch to another playlist in the same project, without going back to the picker. */
  onPlaylistSelect?: (playlist: Playlist) => void;
  /** Project the open playlist belongs to — what the sidebar offers to switch within. */
  projectId?: number | null;
  playlistId: number | null;
  /** What to call the playlist on screen — see `playlistLabel`. */
  playlistTitle?: string;
  selectedVersionId?: number | null;
  /** Version the followed review session is showing, if any. A hint only. */
  followedVersionId?: number | null;
  onVersionSelect?: (version: Version) => void;
  userEmail: string;
  onLogout?: () => void;
}

const COLLAPSE_BREAKPOINT = 1024;

const LayoutWrapper = styled.div`
  display: flex;
  width: 100%;
  min-height: 100%;
  background: ${({ theme }) => theme.colors.bg.base};
`;

const Main = styled.main<{ $sidebarCollapsed: boolean }>`
  flex: 1;
  margin-left: ${({ theme, $sidebarCollapsed }) =>
    $sidebarCollapsed
      ? theme.sizes.sidebar.collapsed
      : theme.sizes.sidebar.expanded};
  padding: 24px 0 24px 32px;
  transition: margin-left ${({ theme }) => theme.transitions.base};
  background:
    radial-gradient(
        ellipse 80% 50% at 50% -20%,
        ${({ theme }) => theme.colors.accent.subtle},
        transparent
      )
      fixed,
    ${({ theme }) => theme.colors.bg.base};
  min-height: 100%;
`;

export function Layout({
  children,
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
}: LayoutProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => window.innerWidth < COLLAPSE_BREAKPOINT
  );

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < COLLAPSE_BREAKPOINT) {
        setSidebarCollapsed(true);
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return (
    <LayoutWrapper>
      <Sidebar
        collapsed={sidebarCollapsed}
        onCollapsedChange={setSidebarCollapsed}
        onReplacePlaylist={onReplacePlaylist}
        onPlaylistSelect={onPlaylistSelect}
        projectId={projectId}
        playlistId={playlistId}
        playlistTitle={playlistTitle}
        selectedVersionId={selectedVersionId}
        followedVersionId={followedVersionId}
        onVersionSelect={onVersionSelect}
        userEmail={userEmail}
        onLogout={onLogout}
      />
      <Main $sidebarCollapsed={sidebarCollapsed}>{children}</Main>
    </LayoutWrapper>
  );
}
