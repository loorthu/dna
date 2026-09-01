import axios, { AxiosInstance, AxiosRequestConfig, AxiosResponse } from 'axios';
import {
  AddVersionsToPlaylistParams,
  AddVersionsToPlaylistResponse,
  EmailNotesParams,
  GetProjectsForUserParams,
  GetPlaylistsForProjectParams,
  GetVersionsForPlaylistParams,
  GetUserByEmailParams,
  GetDraftNoteParams,
  GetAllDraftNotesParams,
  UpsertDraftNoteParams,
  DeleteDraftNoteParams,
  GetPlaylistMetadataParams,
  UpsertPlaylistMetadataParams,
  DeletePlaylistMetadataParams,
  DispatchBotParams,
  StopBotParams,
  GetBotStatusParams,
  GetTranscriptParams,
  DeploymentCapabilities,
  GetRecordingCutsParams,
  GetReviewLinkParams,
  GetReviewPlaylistParams,
  GetSegmentsParams,
  ResolveReviewAddressParams,
  ReviewLink,
  ReviewPlaylist,
  ReviewResolution,
  GetUserSettingsParams,
  UpsertUserSettingsParams,
  DeleteUserSettingsParams,
  GenerateNoteParams,
  GenerateNoteResponse,
  GetVersionStatusesParams,
  PublishNotesParams,
  PublishNotesResponse,
  PublishTranscriptParams,
  PublishTranscriptResponse,
  DraftNote,
  Playlist,
  PlaylistMetadata,
  Project,
  User as DNAUser,
  Version,
  BotSession,
  BotStatus,
  Transcript,
  PlaylistRecordingCuts,
  StoredSegment,
  UserSettings,
  SearchEntitiesParams,
  SearchResponse,
  SearchResult,
  StatusOption,
  NoteQCCheck,
  NoteQCCheckCreate,
  NoteQCCheckUpdate,
  NoteQCResult,
  RunQCChecksResponseBody,
  GetQCChecksParams,
  CreateQCCheckParams,
  UpdateQCCheckParams,
  DeleteQCCheckParams,
  RunQCChecksParams,
} from './interfaces';

export interface User {
  id: string;
  name?: string;
  email?: string;
  token?: string;
}

export interface ApiHandlerConfig {
  baseURL: string;
  timeout?: number;
}

function normalizeNoteQCCheck(raw: NoteQCCheck & { id?: string }): NoteQCCheck {
  return {
    ...raw,
    _id: raw._id || raw.id || '',
  };
}

class ApiHandler {
  private axiosInstance: AxiosInstance;
  private currentUser: User | null = null;

  constructor(config: ApiHandlerConfig) {
    this.axiosInstance = axios.create({
      baseURL: config.baseURL,
      timeout: config.timeout ?? 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    this.axiosInstance.interceptors.request.use((requestConfig) => {
      if (this.currentUser?.token) {
        requestConfig.headers.Authorization = `Bearer ${this.currentUser.token}`;
      }
      if (this.currentUser?.id) {
        requestConfig.headers['X-User-Id'] = this.currentUser.id;
      }
      return requestConfig;
    });
  }

  setUser(user: User | null): void {
    this.currentUser = user;
  }

  getUser(): User | null {
    return this.currentUser;
  }

  async get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    const response: AxiosResponse<T> = await this.axiosInstance.get(
      url,
      config
    );
    return response.data;
  }

  async post<T>(
    url: string,
    data?: unknown,
    config?: AxiosRequestConfig
  ): Promise<T> {
    const response: AxiosResponse<T> = await this.axiosInstance.post(
      url,
      data,
      config
    );
    return response.data;
  }

  async put<T>(
    url: string,
    data?: unknown,
    config?: AxiosRequestConfig
  ): Promise<T> {
    const response: AxiosResponse<T> = await this.axiosInstance.put(
      url,
      data,
      config
    );
    return response.data;
  }

  async delete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    const response: AxiosResponse<T> = await this.axiosInstance.delete(
      url,
      config
    );
    return response.data;
  }

  async getProjectsForUser(
    params: GetProjectsForUserParams
  ): Promise<Project[]> {
    return this.get<Project[]>(
      `/projects/user/${encodeURIComponent(params.userEmail)}`
    );
  }

  async getPlaylistsForProject(
    params: GetPlaylistsForProjectParams
  ): Promise<Playlist[]> {
    return this.get<Playlist[]>(`/projects/${params.projectId}/playlists`);
  }

  async getVersionsForPlaylist(
    params: GetVersionsForPlaylistParams
  ): Promise<Version[]> {
    return this.get<Version[]>(`/playlists/${params.playlistId}/versions`);
  }

  async addVersionsToPlaylist(
    params: AddVersionsToPlaylistParams
  ): Promise<AddVersionsToPlaylistResponse> {
    return this.post<AddVersionsToPlaylistResponse>(
      `/playlists/${params.playlistId}/versions`,
      { jts: params.jts }
    );
  }

  async getUserByEmail(params: GetUserByEmailParams): Promise<DNAUser> {
    return this.get<DNAUser>(`/users/${encodeURIComponent(params.userEmail)}`);
  }

