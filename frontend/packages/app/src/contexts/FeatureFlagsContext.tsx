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

// Deployment-config only: no localStorage, no Settings toggle, default off.
// Each fronts something whose backend half is not wired up at every site, so a
// user must not be able to switch them on and get silent failures.
//
//  - Note QC is an LLM pass over every draft when the Publish dialog opens.
//    Sites that have not opted in should never pay for it or see its UI.
//  - Transcript publish needs DNA_ENABLE_TRANSCRIPT_PUBLISH plus a provisioned
//    ShotGrid custom entity; without both, the endpoint 404s. Keep this in step
//    with the backend flag.
//  - Note links reach ShotGrid only on a note's FIRST publish; `update_note`
//    never re-sends them, so links added later go nowhere. Off until that
//    round trip is complete.
//  - Note subject is written by ShotGrid, not by a reviewer: every note on the
//    site carries a tool-generated subject, and a playlist note's is the
//    playlist name frozen at seeding time. Editing it here would produce the
//    only hand-typed subject on the site. Off; publish still echoes the
//    mirrored value back unchanged, which is what preserves that record.
const ENV_NOTE_QC = readEnvOverride(import.meta.env.VITE_FEATURE_NOTE_QC);
const ENV_TRANSCRIPT_PUBLISH = readEnvOverride(
  import.meta.env.VITE_FEATURE_TRANSCRIPT_PUBLISH
);
const ENV_NOTE_LINKS = readEnvOverride(import.meta.env.VITE_FEATURE_NOTE_LINKS);
const ENV_NOTE_SUBJECT = readEnvOverride(
  import.meta.env.VITE_FEATURE_NOTE_SUBJECT
);

interface FeatureFlagsContextValue {
  transcriptionEnabled: boolean;
  aiEnabled: boolean;
  inReviewEnabled: boolean;
  followAlongEnabled: boolean;
  noteQcEnabled: boolean;
  transcriptPublishEnabled: boolean;
  noteLinksEnabled: boolean;
  noteSubjectEnabled: boolean;
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
        // AI note generation stays available with QC off — they are separate
        // features that happened to share a switch.
        noteQcEnabled: (ENV_NOTE_QC ?? false) && aiEnabled,
        transcriptPublishEnabled: ENV_TRANSCRIPT_PUBLISH ?? false,
        noteLinksEnabled: ENV_NOTE_LINKS ?? false,
        noteSubjectEnabled: ENV_NOTE_SUBJECT ?? false,
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
