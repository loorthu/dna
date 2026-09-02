export type EntityType =
  | 'Project'
  | 'Shot'
  | 'Asset'
  | 'Note'
  | 'Task'
  | 'Version'
  | 'Playlist';

export interface ProjectReference {
  type: string;
  id: number;
  name?: string;
}

export interface PipelineStep {
  type: string;
  id: number;
  name?: string;
}

export interface UserReference {
  id: number;
  name: string;
  type: string;
}

export interface EntityBase {
  id: number;
  type: EntityType;
}

export interface Project extends EntityBase {
  type: 'Project';
  name?: string;
  /** Short project code used by external tools; falls back to `name`. */
  code?: string;
}

export interface Task extends EntityBase {
  type: 'Task';
  name?: string;
  status?: string;
  pipeline_step?: PipelineStep;
  project?: ProjectReference;
  entity?: EntityBase;
}

export interface Note extends EntityBase {
  type: 'Note';
  subject?: string;
  content?: string;
  project?: ProjectReference;
  note_links: EntityBase[];
}

export interface Shot extends EntityBase {
  type: 'Shot';
  name?: string;
  description?: string;
  project?: ProjectReference;
  tasks: Task[];
}

export interface Asset extends EntityBase {
  type: 'Asset';
  name?: string;
  description?: string;
  project?: ProjectReference;
  tasks: Task[];
}

export interface Version extends EntityBase {
  type: 'Version';
  name?: string;
  description?: string;
  status?: string;
  user?: UserReference;
  created_at?: string;
  updated_at?: string;
  movie_path?: string;
  frame_path?: string;
  thumbnail?: string;
  project?: ProjectReference;
  entity?: Shot | Asset;
  task?: Task;
  notes: Note[];
  prodtrack_detail_url?: string;
  prodtrack_entity_detail_url?: string;
  /** Opaque id for this version in an external review tool. */
  external_ref?: string;
}

export interface Playlist extends EntityBase {
  type: 'Playlist';
  code?: string;
  description?: string;
  project?: ProjectReference;
  created_at?: string;
  updated_at?: string;
  versions: Version[];
  /**
   * How many versions the playlist holds. Present when the backend lists playlists — where
   * `versions` itself is left empty because it is too expensive to carry — and undefined
   * anywhere nobody counted.
   */
  version_count?: number;
}

export interface User {
  id: number;
  type: 'User';
  name?: string;
  email?: string;
  login?: string;
}

export type DNAEntity =
  | Project
  | Shot
  | Asset
  | Note
  | Task
  | Version
  | Playlist
  | User;

export interface EntityLink {
  type: string;
  id: number;
}

export interface CreateNoteRequest {
  subject: string;
  content?: string;
  project: ProjectReference;
  note_links?: EntityLink[];
}

export interface GetProjectsForUserParams {
  userEmail: string;
}

export interface GetPlaylistsForProjectParams {
  projectId: number;
}

export interface GetVersionsForPlaylistParams {
  playlistId: number;
}

export interface AddVersionsToPlaylistParams {
  playlistId: number;
  /** The versions to add, by the id the review tool announces for them (the JTS at SPI). */
  jts: number[];
}

/** What became of one requested id. Some of a pasted list land and some do not. */
export interface AddVersionOutcome {
  jts: number;
  status: 'added' | 'already_in_playlist' | 'not_found';
  version_id?: number | null;
  version_name?: string | null;
}

export interface AddVersionsToPlaylistResponse {
  outcomes: AddVersionOutcome[];
  added_count: number;
}

export interface GetUserByEmailParams {
  userEmail: string;
}

export interface DraftNoteLink {
  entity_type: string;
  entity_id: number;
  entity_name?: string;
}

/**
 * Which side created the note row. A note written in DNA and one mirrored in from the production
 * tracker are the same shape once published, so the backend records the writer at insert time.
 * Absent on rows written before that was recorded.
 */
