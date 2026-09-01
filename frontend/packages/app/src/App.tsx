import { useState, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Playlist, playlistLabel, Project, Version } from '@dna/core';
import { Layout, ContentArea, ProjectSelector } from './components';
import { useAuth } from './contexts';
import { useGetVersionsForPlaylist } from './api';
import { usePlaylistMetadata } from './hooks/usePlaylistMetadata';
import { useFollowAlong } from './hooks/useFollowAlong';

function App() {
  const queryClient = useQueryClient();
  const { signOut } = useAuth();
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [selectedPlaylist, setSelectedPlaylist] = useState<Playlist | null>(
    null
  );
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<Version | null>(null);

  const { data: versions = [], refetch } = useGetVersionsForPlaylist(
    selectedPlaylist?.id ?? null
  );

  const { data: playlistMetadata } = usePlaylistMetadata(
    selectedPlaylist?.id ?? null
  );

  const { followedVersion } = useFollowAlong({
    show: selectedProject?.code ?? selectedProject?.name ?? null,
    playlistId: selectedPlaylist?.id ?? null,
    versions,
  });

  useEffect(() => {
    if (versions.length > 0 && !selectedVersion) {
      const inReviewVersionId = playlistMetadata?.in_review;
      const inReviewVersion = inReviewVersionId
        ? versions.find((v) => v.id === inReviewVersionId)
        : null;

      if (inReviewVersion) {
        setSelectedVersion(inReviewVersion);
      } else {
        setSelectedVersion(versions[0]);
      }
    }
  }, [versions, selectedVersion, playlistMetadata]);

  const playlistTitle = playlistLabel(selectedPlaylist);

  // The tab title too, not just the sidebar: reviewers keep several playlists open at once, and a
  // row of tabs all reading "DNA App" is the same "which one is this?" problem one level up.
  useEffect(() => {
    document.title = playlistTitle ? `${playlistTitle} · DNA` : 'DNA';
  }, [playlistTitle]);

  const handleRefresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['allDraftNotes'] });
    await queryClient.invalidateQueries({ queryKey: ['draftNote'] });

    const result = await refetch();
    if (result.data && selectedVersion) {
      const updatedVersion = result.data.find(
        (v) => v.id === selectedVersion.id
      );
      if (updatedVersion) {
        setSelectedVersion(updatedVersion);
      }
    }
  };

  const handleSelectionComplete = (
    project: Project,
    playlist: Playlist,
    email: string
  ) => {
    setSelectedProject(project);
    setSelectedPlaylist(playlist);
    setUserEmail(email);
  };

  const handleReplacePlaylist = () => {
    setSelectedPlaylist(null);
    setSelectedVersion(null);
  };

  // Switching straight from the sidebar, without a trip back through the picker. The version has
  // to go with it: it belongs to the playlist being left, and holding on to it would leave the
  // content area showing a shot the new playlist does not contain.
  const handlePlaylistSelect = (playlist: Playlist) => {
    setSelectedPlaylist(playlist);
    setSelectedVersion(null);
  };

  const handleLogout = () => {
    signOut();
    setSelectedProject(null);
    setSelectedPlaylist(null);
    setUserEmail(null);
    setSelectedVersion(null);
  };

  const handleVersionSelect = (version: Version) => {
    setSelectedVersion(version);
  };

  if (!selectedProject || !selectedPlaylist || !userEmail) {
    return <ProjectSelector onSelectionComplete={handleSelectionComplete} />;
  }

  return (
    <Layout
      onReplacePlaylist={handleReplacePlaylist}
      onPlaylistSelect={handlePlaylistSelect}
      projectId={selectedProject.id}
      playlistId={selectedPlaylist.id}
      playlistTitle={playlistTitle}
      selectedVersionId={selectedVersion?.id}
      followedVersionId={followedVersion?.id ?? null}
      onVersionSelect={handleVersionSelect}
      userEmail={userEmail}
      onLogout={handleLogout}
    >
      <ContentArea
        version={selectedVersion}
        versions={versions}
        playlistId={selectedPlaylist.id}
        userEmail={userEmail}
        onVersionSelect={handleVersionSelect}
        onRefresh={handleRefresh}
      />
    </Layout>
  );
}

export default App;
