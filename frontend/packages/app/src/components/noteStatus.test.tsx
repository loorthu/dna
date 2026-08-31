import { describe, it, expect } from 'vitest';
import type { DraftNote } from '@dna/core';
import { noteStatus } from './noteStatus';

function note(fields: Partial<DraftNote>): DraftNote {
  return {
    _id: 'n1',
    user_email: 'reviewer@test.com',
    playlist_id: 463291,
    version_id: 3880022,
    content: '',
    subject: '',
    to: '',
    cc: '',
    links: [],
    version_status: '',
    published: false,
    edited: false,
    published_note_id: null,
    updated_at: '2026-08-31T17:31:06.314Z',
    created_at: '2026-08-31T17:31:06.314Z',
    attachment_ids: [],
    ...fields,
  };
}

describe('noteStatus', () => {
  it('does not badge the empty note ShotGrid seeds when a playlist is created', () => {
    // The regression this exists for: every version of a new playlist showed "P" for its owner,
    // who had published nothing. ShotGrid makes one empty note per version at creation, the sync
    // mirrors it in as published, and the badge took that at face value. Note the subject — SG's
    // note-from-playlist flow fills it with the playlist's own name, so emptiness alone is not
    // what identifies these.
    const seeded = note({
      published: true,
      published_note_id: 9001,
      subject: 'Dev Test - Pls Ignore',
      origin: 'prodtrack',
    });

    expect(noteStatus(seeded)).toBeNull();
  });

  it('badges a note published from DNA', () => {
    expect(
      noteStatus(
        note({
          published: true,
          published_note_id: 9002,
          content: 'Needs more contrast',
          origin: 'dna',
        })
      )
    ).toBe('published');
  });

  it('withholds the published letter from rows predating origin', () => {
    // Nothing had been published from DNA when the field was added, so a published row with no
    // origin is a mirror of an upstream note, not evidence of anyone publishing from here.
    expect(
      noteStatus(
        note({
          published: true,
          published_note_id: 9003,
          content: 'From ShotGrid',
        })
      )
    ).toBeNull();
  });

  it('keeps the draft letter on rows predating origin', () => {
    // Asymmetry on purpose: the sync only ever writes published rows, so an unpublished one was
    // typed in DNA. Blanking these would read as somebody's draft having gone missing.
    expect(noteStatus(note({ content: 'Half a thought' }))).toBe('draft');
  });

  it('reports a published note edited since as edited', () => {
    // Only a person editing in DNA moves a note into this state, so it stands without an origin.
    expect(
      noteStatus(
        note({ published: false, published_note_id: 9004, content: 'Reworded' })
      )
    ).toBe('edited');
  });

  it('says nothing about a version with no note, or an untouched one', () => {
    expect(noteStatus(undefined)).toBeNull();
    expect(noteStatus(note({ origin: 'dna' }))).toBeNull();
  });
});
