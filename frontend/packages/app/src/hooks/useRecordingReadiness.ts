import { useQuery } from '@tanstack/react-query';
import type {
  BotStatus,
  BotStatusEnum,
  Platform,
  RecordingCutsStatus,
} from '@dna/core';
import { apiHandler } from '../api';
import { useCapabilities } from './useCapabilities';
import { usePlaylistMetadata } from './usePlaylistMetadata';
import { useRecordingCuts } from './useRecordingCuts';
import { useBotSession } from './useTranscription';

/**
 * Whether the meeting behind a playlist has finished landing — asked before notes go out.
 *
 * Three facts, because three different things can still be in motion when someone opens the Email
 * dialog, and none of them is visible anywhere else in the app:
 *
 *   bot_left   the bot is still in the call, so the transcript is still growing
 *   archived   the collector has not taken custody, so there is no file to link to yet
 *   served     the file exists but this network cannot fetch it, so the link would 404
 *
 * WHY THE LAST TWO ARE NOT THE SAME QUESTION. They are answered by different machines, on
 * different sides. DNA and Vexa run off the content network; the collector, the share and the
 * nginx that serves it do not. So DNA can only ever report what the collector TOLD it — and the
 * browser doing the publishing is on the content side, which makes it the one thing in the system
 * that can confirm the archive is reachable from where people will actually open the link.
 *
 * Neither check is redundant. The API record is not second-hand: `network_path` and `sha256` are
 * written only after the collector muxed the file, moved it to the share, READ IT BACK OFF THE
 * SHARE and re-hashed it — and the upstream copy is released only after that record exists. What
 * it cannot speak to is the serving path: a share mounted read-only into nginx, an alias pointing
 * at last year's directory, a file written under a uid nginx cannot read. Every one of those
 * leaves DNA reporting a verified archive and every emailed link returning 404.
 */

/** Bot statuses that mean it is still in, or on its way into, the meeting. */
const BOT_IN_MEETING: BotStatusEnum[] = [
  'joining',
  'waiting_room',
  'in_call',
  'transcribing',
];

/**
 * Cut-list statuses that can only be reached once the upload finished.
 *
 * Load-bearing beyond the archive check: reaching any of them proves the bot is gone, which is
 * how a stale bot session — a `bot.status_changed` frame that never arrived — is prevented from
 * holding the gate shut forever. Server truth about the recording outranks a cached status.
 */
const UPLOAD_COMPLETE: RecordingCutsStatus[] = [
  'archiving',
  // Reached only from `archiving`: the collector had the whole recording and then could not file
  // it. The bot is as gone as it is in any other state here, and leaving it out would hold the
  // bot row shut too — two rows waiting on one problem, neither of them naming it.
  'blocked',
  'ready',
  'no_segments',
];

export type ReadinessState =
  /** Settled, and settled well. */
  | 'pass'
  /** Not settled yet, but it will be on its own — this is what holds the gate. */
  | 'waiting'
  /** The answer has been asked for and has not arrived. Holds the gate; resolves in a moment. */
  | 'checking'
  /** Could not be determined at all. Reported, but never allowed to block. */
  | 'unknown'
  /** Does not apply to this meeting. */
  | 'skipped';

export type ReadinessCheckId = 'bot_left' | 'archived' | 'served';

export interface ReadinessCheck {
  id: ReadinessCheckId;
  state: ReadinessState;
  label: string;
  detail: string;
}

export interface RecordingReadiness {
  /**
   * Whether there is anything to report. False for a playlist no bot has ever run on, where a
   * readiness panel would be a box of grey ticks about a meeting that never happened.
   */
  applicable: boolean;
  checks: ReadinessCheck[];
  /** Something is still in flight. The Send button's default disabled state. */
  blocking: boolean;
  /** For the "Send anyway (n of m ready)" label. */
  passed: number;
  total: number;
}

/**
 * What this browser found when it asked its own origin for the archived file.
 *
 * `missing` carries its detail because the reasons are not interchangeable to whoever has to fix
 * it: a 404 is an alias or a filename, a 403 is a uid, and a failed fetch is the share or the
 * network. Reporting "not served" alone sends someone looking in the wrong place.
 */
