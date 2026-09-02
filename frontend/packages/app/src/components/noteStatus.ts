import type { DraftNote, NoteOrigin } from '@dna/core';

export type NoteStatus = 'published' | 'edited' | 'draft';

/**
 * What the rule needs to know about a note, named as the app's local draft names it. Notes reach
 * the UI in two shapes — the server row and the editor's local draft — and the sidebar and the
 * editor each used to decide this for themselves, which is how the sidebar got fixed and the
 * editor went on saying "Published" over the same note.
 */
export interface NoteProvenance {
  origin?: NoteOrigin | null;
  published: boolean;
  publishedNoteId: number | null;
  content?: string | null;
  subject?: string | null;
}

/** Server rows spell two of these differently. */
export function noteProvenance(note: DraftNote): NoteProvenance;
export function noteProvenance(
  note: DraftNote | undefined
): NoteProvenance | undefined;
export function noteProvenance(
  note: DraftNote | undefined
): NoteProvenance | undefined {
  if (!note) return undefined;
  return {
    origin: note.origin,
    published: note.published,
    publishedNoteId: note.published_note_id ?? null,
    content: note.content,
    subject: note.subject,
  };
}

/**
 * Which state, if any, a note is in — the sidebar's letter and the editor's badge both.
 *
 * The states are about work done in DNA. That is not the same question as "is there a note on
 * this version": ShotGrid seeds an empty note per version when a playlist is created, one for the
 * playlist owner, and the sync mirrors every upstream note into a draft row marked published —
 * indistinguishable, once written, from a note DNA pushed. Saying "Published" over those made
 * every version in a brand new playlist look published by someone who had pushed nothing.
 *
 * `origin` settles it for rows written since it existed. Older rows have none, and the two states
 * are not symmetric:
 *
 *  - Unpublished rows are DNA's. The sync only ever writes `published: true`, so nothing else
 *    could have created them, and their drafts keep their badge.
 *  - Published rows without an origin are not demonstrably DNA's, and nothing had in fact been
 *    published from DNA by the time the field was added, so they get nothing.
 */
export function noteStatus(
  note: NoteProvenance | null | undefined
): NoteStatus | null {
  if (!note) return null;
  if (note.origin === 'prodtrack') return null;

  if (note.published) return note.origin === 'dna' ? 'published' : null;
  // Published, then edited here since — only a person editing in DNA moves a note into this state.
  if (note.publishedNoteId) return 'edited';
  if (note.content || note.subject) return 'draft';
  return null;
}

/**
 * The one-letter form used wherever a note's state has to fit in a corner: the
 * sidebar's version cards and the publish grid's State column. Kept beside the
 * rule that produces the status so the two spellings cannot drift apart.
 */
export function noteStatusLetter(status: NoteStatus): string {
  switch (status) {
    case 'published':
      return 'P';
    case 'edited':
      return 'E';
    case 'draft':
      return 'D';
  }
}

/** Spelled out, for tooltips and anywhere there is room for the full thing. */
export function noteStatusLabel(status: NoteStatus): string {
  switch (status) {
    case 'published':
      return 'Published';
    case 'edited':
      return 'Published (Edited)';
    case 'draft':
      return 'Draft';
  }
}