export type NoteOrigin = 'dna' | 'prodtrack';

export interface DraftNote {
  _id: string;
  user_email: string;
  playlist_id: number;
  version_id: number;
  content: string;
  subject: string;
  to: string;
  cc: string;
  links: DraftNoteLink[];
  version_status: string;
  published: boolean;
  edited: boolean;
  published_note_id?: number | null;
  updated_at: string;
  created_at: string;
  attachment_ids: string[];
  origin?: NoteOrigin | null;
}

export interface DraftNoteUpdate {
  content?: string;
  subject?: string;
  to?: string;
  cc?: string;
  links?: DraftNoteLink[];
  version_status?: string;
  edited?: boolean;
  attachment_ids?: string[];
}

export interface GetDraftNoteParams {
  playlistId: number;
  versionId: number;
  userEmail: string;
}

export interface UpsertDraftNoteParams {
  playlistId: number;
  versionId: number;
  userEmail: string;
  data: DraftNoteUpdate;
}

export interface DeleteDraftNoteParams {
  playlistId: number;
  versionId: number;
  userEmail: string;
}

export interface GetAllDraftNotesParams {
  playlistId: number;
  versionId: number;
}

export interface PlaylistMetadata {
  _id: string;
  playlist_id: number;
  in_review: number | null;
  meeting_id: string | null;
  platform: Platform | null;
  transcription_paused: boolean;
  /**
   * Vexa's id for the meeting the bot last ran on this playlist, or null before the first
   * dispatch. It identifies WHICH meeting, so it changes on every dispatch — which is what tells
   * a cached recording answer that it is about a meeting nobody is asking about any more.
   */
  vexa_meeting_id?: number | null;
}

export interface PlaylistMetadataUpdate {
  in_review?: number | null;
  meeting_id?: string | null;
  platform?: Platform | null;
  transcription_paused?: boolean;
}

export interface GetPlaylistMetadataParams {
  playlistId: number;
}

export interface UpsertPlaylistMetadataParams {
  playlistId: number;
  data: PlaylistMetadataUpdate;
}

export interface DeletePlaylistMetadataParams {
  playlistId: number;
}

export type Platform = 'google_meet' | 'teams';

export type BotStatusEnum =
  | 'idle'
  | 'joining'
  | 'waiting_room'
  | 'in_call'
  | 'transcribing'
  | 'failed'
  | 'stopped'
  | 'completed';

export interface DispatchBotRequest {
  platform: Platform;
  meeting_id: string;
  playlist_id: number;
  passcode?: string;
  bot_name?: string;
  language?: string;
  /** Record the meeting's video as well as transcribing it. Opt-in, per meeting. */
  recording_enabled?: boolean;
}

export interface BotStatus {
  platform: Platform;
  meeting_id: string;
  status: BotStatusEnum;
  message?: string;
  updated_at: string;
}

export interface BotSession {
  platform: Platform;
  meeting_id: string;
  playlist_id: number;
  status: BotStatusEnum;
  bot_name?: string;
  language?: string;
  created_at: string;
  updated_at: string;
  /**
   * Whether this meeting is being recorded, as Vexa RESOLVED it — not as it was requested.
   * A deployment that ignores the request must not leave the UI claiming a recording exists.
   */
  recording_enabled?: boolean;
  /** Whether arriving transcript segments are being stored (false with no version in review). */
  saving_segments?: boolean;
  warnings?: string[];
}

export interface TranscriptSegment {
  text: string;
  speaker?: string;
  start_time?: number;
  end_time?: number;
  timestamp: string;
}

export interface Transcript {
  platform: Platform;
  meeting_id: string;
  segments: TranscriptSegment[];
  language?: string;
  duration?: number;
}

export interface DispatchBotParams {
  request: DispatchBotRequest;
}

export interface StopBotParams {
  platform: Platform;
  meetingId: string;
}