export type MediaProbe =
  /** No archive to ask about yet — the question is not open. */
  | { state: 'not_yet' }
  | { state: 'checking' }
  | { state: 'served' }
  | { state: 'missing'; detail: string };

export interface ReadinessInputs {
  /** A bot has been dispatched to this playlist at some point. */
  hasMeeting: boolean;
  botStatus: BotStatusEnum | undefined;
  /** Whether this deployment records at all — with no recorder there is no archive to wait for. */
  recordingCapable: boolean;
  cuts: RecordingCutsStatus | undefined;
  /** Why, when `cuts` is `blocked`. The only actionable part of that answer. */
  cutsDetail: string | null | undefined;
  cutsLoading: boolean;
  cutsError: boolean;
  probe: MediaProbe;
}

const EMPTY: RecordingReadiness = {
  applicable: false,
  checks: [],
  blocking: false,
  passed: 0,
  total: 0,
};

/**
 * The rule, as a pure function, so it can be tested as a rule.
 *
 * Exported separately from the hook for the same reason `pollIntervalFor` is: asserting this
 * through the hook needs a query client, a capabilities response and a bot session before the
 * first expectation, and produces tests that pass whatever the rule does.
 */
export function recordingReadiness(
  inputs: ReadinessInputs
): RecordingReadiness {
  const {
    hasMeeting,
    botStatus,
    recordingCapable,
    cuts,
    cutsDetail,
    cutsLoading,
    cutsError,
    probe,
  } = inputs;

  // `no_meeting` is the answer for a playlist whose bot has not been dispatched — including in
  // the seconds before one is. Nothing is in flight, so there is nothing to say and nothing to
  // hold: an email of notes on a playlist that never had a meeting is an ordinary thing to send.
  //
  // Either source is enough to say a meeting exists. They disagree for one moment — a dispatch
  // the cut list has seen and the cached metadata has not — and answering "no meeting" there
  // would drop the panel at exactly the moment it becomes worth showing.
  if (!hasMeeting && (cuts === undefined || cuts === 'no_meeting')) {
    return EMPTY;
  }

  const uploadFinished = cuts !== undefined && UPLOAD_COMPLETE.includes(cuts);

  const botLeft: ReadinessCheck = ((): ReadinessCheck => {
    const id = 'bot_left' as const;
    const label = 'Bot has left the meeting';
    if (uploadFinished) {
      return {
        id,
        state: 'pass',
        label,
        detail: 'The recording finished uploading, so the bot is gone.',
      };
    }
    if (botStatus === undefined) {
      return {
        id,
        state: 'unknown',
        label,
        detail:
          'No bot status for this meeting — it may have run in another session.',
      };
    }
    if (BOT_IN_MEETING.includes(botStatus)) {
      return {
        id,
        state: 'waiting',
        label,
        detail: 'Still in the call — the transcript is still growing.',
      };
    }
    return { id, state: 'pass', label, detail: `Bot is ${botStatus}.` };
  })();

  const archived: ReadinessCheck = ((): ReadinessCheck => {
    const id = 'archived' as const;
    const label = 'Recording archived and verified';
    if (!recordingCapable) {
      return {
        id,
        state: 'skipped',
        label,
        detail: 'This deployment does not record meetings.',
      };
    }
    if (cuts === 'no_recording') {
      return {
        id,
        state: 'skipped',
        label,
        detail: 'Recording was turned off when the bot was dispatched.',
      };
    }
    if (cutsError) {
      // Never blocks. The recording is almost certainly fine and the check is not; refusing to
      // send notes because a status endpoint is down helps nobody.
      return {
        id,
        state: 'unknown',
        label,
        detail: 'Could not reach the recording service to check.',
      };
    }
    if (cutsLoading || cuts === undefined) {
      return { id, state: 'checking', label, detail: 'Checking…' };
    }
    if (cuts === 'pending') {
      return {
        id,
        state: 'waiting',
        label,
        detail: 'The meeting is still being recorded.',
      };
    }
    if (cuts === 'archiving') {
      return {
        id,
        state: 'waiting',
        label,
        detail:
          'Upload finished — the collector is taking custody (about a minute).',
      };
    }
    if (cuts === 'blocked') {
      // Waiting on a PERSON, not on time — so it is the one waiting row that says what to do
      // rather than how long to give it. It reached here as a `pass` once, because everything
      // that was not pending or archiving was assumed archived: the gate opened on a recording
      // that does not exist, and the email went out linking to it.
      return {
        id,
        state: 'waiting',
        label,
        detail:
          cutsDetail ??
          'The collector cannot file this recording. It is safe, but not on the share yet.',
      };
    }
    return {
      id,
      state: 'pass',
      label,
      detail:
        'Written to the recording host, read back and hashed before the upstream copy was released.',
    };
  })();

  const served: ReadinessCheck = ((): ReadinessCheck => {
    const id = 'served' as const;
    const label = 'Playable from this network';
    if (archived.state === 'skipped') {
      // Nothing was recorded, so there is nothing to serve. Reporting it as unserved would
      // invent a fault out of a meeting that was never meant to have a file.
      return { id, state: 'skipped', label, detail: archived.detail };
    }
    if (archived.state === 'unknown') {
      return {
        id,
        state: 'unknown',
        label,
        detail: 'Not checked — the archive could not be looked up.',
      };
    }
    if (probe.state === 'not_yet') {
      // Blocking, but so is `archived` in this state — the gate is held once, and this row is
      // here to say what will be checked next rather than to hold anything on its own.
      return {
        id,
        state: 'waiting',
        label,
        detail: 'Waiting for the archive.',
      };
    }
    if (probe.state === 'checking') {
      return {
        id,
        state: 'checking',
        label,
        detail: 'Fetching it from this origin…',
      };
    }
    if (probe.state === 'missing') {
      // DELIBERATELY BLOCKING, and deliberately not fatal. DNA says the file was written and
      // verified on the share, so this is a serving fault, not a lost recording — but the link
      // in the email is the one this browser just failed to fetch, so sending it is a decision
      // rather than a default.
      return { id, state: 'waiting', label, detail: probe.detail };
    }
    return {
      id,
      state: 'pass',
      label,
      detail: 'Fetched from this origin — the emailed link will resolve.',
    };
  })();

  const checks = [botLeft, archived, served];
  const counted = checks.filter((c) => c.state !== 'skipped');
  return {
    applicable: true,
    checks,
    blocking: checks.some(
      (c) => c.state === 'waiting' || c.state === 'checking'
    ),
    passed: counted.filter((c) => c.state === 'pass').length,
    total: counted.length,
  };
}

