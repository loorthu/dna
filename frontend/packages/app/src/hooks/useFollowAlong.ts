import { useEffect, useMemo, useRef } from 'react';
import { findByExternalRef, type ReviewFocus, type Version } from '@dna/core';
import { useFollowAlongContext } from '../contexts/FollowAlongContext';
import { useToast } from '../contexts';

export interface UseFollowAlongOptions {
  /** Show code the review player announces sessions under. */
  show: string | null;
  playlistId: number | null;
  versions: Version[];
}

export interface UseFollowAlongResult {
  enabled: boolean;
  connected: boolean;
  session: string | null;
  focus: ReviewFocus | null;
  followedVersion: Version | null;
  isOffPlaylist: boolean;
}

/**
 * Resolves the followed session's current clip onto a loaded version.
 *
 * Matching happens against the versions already in memory, so changing clip
 * costs no requests. Call this once, from the component that owns the
 * selection; everything else reads `useFollowAlongContext`.
 */
export function useFollowAlong({
  show,
  playlistId,
  versions,
}: UseFollowAlongOptions): UseFollowAlongResult {
  const { available, connected, session, focus, setShow, setPlaylistId } =
    useFollowAlongContext();
  const { showToast } = useToast();

  useEffect(() => {
    setShow(show);
  }, [show, setShow]);

  useEffect(() => {
    setPlaylistId(playlistId);
  }, [playlistId, setPlaylistId]);

  const followedVersion = useMemo(() => {
    if (!available || !focus) {
      return null;
    }
    return findByExternalRef(versions, focus.externalRef);
  }, [available, focus, versions]);

  const isOffPlaylist = available && !!focus && !followedVersion;

  // The player republishes the current clip continuously, so warn once per
  // clip rather than once per message.
  const warnedRefs = useRef<Set<string>>(new Set());

  useEffect(() => {
    warnedRefs.current.clear();
  }, [playlistId, session]);

  useEffect(() => {
    if (!isOffPlaylist || !focus) {
      return;
    }
    if (warnedRefs.current.has(focus.externalRef)) {
      return;
    }
    warnedRefs.current.add(focus.externalRef);

    showToast({
      type: 'warning',
      title: 'Review moved off this playlist',
      description: focus.shot
        ? `${focus.shot} is on screen but is not in this playlist.`
        : 'The current clip is not in this playlist.',
    });
  }, [isOffPlaylist, focus, showToast]);

  return {
    enabled: available && !!session,
    connected,
    session,
    focus,
    followedVersion,
    isOffPlaylist,
  };
}