export interface GetBotStatusParams {
  platform: Platform;
  meetingId: string;
}

export interface GetTranscriptParams {
  platform: Platform;
  meetingId: string;
}

export interface StoredSegment {
  id: string;
  segment_id: string;
  playlist_id: number;
  version_id: number;
  text: string;
  speaker?: string;
  language?: string;
  start_time?: number;
  end_time?: number;
  completed?: boolean;
  absolute_start_time: string;
  absolute_end_time: string;
  vexa_updated_at?: string;
  created_at: string;
  updated_at: string;
}

/**
 * One span of the meeting recording that discussed a version — an in/out pair, not a rendered
 * clip. Nothing is cut: the player seeks a single file to `video_in_seconds` and stops at
 * `video_out_seconds`.
 */
export interface RecordingCut {
  video_in_seconds: number;
  video_out_seconds: number;
  transcript_segment_ids: string[];
}

export interface VersionCuts {
  version_id: number;
  /** Stable hash of this version's cut list — the same inputs always produce the same value. */
  body_hash: string;
  cuts: RecordingCut[];
}

/**
 * Everything the player needs for one playlist, in one call.
 *
 * `status` is the load-bearing field. Four situations produce an empty `versions` array and each
 * wants a different thing said to the viewer, so they must not be collapsed into "no cuts":
 *
 *   ready         media and spans are available
 *   pending       the meeting is being recorded right now — come back when it ends
 *   archiving     recorded; the collector has not finished taking custody — come back shortly
 *   no_recording  never recorded, or recording was turned off — nothing is coming
 *   no_segments   recorded, but nothing was said against these versions
 */
/**
 * Which optional pipelines this deployment is configured for.
 *
 * The deployment decides, not the viewer: playing a meeting back needs a recorder, a collector
 * and a share, and only the back end knows whether it has them. A front-end build flag saying the
 * same thing was a second setting that had to agree with this one.
 */
export interface DeploymentCapabilities {
  recording_playback: boolean;
}

export type RecordingCutsStatus =
  | 'ready'
  | 'pending'
  | 'archiving'
  /**
   * Recorded, but the collector cannot file it without someone acting — today, a show whose
   * recording directory does not exist on the share. Distinct from `archiving` because no
   * amount of waiting resolves it, and `status_detail` says what to do.
   */
  | 'blocked'
  /** No bot has ever run on this playlist — the state it is in before the first dispatch. */
  | 'no_meeting'
  /** A meeting ran with recording turned off. */
  | 'no_recording'
  | 'no_segments';

export interface PlaylistRecordingCuts {
  playlist_id: number;
  status: RecordingCutsStatus;
  /** Why, when the status alone does not say enough to act on. Only set for `blocked`. */
  status_detail: string | null;
  /** Served by nginx off the share; null until an archive exists. */
  media_url: string | null;
  duration_seconds: number | null;
  /** The recorder's own clock at its first frame — the zero every offset is measured from. */
  recording_t0: string | null;
  /** Which anchor produced it: a cut list built on the wrong zero looks exactly like a right one. */
  recording_t0_source: string | null;
  versions: VersionCuts[];
}

export interface GetRecordingCutsParams {
  playlistId: number;
}

export interface GetSegmentsParams {
  playlistId: number;
  versionId: number;
}

export interface UserSettings {
  _id: string;
  user_email: string;
  /** Saved custom prompt; empty means use deployment default. */
  note_prompt: string;
  /** Configured default prompt template (for display when note_prompt is empty). */
  default_note_prompt: string;
  regenerate_on_version_change: boolean;
  regenerate_on_transcript_update: boolean;
  sync_prodtrack_tab_on_version_change: boolean;
  prodtrack_page_type: 'version' | 'entity';
  updated_at: string;
  created_at: string;
}

export interface UserSettingsUpdate {
  note_prompt?: string;
  regenerate_on_version_change?: boolean;
  regenerate_on_transcript_update?: boolean;
  sync_prodtrack_tab_on_version_change?: boolean;
  prodtrack_page_type?: 'version' | 'entity';
}