/** Re-ask this often while something is still in flight — matched to `useRecordingCuts`. */
const IN_FLIGHT_POLL_MS = 10_000;

/**
 * Readiness for one playlist, live.
 *
 * The bot's status comes from the cached session when there is one — that is event-driven and
 * therefore fresher than any poll — and from the server otherwise, which is what makes the answer
 * survive a page reload. A live session with a missed status frame would pin this to "waiting"
 * forever, which is why `UPLOAD_COMPLETE` overrides it above.
 */
export function useRecordingReadiness(
  playlistId: number | null
): RecordingReadiness {
  const { data: metadata } = usePlaylistMetadata(playlistId);
  const session = useBotSession(playlistId);

  // The deployment's capability alone, NOT the transcription feature flag the recording TAB also
  // checks. That flag decides whether cut lists are worth showing; an archive lands either way,
  // and a meeting that was recorded is still one you want to have landed before you email about it.
  const { recording_playback: recordingCapable } = useCapabilities();

  const platform = (session?.platform ?? metadata?.platform) as
    | Platform
    | undefined;
  const meetingId = session?.meeting_id ?? metadata?.meeting_id;

  const { data: fetchedStatus } = useQuery<BotStatus, Error>({
    queryKey: ['botStatus', platform, meetingId],
    queryFn: () =>
      apiHandler.getBotStatus({ platform: platform!, meetingId: meetingId! }),
    enabled: !!(platform && meetingId && !session),
    // Polled, unlike the one-shot read in `useTranscription`: this hook is watching for the bot
    // to LEAVE, and without a session there are no events to hear it happen.
    refetchInterval: (query) =>
      BOT_IN_MEETING.includes(query.state.data?.status as BotStatusEnum)
        ? IN_FLIGHT_POLL_MS
        : false,
  });

  const cuts = useRecordingCuts(
    recordingCapable ? playlistId : null,
    metadata?.vexa_meeting_id ?? null
  );

  const probe = useMediaProbe(cuts.data?.media_url ?? null);

  return recordingReadiness({
    hasMeeting: metadata?.vexa_meeting_id != null || !!session,
    botStatus: session?.status ?? fetchedStatus?.status,
    recordingCapable,
    cuts: cuts.data?.status,
    cutsDetail: cuts.data?.status_detail,
    cutsLoading: recordingCapable && cuts.isLoading,
    cutsError: cuts.isError,
    probe,
  });
}

