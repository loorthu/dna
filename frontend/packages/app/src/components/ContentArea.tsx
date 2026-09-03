import { useRef, useCallback, useMemo, useEffect, useState } from 'react';
import styled from 'styled-components';
import { useQuery } from '@tanstack/react-query';
import type { Version, SearchResult, UserSettings } from '@dna/core';
import { VersionHeader } from './VersionHeader';
import { NoteEditor, type NoteEditorHandle } from './NoteEditor';
import { AssistantPanel } from './AssistantPanel';
import {
  usePlaylistMetadata,
  useSetInReview,
  useDraftNote,
  useBotSession,
  isBotSessionLive,
} from '../hooks';
import { useHotkeyAction } from '../hotkeys';
import { apiHandler } from '../api';
import { useFeatureFlags } from '../contexts';
// Imported from their own modules rather than the review barrel: that barrel pulls in ReviewPage,
// which reaches back into this components barrel, and the cycle resolves to undefined at module
// init rather than to an error anyone could read.
import { useReviewLink } from '../review/useReviewLink';
import { reviewShotHref } from '../review/reviewLink';
import {
  openProdtrackVersionViaExtensionOrNewTab,
  openProdtrackVersionInExtension,
} from '../prodtrackTabSync/sendProdtrackTabSync';

interface ContentAreaProps {
  version?: Version | null;
  versions?: Version[];
  playlistId?: number | null;
  userEmail?: string | null;
  onVersionSelect?: (version: Version) => void;
  onRefresh?: () => void;
}

const ContentWrapper = styled.div`
  display: flex;
  flex-direction: column;
  gap: 24px;
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  padding-right: 32px;
`;

const EmptyState = styled.div`
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 64px 32px;
  text-align: center;
  color: ${({ theme }) => theme.colors.text.muted};
`;

const EmptyStateTitle = styled.h2`
  margin: 0 0 8px 0;
  font-size: 20px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.text.secondary};
`;

const EmptyStateText = styled.p`
  margin: 0;
  font-size: 14px;
`;