export interface GetUserSettingsParams {
  userEmail: string;
}

export interface UpsertUserSettingsParams {
  userEmail: string;
  data: UserSettingsUpdate;
}

export interface DeleteUserSettingsParams {
  userEmail: string;
}

export interface GenerateNoteParams {
  playlistId: number;
  versionId: number;
  userEmail: string;
  additionalInstructions?: string;
}

export interface GenerateNoteResponse {
  suggestion: string;
  prompt: string;
  context: string;
}

export interface AISuggestionState {
  suggestion: string | null;
  prompt: string | null;
  context: string | null;
  isLoading: boolean;
  error: Error | null;
}

export type AISuggestionStateChangeCallback = (
  playlistId: number,
  versionId: number,
  state: AISuggestionState
) => void;

// Search types for entity search endpoint
export type SearchableEntityType =
  | 'user'
  | 'shot'
  | 'asset'
  | 'version'
  | 'task'
  | 'playlist';

export interface SearchRequest {
  query: string;
  entity_types: SearchableEntityType[];
  project_id?: number;
  limit?: number;
}

export interface SearchResult {
  type: string;
  id: number;
  name: string;
  description?: string;
  email?: string;
  project?: {
    type: string;
    id: number;
  };
}

export interface SearchResponse {
  results: SearchResult[];
}

export interface SearchEntitiesParams {
  query: string;
  entityTypes: SearchableEntityType[];
  projectId?: number;
  limit?: number;
}

// Status types for version status dropdown
export interface StatusOption {
  code: string;
  name: string;
}

export interface GetVersionStatusesParams {
  projectId?: number;
}

export interface PublishNoteTarget {
  user_email: string;
  version_id: number;
}

export interface PublishNotesRequest {
  user_email: string;
  targets: PublishNoteTarget[];
}

export interface PublishNotesResponse {
  published_count: number;
  republished_count: number;
  skipped_count: number;
  failed_count: number;
  total: number;
}

export interface PublishNotesParams {
  playlistId: number;
  request: PublishNotesRequest;
}

export interface PublishTranscriptRequest {
  version_id: number;
}

export interface PublishTranscriptResponse {
  transcript_entity_id: number;
  outcome: 'created' | 'updated' | 'skipped';
  skipped_reason?: string | null;
  segments_count: number;
}

export interface PublishTranscriptParams {
  playlistId: number;
  request: PublishTranscriptRequest;
}

export interface EmailNotesRequest {
  to: string;
  cc?: string;
  subject?: string;
  sent_by: string;
}

export interface EmailNotesParams {
  playlistId: number;
  request: EmailNotesRequest;
}

export type NoteQCSeverity = 'warning' | 'error';

export interface NoteQCCheck {
  _id: string;
  user_email: string;
  name: string;
  prompt: string;
  severity: NoteQCSeverity;
  enabled: boolean;
  updated_at: string;
  created_at: string;
}

export interface NoteQCCheckCreate {
  name: string;
  prompt: string;
  severity: NoteQCSeverity;
  enabled?: boolean;
}

export interface NoteQCCheckUpdate {
  name?: string;
  prompt?: string;
  severity?: NoteQCSeverity;
  enabled?: boolean;
}

export interface NoteQCAttributeSuggestion {
  to?: string | null;
  cc?: string | null;
  subject?: string | null;
  version_status?: string | null;
  links?: DraftNoteLink[] | null;
}

export interface NoteQCResult {
  check_id: string;
  check_name: string;
  severity: NoteQCSeverity;
  passed: boolean;
  issue?: string | null;
  evidence?: string | null;
  note_suggestion?: string | null;
  attribute_suggestion?: NoteQCAttributeSuggestion | null;
}

export interface RunQCChecksRequestBody {
  user_email: string;
}

