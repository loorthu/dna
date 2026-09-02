import { useFeatureFlags } from '../contexts/FeatureFlagsContext';

/**
 * To and CC are collected on a note but never reach ShotGrid: `publish_notes`
 * sends `addressings_to`/`addressings_cc` as empty lists (backend/src/main.py),
 * so the fields promise a notification that never goes out — and the "required"
 * marker on To gates nothing. Flip this to bring both back; stored values are
 * left untouched either way.
 *
 * A constant rather than a feature flag because there is nothing for a site to
 * turn on: no deployment makes these fields reach ShotGrid. Links and Subject
 * differ — they do reach it — so those are `VITE_FEATURE_NOTE_LINKS` and
 * `VITE_FEATURE_NOTE_SUBJECT`.
 */
export const ADDRESSING_FIELDS_ENABLED = false;

/**
 * Whether the note options row renders anything at all. Lives here so the row
 * and the editor that frames it read the same rule: with every field off, the
 * editor header was laying out an empty child and contributing only its gap.
 */
export function useNoteOptionsVisible(): boolean {
  const { noteLinksEnabled, noteSubjectEnabled } = useFeatureFlags();
  return ADDRESSING_FIELDS_ENABLED || noteLinksEnabled || noteSubjectEnabled;
}