function formatDate(dateString?: string): string {
  if (!dateString) return '';
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

const IN_REVIEW_STATUS = 'rev';

/**
 * How long someone gets to move to a shot and mark it In Review themselves before the button
 * starts pulsing at them. Long enough that the ordinary "click the shot, click the button"
 * motion never sees the warning; short enough that anyone who got distracted still does.
 */
const IN_REVIEW_REMINDER_DELAY_MS = 3000;

export function ContentArea({
  version,
  versions = [],
  playlistId,
  userEmail,
  onVersionSelect,
  onRefresh,
}: ContentAreaProps) {
  const noteEditorRef = useRef<NoteEditorHandle>(null);
  const { transcriptionEnabled, aiEnabled } = useFeatureFlags();
  const assistantPanelVisible = transcriptionEnabled || aiEnabled;

  const currentVersionAsSearchResult = useMemo((): SearchResult | undefined => {
    if (!version) return undefined;
    return {
      type: 'Version',
      id: version.id,
      name: version.name || `Version ${version.id}`,
    };
  }, [version]);

  const versionSubmitter = useMemo((): SearchResult | undefined => {
    if (!version?.user) return undefined;
    return { type: 'User', id: version.user.id, name: version.user.name || '' };
  }, [version?.user]);

  const { draftNote, updateDraftNote, saveAttachmentIds } = useDraftNote({
    playlistId,
    versionId: version?.id,
    userEmail,
    currentVersion: currentVersionAsSearchResult,
    submitter: versionSubmitter,
  });

  const selectedVersionStatus =
    draftNote?.versionStatus || (version?.status ?? '');

  const handleVersionStatusChange = useCallback(
    (code: string) => {
      updateDraftNote({ versionStatus: code });
    },
    [updateDraftNote]
  );

  const handleRefreshClick = useCallback(() => {
    updateDraftNote({ versionStatus: version?.status ?? '' });
    onRefresh?.();
  }, [version?.status, onRefresh, updateDraftNote]);

  const currentIndex = version
    ? versions.findIndex((v) => v.id === version.id)
    : -1;
  const canGoBack = currentIndex > 0;
  const canGoNext = currentIndex >= 0 && currentIndex < versions.length - 1;

  const { data: playlistMetadata } = usePlaylistMetadata(playlistId ?? null);
  const { setInReview, isLoading: isSettingInReview } = useSetInReview(
    playlistId ?? null
  );

  const inReviewVersionId = playlistMetadata?.in_review;
  const inReviewVersion = inReviewVersionId
    ? versions.find((v) => v.id === inReviewVersionId)
    : versions.find((v) => v.status === IN_REVIEW_STATUS);
  const hasInReview = !!inReviewVersion;
  const isCurrentVersionInReview =
    version && inReviewVersionId ? version.id === inReviewVersionId : false;

  // Segments are filed against `in_review` and nothing else — a version merely sitting at the
  // "rev" status does not save them, so this deliberately ignores the fallback above. While a bot
  // is live with none set, everything it transcribes is discarded on arrival.
  const botSession = useBotSession(playlistId ?? null);
  const botLive = isBotSessionLive(botSession);
  const isDiscardingSegments = botLive && (inReviewVersionId ?? null) === null;

  // Segments are still being kept, just against a version nobody is looking at any more. That is
  // the shot switch someone forgot to follow through on, and it stays invisible until said.
  const transcriptElsewhere =
    botLive &&
    !!inReviewVersionId &&
    !!version &&
    version.id !== inReviewVersionId;
  const [remindTranscriptElsewhere, setRemindTranscriptElsewhere] =
    useState(false);
  useEffect(() => {
    setRemindTranscriptElsewhere(false);
    if (!transcriptElsewhere) return;
    const timer = setTimeout(
      () => setRemindTranscriptElsewhere(true),
      IN_REVIEW_REMINDER_DELAY_MS
    );
    return () => clearTimeout(timer);
    // The version and the in-review target are named so that moving between two versions that
    // are both "elsewhere" restarts the grace period rather than nagging instantly.
  }, [transcriptElsewhere, version?.id, inReviewVersionId]);

  const transcriptTargetLabel =
    inReviewVersion?.entity?.name || inReviewVersion?.name || undefined;

  const handleBack = useCallback(() => {
    if (canGoBack && onVersionSelect) {
      onVersionSelect(versions[currentIndex - 1]);
    }
  }, [canGoBack, onVersionSelect, versions, currentIndex]);

  const handleNext = useCallback(() => {
    if (canGoNext && onVersionSelect) {
      onVersionSelect(versions[currentIndex + 1]);
    }
  }, [canGoNext, onVersionSelect, versions, currentIndex]);

  const handleInReview = () => {
    if (inReviewVersion && onVersionSelect) {
      onVersionSelect(inReviewVersion);
    }
  };

  const handleSetInReview = async () => {
    if (version && playlistId) {
      await setInReview(version.id);
    }
  };

  const handleInsertNote = useCallback((content: string) => {
    noteEditorRef.current?.appendContent(content);
  }, []);

  useHotkeyAction('nextVersion', handleNext);
  useHotkeyAction('previousVersion', handleBack);
  useHotkeyAction('setInReview', handleSetInReview, {
    enabled: !!version && !!playlistId,
  });

  const extensionId =
    import.meta.env.VITE_PRODTRACK_TAB_SYNC_EXTENSION_ID?.trim() ?? '';

  const [prodtrackControlledTabId, setProdtrackControlledTabId] = useState<
    number | null
  >(null);
  const prodtrackTabIdRef = useRef<number | null>(null);
  prodtrackTabIdRef.current = prodtrackControlledTabId;

  const { data: userSettings, isSuccess: userSettingsQuerySuccess } =
    useQuery<UserSettings | null>({
      queryKey: ['userSettings', userEmail],
      queryFn: () => apiHandler.getUserSettings({ userEmail: userEmail! }),
      enabled: !!userEmail,
    });

  const shouldAutoSyncProdtrackTab =
    userSettingsQuerySuccess &&
    (userSettings === null ||
      (userSettings.sync_prodtrack_tab_on_version_change ?? true) === true);

  const prodtrackPageType = userSettings?.prodtrack_page_type ?? 'version';
  const activeProdtrackUrl =
    prodtrackPageType === 'entity'
      ? (version?.prodtrack_entity_detail_url ?? version?.prodtrack_detail_url)
      : version?.prodtrack_detail_url;

  const handleSyncProdtrackTab = useCallback(() => {
    const url = activeProdtrackUrl;
    if (!url || !extensionId) return;
    void openProdtrackVersionViaExtensionOrNewTab(extensionId, url, {
      tabId: prodtrackControlledTabId ?? undefined,
    }).then((result) => {
      if (result.ok && typeof result.tabId === 'number') {
        setProdtrackControlledTabId(result.tabId);
      }
    });
  }, [activeProdtrackUrl, extensionId, prodtrackControlledTabId]);

  // Tracks the version id we last reacted to, so we only sync on an actual
  // version change (not on settings/url/mount re-renders for the same version).
  const lastProdtrackVersionIdRef = useRef<number | null>(null);

  useEffect(() => {
    const currentVersionId = version?.id ?? null;
    if (currentVersionId == null) return;

    const previousVersionId = lastProdtrackVersionIdRef.current;
    lastProdtrackVersionIdRef.current = currentVersionId;
    if (currentVersionId === previousVersionId) return;

    // Only sync into a PT tab the user already opened with the "PT tab" button.
    // We never open the tab automatically — not on launch, not on version change.
    const controlledTabId = prodtrackTabIdRef.current;
    if (controlledTabId == null) return;

    if (!activeProdtrackUrl) return;
    if (!shouldAutoSyncProdtrackTab) return;
    if (!extensionId) return;
    const url = activeProdtrackUrl;
    const timer = window.setTimeout(() => {
      // Extension-only (no new-tab fallback): if the controlled tab was closed,
      // a failed sync must not spawn a window on its own.
      void openProdtrackVersionInExtension(extensionId, url, {
        tabId: controlledTabId,
      }).then((result) => {
        if (result.ok && typeof result.tabId === 'number') {
          setProdtrackControlledTabId(result.tabId);
        }
      });
    }, 120);
    return () => window.clearTimeout(timer);
  }, [
    version?.id,
    activeProdtrackUrl,
    shouldAutoSyncProdtrackTab,
    extensionId,
  ]);

  const syncProdtrackTitle = !activeProdtrackUrl
    ? 'Production tracking URL is not available for this version.'
    : extensionId
      ? 'Open in the tab sync extension when available; otherwise opens in a new tab.'
      : 'Open production tracking in a new browser tab.';

  const syncProdtrackDisabled = !activeProdtrackUrl;

  // The same shot on the artist-facing page. Asked for per playlist rather than composed here:
  // the anchor is a slug of the version's name, and the page and the notes email derive theirs
  // from the same backend rule.
  const { data: reviewLink } = useReviewLink(playlistId);
  const reviewUrl = reviewShotHref(reviewLink, version?.id);

  if (!version) {
    return (
      <ContentWrapper>
        <EmptyState>
          <EmptyStateTitle>No version selected</EmptyStateTitle>
          <EmptyStateText>
            Select a version from the sidebar to view its details
          </EmptyStateText>
        </EmptyState>
      </ContentWrapper>
    );
  }

  const entityName = version.entity?.name || '';
  const versionNumber =
    version.name?.replace(entityName, '').replace(/^[\s\-_]+/, '') ||
    version.name ||
    '';
  const links: string[] = [];
  if (version.task?.pipeline_step?.name) {
    links.push(version.task.pipeline_step.name);
  }
  if (version.entity?.name) {
    links.push(version.entity.name);
  }

  return (
    <>
      <ContentWrapper>
        <VersionHeader
          shotCode={entityName}
          versionNumber={versionNumber}
          submittedBy={version.user?.name}
          dateSubmitted={formatDate(version.created_at as string)}
          versionStatus={selectedVersionStatus}
          projectId={version.project?.id}
          thumbnailUrl={version.thumbnail}
          links={links}
          onBack={handleBack}
          onNext={handleNext}
          onInReview={handleInReview}
          onSetInReview={handleSetInReview}
          onVersionStatusChange={handleVersionStatusChange}
          prodtrackDetailUrl={activeProdtrackUrl}
          prodtrackTabUsesExtension={!!extensionId}
          onSyncProdtrackTab={extensionId ? handleSyncProdtrackTab : undefined}
          syncProdtrackDisabled={syncProdtrackDisabled}
          syncProdtrackTitle={syncProdtrackTitle}
          reviewUrl={reviewUrl}
          canGoBack={canGoBack}
          canGoNext={canGoNext}
          hasInReview={hasInReview}
          isCurrentVersionInReview={isCurrentVersionInReview}
          isSettingInReview={isSettingInReview}
          isDiscardingSegments={isDiscardingSegments}
          isTranscriptElsewhere={remindTranscriptElsewhere}
          transcriptTargetLabel={transcriptTargetLabel}
          onRefresh={handleRefreshClick}
        />
        <NoteEditor
          ref={noteEditorRef}
          projectId={version.project?.id}
          currentVersion={version}
          draftNote={draftNote}
          updateDraftNote={updateDraftNote}
          saveAttachmentIds={saveAttachmentIds}
          defaultHeight={assistantPanelVisible ? undefined : 300}
        />
        <AssistantPanel
          playlistId={playlistId}
          versionId={version.id}
          userEmail={userEmail}
          onInsertNote={handleInsertNote}
        />
      </ContentWrapper>
    </>
  );
}
