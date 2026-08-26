/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from 'react';

const TRANSCRIPTION_KEY = 'dna-transcription-enabled';
const AI_KEY = 'dna-ai-enabled';
const IN_REVIEW_KEY = 'dna-in-review-enabled';
const FOLLOW_ALONG_KEY = 'dna-follow-along-enabled';
const RECORDING_PLAYBACK_KEY = 'dna-recording-playback-enabled';

function readEnvOverride(envValue: string | undefined): boolean | null {
  if (envValue === 'true') return true;
  if (envValue === 'false') return false;
  return null;
}

const ENV_TRANSCRIPTION = readEnvOverride(
  import.meta.env.VITE_FEATURE_TRANSCRIPTION
);
const ENV_IN_REVIEW = readEnvOverride(import.meta.env.VITE_FEATURE_IN_REVIEW);
const ENV_AI = readEnvOverride(import.meta.env.VITE_FEATURE_AI);
const ENV_FOLLOW_ALONG = readEnvOverride(
  import.meta.env.VITE_FEATURE_FOLLOW_ALONG
);
const ENV_RECORDING_PLAYBACK = readEnvOverride(
  import.meta.env.VITE_FEATURE_RECORDING_PLAYBACK
);

interface FeatureFlagsContextValue {
  transcriptionEnabled: boolean;
  recordingPlaybackEnabled: boolean;
  recordingPlaybackLocked: boolean;
  recordingPlaybackLockReason: string | null;
  setRecordingPlaybackEnabled: (enabled: boolean) => void;
  aiEnabled: boolean;
  inReviewEnabled: boolean;
  followAlongEnabled: boolean;
  transcriptionLocked: boolean;
  aiLocked: boolean;
  inReviewLocked: boolean;
  followAlongLocked: boolean;
  transcriptionLockReason: string | null;
  inReviewLockReason: string | null;
  setTranscriptionEnabled: (enabled: boolean) => void;
  setAiEnabled: (enabled: boolean) => void;
  setInReviewEnabled: (enabled: boolean) => void;
  setFollowAlongEnabled: (enabled: boolean) => void;
}

const FeatureFlagsContext = createContext<FeatureFlagsContextValue | null>(
  null
);

export function FeatureFlagsProvider({ children }: { children: ReactNode }) {
  const [transcriptionBase, setTranscriptionState] = useState(() => {
    if (ENV_TRANSCRIPTION !== null) return ENV_TRANSCRIPTION;
    const stored = localStorage.getItem(TRANSCRIPTION_KEY);
    return stored === null ? true : stored === 'true';
  });

  const [aiEnabled, setAiState] = useState(() => {
    if (ENV_AI !== null) return ENV_AI;
    const stored = localStorage.getItem(AI_KEY);
    return stored === null ? true : stored === 'true';
  });

  const [inReviewBase, setInReviewState] = useState(() => {
    if (ENV_IN_REVIEW !== null) return ENV_IN_REVIEW;
    const stored = localStorage.getItem(IN_REVIEW_KEY);
    return stored === null ? true : stored === 'true';
  });

  // Recording playback: OFF by default, unlike the rest. It shows a video of the meeting, which
  // is a bigger thing to turn on by accident than a transcript pane, and it is useless without a
  // deployment that records and collects.
  const [recordingPlaybackBase, setRecordingPlaybackState] = useState(() => {
    if (ENV_RECORDING_PLAYBACK !== null) return ENV_RECORDING_PLAYBACK;
    const stored = localStorage.getItem(RECORDING_PLAYBACK_KEY);
    return stored === null ? false : stored === 'true';
  });

  // Follow Along stands apart from the russian-doll chain below: it moves only
  // the local selection and needs nothing from the transcription pipeline.
  const [followAlongEnabled, setFollowAlongState] = useState(() => {
    if (ENV_FOLLOW_ALONG !== null) return ENV_FOLLOW_ALONG;
    const stored = localStorage.getItem(FOLLOW_ALONG_KEY);
    return stored === null ? true : stored === 'true';
  });

  // Russian-doll dependency: AI ⊆ Transcription ⊆ In Review.
  // AI requires Transcription, and Transcription requires In Review, so
  // enabling a parent (via UI toggle or env override) forces its children on.
  const transcriptionEnabled = transcriptionBase || aiEnabled;
  const inReviewEnabled = inReviewBase || transcriptionEnabled;

  // Playback DEPENDS on transcription rather than forcing it, so this chains with && where the
  // others use ||. The cut list is built from stored segments: with transcription off there are
  // none, and the tab could only ever say "nothing was said against this version" — which reads
  // as a broken feature rather than a disabled one. Turning transcription on does NOT turn
  // playback on; a video of the room is opt-in.
  const recordingPlaybackEnabled =
    recordingPlaybackBase && transcriptionEnabled;

  const setTranscriptionEnabled = useCallback((enabled: boolean) => {
    if (ENV_TRANSCRIPTION !== null) return;
    localStorage.setItem(TRANSCRIPTION_KEY, String(enabled));
    setTranscriptionState(enabled);
  }, []);

  const setAiEnabled = useCallback((enabled: boolean) => {
    if (ENV_AI !== null) return;
    localStorage.setItem(AI_KEY, String(enabled));
    setAiState(enabled);
  }, []);

  const setInReviewEnabled = useCallback((enabled: boolean) => {
    if (ENV_IN_REVIEW !== null) return;
    localStorage.setItem(IN_REVIEW_KEY, String(enabled));
    setInReviewState(enabled);
  }, []);

  const setRecordingPlaybackEnabled = useCallback((enabled: boolean) => {
    if (ENV_RECORDING_PLAYBACK !== null) return;
    localStorage.setItem(RECORDING_PLAYBACK_KEY, String(enabled));
    setRecordingPlaybackState(enabled);
  }, []);

  const setFollowAlongEnabled = useCallback((enabled: boolean) => {
    if (ENV_FOLLOW_ALONG !== null) return;
    localStorage.setItem(FOLLOW_ALONG_KEY, String(enabled));
    setFollowAlongState(enabled);
  }, []);

  return (
    <FeatureFlagsContext.Provider
      value={{
        transcriptionEnabled,
        aiEnabled,
        inReviewEnabled,
        followAlongEnabled,
        recordingPlaybackEnabled,
        recordingPlaybackLocked:
          ENV_RECORDING_PLAYBACK !== null || !transcriptionEnabled,
        recordingPlaybackLockReason:
          ENV_RECORDING_PLAYBACK !== null
            ? 'pipeline'
            : !transcriptionEnabled
              ? 'transcription'
              : null,
        setRecordingPlaybackEnabled,
        transcriptionLocked: ENV_TRANSCRIPTION !== null || aiEnabled,
        aiLocked: ENV_AI !== null,
        inReviewLocked: ENV_IN_REVIEW !== null || transcriptionEnabled,
        followAlongLocked: ENV_FOLLOW_ALONG !== null,
        transcriptionLockReason:
          ENV_TRANSCRIPTION !== null ? 'pipeline' : aiEnabled ? 'ai' : null,
        inReviewLockReason:
          ENV_IN_REVIEW !== null
            ? 'pipeline'
            : transcriptionEnabled
              ? 'transcription'
              : null,
        setTranscriptionEnabled,
        setAiEnabled,
        setInReviewEnabled,
        setFollowAlongEnabled,
      }}
    >
      {children}
    </FeatureFlagsContext.Provider>
  );
}

export function useFeatureFlags() {
  const ctx = useContext(FeatureFlagsContext);
  if (!ctx)
    throw new Error('useFeatureFlags must be used within FeatureFlagsProvider');
  return ctx;
}