  async getDraftNote(params: GetDraftNoteParams): Promise<DraftNote | null> {
    return this.get<DraftNote | null>(
      `/playlists/${params.playlistId}/versions/${params.versionId}/draft-notes/${encodeURIComponent(params.userEmail)}`
    );
  }

  async upsertDraftNote(params: UpsertDraftNoteParams): Promise<DraftNote> {
    return this.put<DraftNote>(
      `/playlists/${params.playlistId}/versions/${params.versionId}/draft-notes/${encodeURIComponent(params.userEmail)}`,
      params.data
    );
  }

  async deleteDraftNote(params: DeleteDraftNoteParams): Promise<boolean> {
    return this.delete<boolean>(
      `/playlists/${params.playlistId}/versions/${params.versionId}/draft-notes/${encodeURIComponent(params.userEmail)}`
    );
  }

  async getAllDraftNotes(params: GetAllDraftNotesParams): Promise<DraftNote[]> {
    return this.get<DraftNote[]>(
      `/playlists/${params.playlistId}/versions/${params.versionId}/draft-notes`
    );
  }

  async getPlaylistMetadata(
    params: GetPlaylistMetadataParams
  ): Promise<PlaylistMetadata | null> {
    return this.get<PlaylistMetadata | null>(
      `/playlists/${params.playlistId}/metadata`
    );
  }

  async upsertPlaylistMetadata(
    params: UpsertPlaylistMetadataParams
  ): Promise<PlaylistMetadata> {
    return this.put<PlaylistMetadata>(
      `/playlists/${params.playlistId}/metadata`,
      params.data
    );
  }

  async deletePlaylistMetadata(
    params: DeletePlaylistMetadataParams
  ): Promise<boolean> {
    return this.delete<boolean>(`/playlists/${params.playlistId}/metadata`);
  }

  async dispatchBot(params: DispatchBotParams): Promise<BotSession> {
    return this.post<BotSession>('/transcription/bot', params.request);
  }

  async stopBot(params: StopBotParams): Promise<boolean> {
    return this.delete<boolean>(
      `/transcription/bot/${params.platform}/${encodeURIComponent(params.meetingId)}`
    );
  }

  async getBotStatus(params: GetBotStatusParams): Promise<BotStatus> {
    return this.get<BotStatus>(
      `/transcription/bot/${params.platform}/${encodeURIComponent(params.meetingId)}/status`
    );
  }

  async getTranscript(params: GetTranscriptParams): Promise<Transcript> {
    return this.get<Transcript>(
      `/transcription/transcript/${params.platform}/${encodeURIComponent(params.meetingId)}`
    );
  }

  async getSegmentsForVersion(
    params: GetSegmentsParams
  ): Promise<StoredSegment[]> {
    return this.get<StoredSegment[]>(
      `/transcription/segments/${params.playlistId}/${params.versionId}`
    );
  }

  /**
   * Where each version was discussed in the meeting recording, plus the media URL to play.
   *
   * One call rather than several: the player needs the media, the anchor and the spans together,
   * and `status` distinguishes the several ways there can be nothing to play yet.
   */
  async getRecordingCuts(
    params: GetRecordingCutsParams
  ): Promise<PlaylistRecordingCuts> {
    return this.get<PlaylistRecordingCuts>(
      `/recordings/cuts/${params.playlistId}`
    );
  }

  /**
   * Where a playlist's artist page is, and the anchor for each of its shots.
   *
   * The cheap half of the review API: it costs the production tracker's answer about the
   * playlist and its version names, and nothing from the note store or the recording. Cheap
   * enough to sit behind a button in the reviewing tool.
   */
  async getReviewLink(params: GetReviewLinkParams): Promise<ReviewLink> {
    return this.get<ReviewLink>(`/review/link/${params.playlistId}`);
  }

  /**
   * Turn a `/review/<project>/<playlist>` address into a playlist id.
   *
   * Slugs are what the notes email links to, and they are not unique — the response either names
   * one playlist or lists every one the address could have meant, for the page to offer.
   */
  async resolveReviewAddress(
    params: ResolveReviewAddressParams
  ): Promise<ReviewResolution> {
    return this.get<ReviewResolution>(
      `/review/resolve/${encodeURIComponent(params.projectSlug)}/${encodeURIComponent(
        params.playlistSlug
      )}`
    );
  }

  /**
   * The artist-facing view of a playlist: every shot with its notes, transcript and cut list.
   *
   * One call for the whole page. It is read-only and assembled server-side, so nothing here is
   * refetched as the reader scrolls.
   */
  async getReviewPlaylist(
    params: GetReviewPlaylistParams
  ): Promise<ReviewPlaylist> {
    return this.get<ReviewPlaylist>(`/review/playlists/${params.playlistId}`);
  }

  /**
   * Which optional pipelines this deployment is configured for.
   *
   * Asked rather than mirrored into a build flag: the back end is the side that knows whether a
   * recorder, collector and share exist, and two settings that have to agree eventually do not.
   */
  async getCapabilities(): Promise<DeploymentCapabilities> {
    return this.get<DeploymentCapabilities>('/capabilities');
  }