/**
 * Ask this origin for the archived file, without downloading it.
 *
 * HEAD rather than a ranged GET: nginx serves these off the share directly, so a HEAD exercises
 * the whole serving path — alias, mount, permissions — and returns no body. A recording is a few
 * hundred MB and this runs while a dialog is open; fetching even the first bytes of one to answer
 * "is it there" would be a strange thing to do repeatedly.
 *
 * A failure is DATA, not a query error: `retry: false` plus a queryFn that never throws keeps
 * "the server said 404" and "the fetch never completed" in the same shape, which is what lets the
 * detail reach the panel instead of being flattened into an error boundary.
 */
/**
 * What one HEAD of the archive means, as a pure function.
 *
 * `null` is the fetch never completing — no origin, no route, no share. It reads as a fourth
 * status code here rather than as an exception, because to the person about to send the email it
 * is the same kind of fact as a 404 and belongs in the same row.
 */
export function interpretMediaProbe(
  response: { ok: boolean; status: number; contentLength: string | null } | null
): { ok: boolean; detail: string } {
  if (response === null) {
    return {
      ok: false,
      detail: 'Could not reach the recordings share from this browser.',
    };
  }
  if (!response.ok) {
    return {
      ok: false,
      // The two are different jobs: a 404 is an alias or a filename, a 403 is the uid the
      // collector wrote as. Naming the code is what points at the right one.
      detail:
        response.status === 404
          ? 'Archived, but this server is not serving it (404) — check the recordings mount.'
          : `This server answered ${response.status} for the recording.`,
    };
  }
  // A zero-length answer passes `ok` and plays as a broken file. It means the archive was seen
  // mid-write, which the collector's ordering should prevent — but catching what the other side
  // cannot see is the entire reason this check exists.
  if (response.contentLength === '0') {
    return { ok: false, detail: 'The archived file is empty on this server.' };
  }
  return { ok: true, detail: '' };
}

function useMediaProbe(mediaUrl: string | null): MediaProbe {
  const { data } = useQuery<{ ok: boolean; detail: string }, Error>({
    queryKey: ['recordingMediaProbe', mediaUrl],
    queryFn: async () => {
      try {
        // `no-store` because a 404 from a file that has not landed yet must not be remembered
        // once it has — the next poll has to see the real answer, not the browser's memory of
        // the last one.
        const response = await fetch(mediaUrl!, {
          method: 'HEAD',
          cache: 'no-store',
        });
        return interpretMediaProbe({
          ok: response.ok,
          status: response.status,
          contentLength: response.headers.get('content-length'),
        });
      } catch {
        return interpretMediaProbe(null);
      }
    },
    enabled: !!mediaUrl,
    retry: false,
    // Keep asking until it is served: a share that has just been written to can lag behind the
    // archive record by an attribute-cache interval, and that resolves without anyone acting.
    refetchInterval: (query) =>
      query.state.data?.ok ? false : IN_FLIGHT_POLL_MS,
    // An archive is written once and never modified, so a success is true for good.
    staleTime: Infinity,
  });

  if (!mediaUrl) {
    return { state: 'not_yet' };
  }
  if (!data) {
    return { state: 'checking' };
  }
  return data.ok
    ? { state: 'served' }
    : { state: 'missing', detail: data.detail };
}
