import { useState, useCallback } from 'react';
import styled, { keyframes, useTheme } from 'styled-components';
import {
  Phone,
  PhoneOff,
  Loader2,
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Circle,
  Radio,
  Pause,
  Play,
} from 'lucide-react';
import { Button, TextField, Popover, Text } from '@radix-ui/themes';
import type { BotStatusEnum } from '@dna/core';
import {
  useTranscription,
  parseMeetingUrl,
  usePlaylistMetadata,
  useUpsertPlaylistMetadata,
} from '../hooks';
import { SplitButton } from './SplitButton';

interface TranscriptionMenuProps {
  playlistId: number | null;
  collapsed?: boolean;
}

/**
 * Whether "Record this meeting" starts ticked.
 *
 * A facility-level default, hardcoded until there is somewhere to configure it per facility or
 * per show. Kept as a named constant rather than inlined so that when that setting arrives, this
 * is the single place it feeds.
 */
const DEFAULT_RECORD_MEETING = true;

const pulse = keyframes`
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
`;

const MenuContainer = styled.div`
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 280px;
`;

const StatusRow = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: ${({ theme }) => theme.colors.bg.surface};
  border-radius: ${({ theme }) => theme.radii.md};
`;

const StatusIndicator = styled.div<{ $status: BotStatusEnum }>`
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: ${({ theme, $status }) => {
    switch ($status) {
      case 'joining':
      case 'waiting_room':
        return theme.colors.status.warning;
      case 'in_call':
      case 'transcribing':
        return theme.colors.status.success;
      case 'failed':
        return theme.colors.status.error;
      case 'stopped':
      case 'completed':
        return theme.colors.text.muted;
      default:
        return theme.colors.text.muted;
    }
  }};
  animation: ${({ $status }) =>
      $status === 'joining' ||
      $status === 'transcribing' ||
      $status === 'waiting_room'
        ? pulse
        : 'none'}
    1.5s ease-in-out infinite;
`;

const StatusText = styled.span`
  font-size: 13px;
  color: ${({ theme }) => theme.colors.text.secondary};
  flex: 1;
`;

const ErrorMessage = styled.div`
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: ${({ theme }) => theme.radii.md};
  font-size: 12px;
  color: ${({ theme }) => theme.colors.status.error};
`;

/* Not an error — the bot is working. It is the transcript that is going nowhere, which looks
   identical to a quiet meeting from the outside. Amber rather than red: nothing has failed, but
   it will not fix itself either. */
const WarningMessage = styled.div`
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 8px 12px;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.25);
  border-radius: ${({ theme }) => theme.radii.md};
  font-size: 12px;
  line-height: 1.4;
  color: ${({ theme }) => theme.colors.status.warning};

  svg {
    flex-shrink: 0;
    margin-top: 1px;
  }
`;

const InputGroup = styled.div`
  display: flex;
  flex-direction: column;
  gap: 8px;
`;

const RecordToggle = styled.label`
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  color: ${({ theme }) => theme.colors.text.secondary};
  cursor: pointer;

  input {
    margin-top: 2px;
    cursor: pointer;
  }
`;

const RecordHint = styled.span`
  display: block;
  font-size: 11px;
  color: ${({ theme }) => theme.colors.text.muted};
`;

/* Shown while a bot is live, from what Vexa RESOLVED rather than what was asked for. The
   checkbox is off by default and not remembered, so "I forgot to tick it" is the expected
   mistake — this makes it visible in seconds instead of at the end of the meeting. */
const RecordingBadge = styled.span<{ $on: boolean }>`
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: ${({ theme }) => theme.radii.sm};
  color: ${({ theme, $on }) =>
    $on ? theme.colors.status.error : theme.colors.text.muted};
  background: ${({ $on }) =>
    $on ? 'rgba(239, 68, 68, 0.12)' : 'transparent'};
  border: 1px solid
    ${({ theme, $on }) =>
      $on ? 'rgba(239, 68, 68, 0.3)' : theme.colors.border.default};
`;

const ButtonRow = styled.div`
  display: flex;
  gap: 8px;