  async getUserSettings(params: GetUserSettingsParams): Promise<UserSettings> {
    return this.get<UserSettings>(
      `/users/${encodeURIComponent(params.userEmail)}/settings`
    );
  }

  async upsertUserSettings(
    params: UpsertUserSettingsParams
  ): Promise<UserSettings> {
    return this.put<UserSettings>(
      `/users/${encodeURIComponent(params.userEmail)}/settings`,
      params.data
    );
  }

  async deleteUserSettings(params: DeleteUserSettingsParams): Promise<boolean> {
    return this.delete<boolean>(
      `/users/${encodeURIComponent(params.userEmail)}/settings`
    );
  }

  async generateNote(
    params: GenerateNoteParams
  ): Promise<GenerateNoteResponse> {
    return this.post<GenerateNoteResponse>('/generate-note', {
      playlist_id: params.playlistId,
      version_id: params.versionId,
      user_email: params.userEmail,
      additional_instructions: params.additionalInstructions,
    });
  }

  async searchEntities(params: SearchEntitiesParams): Promise<SearchResult[]> {
    const response = await this.post<SearchResponse>('/search', {
      query: params.query,
      entity_types: params.entityTypes,
      project_id: params.projectId,
      limit: params.limit ?? 10,
    });
    return response.results;
  }

  async getVersionStatuses(
    params: GetVersionStatusesParams
  ): Promise<StatusOption[]> {
    const queryParams = params.projectId
      ? `?project_id=${params.projectId}`
      : '';
    return this.get<StatusOption[]>(`/version-statuses${queryParams}`);
  }

  async getPlaylistDraftNotes(playlistId: number): Promise<DraftNote[]> {
    return this.get<DraftNote[]>(`/playlists/${playlistId}/draft-notes`);
  }

  async publishNotes(
    params: PublishNotesParams
  ): Promise<PublishNotesResponse> {
    return this.post<PublishNotesResponse>(
      `/playlists/${params.playlistId}/publish-notes`,
      params.request
    );
  }

  async publishTranscript(
    params: PublishTranscriptParams
  ): Promise<PublishTranscriptResponse> {
    return this.post<PublishTranscriptResponse>(
      `/playlists/${params.playlistId}/publish-transcript`,
      params.request
    );
  }

  async emailNotes(params: EmailNotesParams): Promise<void> {
    await this.post<void>(
      `/playlists/${params.playlistId}/email-notes`,
      params.request
    );
  }

  async getQCChecks(params: GetQCChecksParams): Promise<NoteQCCheck[]> {
    const rows = await this.get<(NoteQCCheck & { id?: string })[]>(
      `/users/${encodeURIComponent(params.userEmail)}/qc-checks`
    );
    return rows.map((r) => normalizeNoteQCCheck(r));
  }

  async createQCCheck(params: CreateQCCheckParams): Promise<NoteQCCheck> {
    const row = await this.post<NoteQCCheck & { id?: string }>(
      `/users/${encodeURIComponent(params.userEmail)}/qc-checks`,
      params.data
    );
    return normalizeNoteQCCheck(row);
  }

  async updateQCCheck(params: UpdateQCCheckParams): Promise<NoteQCCheck> {
    const row = await this.put<NoteQCCheck & { id?: string }>(
      `/users/${encodeURIComponent(params.userEmail)}/qc-checks/${encodeURIComponent(params.checkId)}`,
      params.data
    );
    return normalizeNoteQCCheck(row);
  }

  async deleteQCCheck(params: DeleteQCCheckParams): Promise<void> {
    await this.axiosInstance.delete(
      `/users/${encodeURIComponent(params.userEmail)}/qc-checks/${encodeURIComponent(params.checkId)}`
    );
  }

  async runQCChecks(params: RunQCChecksParams): Promise<NoteQCResult[]> {
    const body = await this.post<RunQCChecksResponseBody>(
      `/playlists/${params.playlistId}/versions/${params.versionId}/run-qc-checks`,
      { user_email: params.userEmail },
      { timeout: 180_000 }
    );
    return body.results;
  }

  async uploadAttachment(
    file: File
  ): Promise<{ id: string; filename: string }> {
    const formData = new FormData();
    formData.append('file', file);
    const response = await this.axiosInstance.postForm<{
      id: string;
      filename: string;
    }>('/api/attachments', formData);
    return response.data;
  }

  async deleteAttachment(attachmentId: string): Promise<void> {
    await this.delete(`/api/attachments/${attachmentId}`);
  }

  async getAttachmentBlobUrl(attachmentId: string): Promise<string> {
    const response = await this.axiosInstance.get<Blob>(
      `/api/attachments/${attachmentId}`,
      { responseType: 'blob' }
    );
    return URL.createObjectURL(response.data);
  }
}

export const createApiHandler = (config: ApiHandlerConfig): ApiHandler => {
  return new ApiHandler(config);
};

export { ApiHandler };
