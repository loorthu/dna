/**
 * Follow Along lets DNA mirror whatever an external review player is showing.
 *
 * The player is not part of DNA: it broadcasts "the room is now looking at
 * this" onto a message broker, and DNA listens. Everything player-specific
 * (payload format, session directory, broker address) is confined to this
 * directory's adapters so a site can swap in its own.
 */

/**
 * A single "what is on screen right now" announcement, normalised out of
 * whatever the review player broadcasts.
 */
export interface ReviewFocus {
  /** Review session the announcement came from; used to filter the topic. */
  session: string;
  /** Show/project code the session belongs to; used to filter the topic. */
  show: string;
  /** Shot name, for display and diagnostics only. */
  shot: string;
  /**
   * Opaque id of the clip in the review player, matched against
   * `Version.external_ref`. Always a string — sites type this field
   * inconsistently, so it is never coerced to a number.
   */
  externalRef: string;
  /**
   * The player's own handle for this clip, distinct from {@link externalRef}.
   *
   * Two announcements can name the same version through different clips, so
   * this is what tells them apart when diagnosing what a session is really
   * broadcasting. Empty when the payload does not carry one.
   */
  clipRef: string;
}

/** A user currently connected to a review session. */
export interface ReviewSessionUser {
  id: string;
  username: string;
}

/** A review session a user can choose to follow. */
export interface ReviewSession {
  id: string;
  name: string;
  users: ReviewSessionUser[];
}

/** Parses one broadcast payload into a focus, or `null` if it is unusable. */
export type ReviewFocusParser = (body: string) => ReviewFocus | null;

export type ReviewFocusCallback = (focus: ReviewFocus) => void;

export type ReviewConnectionStateCallback = (
  connected: boolean,
  error?: Error
) => void;
