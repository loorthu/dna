import { useCallback } from 'react';
import styled from 'styled-components';
import * as Tabs from '@radix-ui/react-tabs';
import { AssistantNote } from './AssistantNote';
import { OtherNotesPanel } from './OtherNotesPanel';
import { TranscriptPanel } from './TranscriptPanel';
import { PromptDebugPanel } from './PromptDebugPanel';
import { VirtualCutPlayer } from './VirtualCutPlayer';
import {
  useAISuggestion,
  usePlaylistMetadata,
  useRecordingCuts,
} from '../hooks';
import { useHotkeyAction } from '../hotkeys';
import { useFeatureFlags } from '../contexts';

const isDevMode = import.meta.env.VITE_DEV_MODE === 'true';
// To re-enable the Other Pending Notes tab, set this to true
const SHOW_OTHER_NOTES_TAB = false;

interface AssistantPanelProps {
  activeTab?: string;
  playlistId?: number | null;
  versionId?: number | null;
  userEmail?: string | null;
  onInsertNote?: (content: string) => void;
}

const PanelWrapper = styled.div`
  display: flex;
  flex-direction: column;
`;

const StyledTabsRoot = styled(Tabs.Root)`
  display: flex;
  flex-direction: column;
`;

const StyledTabsList = styled(Tabs.List)`
  display: flex;
  align-items: center;
  gap: 0;
  border-bottom: 1px solid ${({ theme }) => theme.colors.border.subtle};
`;

const StyledTabsTrigger = styled(Tabs.Trigger)`
  padding: 12px 16px;
  font-size: 14px;
  font-weight: 500;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.muted};
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.fast};

  &:hover {
    color: ${({ theme }) => theme.colors.text.secondary};
  }

  &[data-state='active'] {
    color: ${({ theme }) => theme.colors.text.primary};
    border-bottom-color: ${({ theme }) => theme.colors.text.primary};
  }
`;

const StyledTabsContent = styled(Tabs.Content)`
  padding: 16px 0;
`;

export function AssistantPanel({
  playlistId,
  versionId,
  userEmail,
  onInsertNote,
}: AssistantPanelProps) {
  const { transcriptionEnabled, aiEnabled, recordingPlaybackEnabled } =
    useFeatureFlags();
  // Which meeting the playlist is on. The panel usually mounts before the bot is dispatched, so
  // the first recording answer describes a meeting that has not happened; naming the meeting in
  // the query key is what makes the answer follow the dispatch instead of outliving it.
  const { data: playlistMetadata } = usePlaylistMetadata(playlistId ?? null);

  // Fetched only when the tab exists: with playback off this is disabled and never asks.
  const recordingCuts = useRecordingCuts(
    recordingPlaybackEnabled ? (playlistId ?? null) : null,
    playlistMetadata?.vexa_meeting_id ?? null
  );

  const { suggestion, prompt, context, isLoading, error, regenerate } =
    useAISuggestion({
      playlistId: playlistId ?? null,
      versionId: versionId ?? null,
      userEmail: userEmail ?? null,
    });

  const handleAiInsert = useCallback(() => {
    if (suggestion) {
      onInsertNote?.(suggestion);
    }
  }, [suggestion, onInsertNote]);

  const handleAiRegenerate = useCallback(() => {
    regenerate();
  }, [regenerate]);

  useHotkeyAction('aiInsert', handleAiInsert, { enabled: !!suggestion });
  useHotkeyAction('aiRegenerate', handleAiRegenerate, {
    enabled: !isLoading,
  });

  if (!transcriptionEnabled && !aiEnabled && !recordingPlaybackEnabled) {
    return null;
  }

  // The first tab that is actually rendered. Naming a tab that is switched off leaves Radix with
  // no selected content — an empty panel with visible triggers — which was reachable before by
  // turning AI off, and is easier to reach now there are three optional tabs.
  const defaultTab = aiEnabled
    ? 'assistant'
    : transcriptionEnabled
      ? 'transcript'
      : 'recording';

  return (
    <PanelWrapper>
      <StyledTabsRoot defaultValue={defaultTab}>
        <StyledTabsList>
          {aiEnabled && (
            <StyledTabsTrigger value="assistant">
              AI Assistant
            </StyledTabsTrigger>
          )}
          {transcriptionEnabled && (
            <StyledTabsTrigger value="transcript">Transcript</StyledTabsTrigger>
          )}
          {recordingPlaybackEnabled && (
            <StyledTabsTrigger value="recording">Recording</StyledTabsTrigger>
          )}
          {SHOW_OTHER_NOTES_TAB && (
            <StyledTabsTrigger value="other">
              Other Pending Notes
            </StyledTabsTrigger>
          )}
          {isDevMode && (
            <StyledTabsTrigger value="debug">Prompt Debug</StyledTabsTrigger>
          )}
        </StyledTabsList>

        {aiEnabled && (
          <StyledTabsContent value="assistant">
            <AssistantNote
              suggestion={suggestion}
              isLoading={isLoading}
              error={error}
              onRegenerate={regenerate}
              onInsertNote={onInsertNote}
            />
          </StyledTabsContent>
        )}

        {transcriptionEnabled && (
          <StyledTabsContent value="transcript">
            <TranscriptPanel
              playlistId={playlistId ?? null}
              versionId={versionId ?? null}
            />
          </StyledTabsContent>
        )}

        {recordingPlaybackEnabled && (
          <StyledTabsContent value="recording">
            <VirtualCutPlayer
              data={recordingCuts.data}
              isLoading={recordingCuts.isLoading}
              error={recordingCuts.error}
              versionId={versionId ?? null}
            />
          </StyledTabsContent>
        )}

        {SHOW_OTHER_NOTES_TAB && (
          <StyledTabsContent value="other">
            <OtherNotesPanel
              playlistId={playlistId}
              versionId={versionId}
              userEmail={userEmail}
              onInsertNote={onInsertNote}
            />
          </StyledTabsContent>
        )}

        {isDevMode && (
          <StyledTabsContent value="debug">
            <PromptDebugPanel prompt={prompt} context={context} />
          </StyledTabsContent>
        )}
      </StyledTabsRoot>
    </PanelWrapper>
  );
}