`;

type PhoneStatus = 'disconnected' | 'connecting' | 'connected';

const TriggerButton = styled.button<{
  $isActive: boolean;
  $phoneStatus: PhoneStatus;
}>`
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 14px;
  height: 32px;
  font-size: 13px;
  font-weight: 500;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme, $isActive }) =>
    $isActive ? theme.colors.text.primary : theme.colors.text.secondary};
  background: transparent;
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.md};
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.fast};

  &:hover {
    background: ${({ theme }) => theme.colors.bg.surfaceHover};
    border-color: ${({ theme }) => theme.colors.border.strong};
  }

  svg.phone-icon {
    color: ${({ theme, $phoneStatus }) => {
      switch ($phoneStatus) {
        case 'connected':
          return theme.colors.status.success;
        case 'connecting':
          return theme.colors.status.warning;
        case 'disconnected':
        default:
          return theme.colors.status.error;
      }
    }};
  }
`;

const SpinnerIcon = styled(Loader2)`
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

const PulsingPhone = styled(Phone)<{ $shouldPulse: boolean }>`
  animation: ${({ $shouldPulse }) => ($shouldPulse ? pulse : 'none')} 1.5s
    ease-in-out infinite;
`;

const CollapsedTriggerButton = styled.button<{ $phoneStatus: PhoneStatus }>`
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  width: 48px;
  height: 48px;
  padding: 6px;
  font-size: 10px;
  font-weight: 500;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.secondary};
  background: transparent;
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.md};
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.fast};

  &:hover {
    background: ${({ theme }) => theme.colors.bg.surfaceHover};
    border-color: ${({ theme }) => theme.colors.border.strong};
  }

  svg.phone-icon {
    color: ${({ theme, $phoneStatus }) => {
      switch ($phoneStatus) {
        case 'connected':
          return theme.colors.status.success;
        case 'connecting':
          return theme.colors.status.warning;
        case 'disconnected':
        default:
          return theme.colors.status.error;
      }
    }};
  }
`;

function getStatusLabel(status: BotStatusEnum, isPaused: boolean): string {
  switch (status) {
    case 'idle':
      return 'Ready';
    case 'joining':
      return 'Joining...';
    case 'waiting_room':
      return 'Awaiting Admission';
    case 'in_call':
      return isPaused ? 'Paused' : 'In Call';
    case 'transcribing':
      return isPaused ? 'Paused' : 'Transcribing';
    case 'failed':
      return 'Failed';
    case 'stopped':
      return 'Stopped';
    case 'completed':
      return 'Completed';
    default:
      return 'Unknown';
  }
}

function getButtonStatusLabel(
  status: BotStatusEnum,
  isPaused: boolean
): string {
  switch (status) {
    case 'joining':
      return 'Joining...';
    case 'waiting_room':
      return 'Waiting';
    case 'in_call':
    case 'transcribing':
      return isPaused ? 'Paused' : 'Live';
    default:
      return '';
  }
}

function getPhoneStatus(status: BotStatusEnum): PhoneStatus {
  switch (status) {
    case 'in_call':
    case 'transcribing':
      return 'connected';
    case 'joining':
    case 'waiting_room':
      return 'connecting';
    case 'idle':
    case 'failed':
    case 'stopped':
    case 'completed':
    default:
      return 'disconnected';
  }
}

function getStatusIcon(status: BotStatusEnum) {
  switch (status) {
    case 'joining':
    case 'waiting_room':
      return <SpinnerIcon size={14} />;
    case 'in_call':
    case 'transcribing':
      return <Radio size={14} />;
    case 'failed':
      return <AlertCircle size={14} />;
    case 'completed':
      return <CheckCircle2 size={14} />;
    default:
      return null;
  }
}