export interface RunQCChecksResponseBody {
  results: NoteQCResult[];
}

export interface GetQCChecksParams {
  userEmail: string;
}

export interface CreateQCCheckParams {
  userEmail: string;
  data: NoteQCCheckCreate;
}

export interface UpdateQCCheckParams {
  userEmail: string;
  checkId: string;
  data: NoteQCCheckUpdate;
}

export interface DeleteQCCheckParams {
  userEmail: string;
  checkId: string;
}

export interface RunQCChecksParams {
  playlistId: number;
  versionId: number;
  userEmail: string;
}

/**
 * The artist-facing view of a review, in one response.
 *
 * A read-only projection built server-side rather than the shapes the reviewing tool uses. The
 * page shows a whole playlist at once and edits none of it, so asking per shot for its version,
 * notes, segments and cut list would be four requests apiece — about ninety for a dailies — to
 * build something that never changes after it loads.
 */
export interface ReviewNote {
  author_email: string;
  /** Byline derived from the mailbox, since a draft note stores only an address. */
  author_name: string;
  subject: string;
  content: string;
  published: boolean;
  updated_at: string | null;
}

export interface ReviewTranscriptLine {
  speaker: string | null;
  text: string;
  absolute_start_time: string | null;
  start_time: number | null;
}

export interface ReviewCut {
  video_in_seconds: number;
  video_out_seconds: number;
}

export interface ReviewShot {
  version_id: number;
  /** Fragment identifier for this shot — what the notes email links to. */
  anchor: string;
  index: number;
  name: string;
  entity_name: string;
  task_name: string;
  artist_name: string;
  status: string;
  thumbnail: string | null;
  frame_path: string;
  created_at: string | null;
  prodtrack_detail_url: string | null;
  notes: ReviewNote[];
  transcript: ReviewTranscriptLine[];
  cuts: ReviewCut[];
}

/**
 * The same enum the coordinator's player uses, plus `disabled` for a deployment with no
 * recording pipeline at all — the review page has no capabilities call of its own.
 */
export type ReviewRecordingStatus = RecordingCutsStatus | 'disabled';

export interface ReviewRecording {
  status: ReviewRecordingStatus;
  media_url: string | null;
  duration_seconds: number | null;
}

export interface ReviewPlaylist {
  playlist_id: number;
  playlist_name: string;
  project_id: number | null;
  project_name: string;
  project_code: string;
  /** Canonical path for this page, which may differ from the one that was followed. */
  url_path: string;
  screened_at: string | null;
  recording: ReviewRecording;
  shots: ReviewShot[];
}

export interface ReviewPlaylistRef {
  playlist_id: number;
  playlist_name: string;
  url_path: string;
  created_at: string | null;
  version_count: number | null;
}

/**
 * What a `/review/<project>/<name>` address resolved to.
 *
 * `playlist_id` null with several `matches` is not a failure: a show that screens "Dailies" every
 * day has many playlists of one name, and the page offers the choice rather than guessing — the
 * newest is the wrong answer for anyone following a link to an older review.
 */
export interface ReviewResolution {
  playlist_id: number | null;
  matches: ReviewPlaylistRef[];
}

/**
 * Where a playlist's artist page is, and the fragment for each shot in it.
 *
 * Asked for rather than assembled in the browser: slugging is lossy, and the page, the notes
 * email and the reviewing tool's button all have to produce the same string. A second
 * implementation here would agree with the backend right up until one of them changed.
 */
export interface ReviewLink {
  playlist_id: number;
  url_path: string;
  /** Fragment per version id — keys arrive as strings, the way JSON object keys do. */
  anchors: Record<string, string>;
}

export interface GetReviewLinkParams {
  playlistId: number;
}

export interface ResolveReviewAddressParams {
  projectSlug: string;
  playlistSlug: string;
}

export interface GetReviewPlaylistParams {
  playlistId: number;
}
