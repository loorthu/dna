import type { DraftNote } from '@dna/core';

export type NoteStatus = 'published' | 'edited' | 'draft';

/**
 * Which letter, if any, a version carries for a given note.
 *
 * The letters are about work done in DNA. That is not the same question as "is there a note on
 * this version": ShotGrid seeds an empty note per version when a playlist is created, one for the
 * playlist owner, and the sync mirrors every upstream note into a draft row marked published —
 * indistinguishable, once written, from a note DNA pushed. Badging those made every version in a
 * brand new playlist look published by someone who had pushed nothing.
 *
 * `origin` settles it for rows written since it existed. Older rows have none, and the two states
 * are not symmetric:
 *
 *  - Unpublished rows are DNA's. The sync only ever writes `published: true`, so nothing else
 *    could have created them, and their drafts keep their letter.
 *  - Published rows without an origin are not demonstrably DNA's, and nothing had in fact been
 *    published from DNA by the time the field was added, so they get nothing.
 */
export function noteStatus(note: DraftNote | undefined): NoteStatus | null {
  if (!note) return null;
  if (note.origin === 'prodtrack') return null;

  if (note.published) return note.origin === 'dna' ? 'published' : null;
  // Published, then edited here since — only a person editing in DNA moves a note into this state.
  if (note.published_note_id) return 'edited';
  if (note.content || note.subject) return 'draft';
  return null;
}