export function TranscriptionMenu({
  playlistId,
  collapsed = false,
}: TranscriptionMenuProps) {
  const [meetingUrl, setMeetingUrl] = useState('');
  const [passcode, setPasscode] = useState('');
  // The facility default, as a constant for now. This is the seam a per-facility or per-show
  // setting plugs into later — the checkbox reads its initial state from here and nothing else,
  // so that change is one line plus wherever the value comes from.
  //
  // The API's own default stays FALSE deliberately: a caller that says nothing gets no
  // recording, and the UI always says something. That is what keeps the decision here rather
  // than in a default on the Vexa host.
  const [recordMeeting, setRecordMeeting] = useState(DEFAULT_RECORD_MEETING);
  const [isOpen, setIsOpen] = useState(false);
  const theme = useTheme();

  const {
    session,
    status,
    isDispatching,
    isStopping,
    error,
    dispatchBot,
    stopBot,
    clearSession,
  } = useTranscription({ playlistId });

  const { data: metadata } = usePlaylistMetadata(playlistId);
  const { mutate: upsertMetadata } = useUpsertPlaylistMetadata(playlistId);

  const currentStatus = status?.status ?? session?.status ?? 'idle';
  const isActive = [
    'joining',
    'waiting_room',
    'in_call',
    'transcribing',
  ].includes(currentStatus);
  const phoneStatus = getPhoneStatus(currentStatus);
  const needsPasscode = parseMeetingUrl(meetingUrl)?.platform === 'teams';
  const isPaused = metadata?.transcription_paused ?? false;

  // Segments are stored against the version in review. With none set the bot joins and Vexa
  // transcribes, and every segment is discarded on arrival — indistinguishable from a meeting
  // where nobody spoke, which is exactly how a whole meeting's transcript was lost.
  // What Vexa resolved, not what the checkbox said — a deployment that ignored the request must
  // not leave this badge claiming a recording is being made.
  const isRecording = session?.recording_enabled === true;
  const recordingTitle = isRecording
    ? 'This meeting is being recorded; the video is archived when it ends.'
    : 'Not recording — only the transcript is kept. Stop the bot and start it again with ' +
      '"Record this meeting" ticked if you need the video.';

  const hasVersionInReview = (metadata?.in_review ?? null) !== null;
  const isDiscardingSegments = isActive && !hasVersionInReview;
  // Nothing is said here BEFORE the bot is sent. The bot goes out while the meeting is still
  // small talk and nobody has picked a shot yet, so a warning at that moment is one the user is
  // right to ignore — and one they learn to ignore. The Set In Review button in the version
  // header carries it instead, from the moment the bot is live until a version is marked.

  const isLiveButPaused =
    isPaused && ['in_call', 'transcribing'].includes(currentStatus);
  const isAwaitingAdmission = currentStatus === 'waiting_room';
  // Carried on the trigger too, not just inside the popover: a warning nobody opens the menu to
  // see is no better than the silence it replaced.
  const shouldPulseYellow =
    isLiveButPaused || isAwaitingAdmission || isDiscardingSegments;

  const getPhoneIconColor = () => {
    if (shouldPulseYellow) {
      return theme.colors.status.warning;
    }
    switch (phoneStatus) {
      case 'connected':
        return theme.colors.status.success;
      case 'connecting':
        return theme.colors.status.warning;
      case 'disconnected':
      default:
        return theme.colors.status.error;
    }
  };

  const phoneIconColor = getPhoneIconColor();

  const handlePauseToggle = useCallback(() => {
    upsertMetadata({ transcription_paused: !isPaused });
  }, [upsertMetadata, isPaused]);

  const handleDispatch = useCallback(async () => {
    if (!meetingUrl.trim()) return;

    try {
      await dispatchBot(meetingUrl, passcode || undefined, recordMeeting);
      setMeetingUrl('');
      setPasscode('');
    } catch {
      // Error is handled by the hook
    }
  }, [meetingUrl, passcode, recordMeeting, dispatchBot]);

  const handleStop = useCallback(async () => {
    try {
      await stopBot();
    } catch {
      // Error is handled by the hook
    }
  }, [stopBot]);

  const handleOpenChange = (open: boolean) => {
    setIsOpen(open);
    if (!open && !isActive) {
      clearSession();
      setMeetingUrl('');
      setPasscode('');
    }
  };

  const renderMainButtonContent = () => {
    if (collapsed) {
      return <PulsingPhone size={18} color={phoneIconColor} $shouldPulse={shouldPulseYellow} />;
    }

    return (
      <>
        <PulsingPhone size={14} color={phoneIconColor} $shouldPulse={shouldPulseYellow} />
        {isActive ? (
          <>
            <StatusIndicator $status={currentStatus} />
            {getButtonStatusLabel(currentStatus, isPaused)}
          </>
        ) : (
          'Transcription'
        )}
      </>
    );
  };

  const renderTrigger = () => {
    if (isActive) {
      return (
        <SplitButton
          onRightClick={handlePauseToggle}
          rightSlot={isPaused ? <Play size={14} /> : <Pause size={14} />}
        >
          {renderMainButtonContent()}
        </SplitButton>
      );
    }

    if (collapsed) {
      return (
        <CollapsedTriggerButton $phoneStatus={phoneStatus}>
          <Phone size={18} className="phone-icon" />
        </CollapsedTriggerButton>
      );
    }

    return (
      <TriggerButton $isActive={isActive} $phoneStatus={phoneStatus}>
        <Phone size={14} className="phone-icon" />
        Transcription
      </TriggerButton>
    );
  };

  return (
    <Popover.Root open={isOpen} onOpenChange={handleOpenChange}>
      <Popover.Trigger asChild>
        <div style={{ display: 'inline-block' }}>{renderTrigger()}</div>
      </Popover.Trigger>
      <Popover.Content side="top" align="start" sideOffset={8}>
        <MenuContainer>
          <Text size="2" weight="medium">
            Meeting Transcription
          </Text>

          {session && (
            <StatusRow>
              <StatusIndicator $status={currentStatus} />
              {getStatusIcon(currentStatus)}
              <StatusText>{getStatusLabel(currentStatus, isPaused)}</StatusText>
              <RecordingBadge $on={isRecording} title={recordingTitle}>
                {isRecording ? (
                  <>
                    <Circle size={8} fill="currentColor" />
                    REC
                  </>
                ) : (
                  'no recording'
                )}
              </RecordingBadge>
            </StatusRow>
          )}

          {error && (
            <ErrorMessage>
              <AlertCircle size={14} />
              {error.message}
            </ErrorMessage>
          )}

          {isDiscardingSegments && (
            <WarningMessage>
              <AlertTriangle size={14} />
              <span>
                <strong>Transcript is not being saved.</strong> No version is
                marked In&nbsp;Review, so segments are discarded as they arrive.
                Mark a version In&nbsp;Review to start keeping them — speech from
                before that is not backfilled.
              </span>
            </WarningMessage>
          )}

          {!isActive && (
            <InputGroup>
              <TextField.Root
                placeholder="Paste meeting URL..."
                value={meetingUrl}
                onChange={(e) => setMeetingUrl(e.target.value)}
                disabled={isDispatching || !playlistId}
              />
              {needsPasscode && (
                <TextField.Root
                  placeholder="Passcode (if required)"
                  value={passcode}
                  onChange={(e) => setPasscode(e.target.value)}
                  disabled={isDispatching}
                />
              )}
              <RecordToggle>
                <input
                  type="checkbox"
                  checked={recordMeeting}
                  onChange={(e) => setRecordMeeting(e.target.checked)}
                  disabled={isDispatching || !playlistId}
                />
                <span>
                  Record this meeting
                  <RecordHint>
                    Keeps the video as well as the transcript. Untick to
                    transcribe only.
                  </RecordHint>
                </span>
              </RecordToggle>
            </InputGroup>
          )}

          <ButtonRow>
            {isActive ? (
              <Button
                color="red"
                variant="soft"
                onClick={handleStop}
                disabled={isStopping}
                style={{ flex: 1 }}
              >
                {isStopping ? (
                  <>
                    <SpinnerIcon size={14} />
                    Stopping...
                  </>
                ) : (
                  <>
                    <PhoneOff size={14} />
                    Stop Transcription
                  </>
                )}
              </Button>
            ) : (
              <Button
                variant="solid"
                onClick={handleDispatch}
                disabled={isDispatching || !meetingUrl.trim() || !playlistId}
                style={{ flex: 1 }}
              >
                {isDispatching ? (
                  <>
                    <SpinnerIcon size={14} />
                    Connecting...
                  </>
                ) : (
                  <>
                    <Phone size={14} />
                    Start Transcription
                  </>
                )}
              </Button>
            )}
          </ButtonRow>

          {!playlistId && (
            <Text size="1" color="gray">
              Select a playlist to enable transcription
            </Text>
          )}
        </MenuContainer>
      </Popover.Content>
    </Popover.Root>
  );
}
