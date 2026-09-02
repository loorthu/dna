import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import styled from 'styled-components';
import {
  Dialog,
  Button,
  Checkbox,
  Flex,
  Text,
  Callout,
  IconButton,
  DropdownMenu,
} from '@radix-ui/themes';
import { Loader2, Info, MoreVertical } from 'lucide-react';
import { usePublishNotes } from '../hooks/usePublishNotes';
import { usePublishTranscript } from '../hooks/usePublishTranscript';
import { EmailNotesDialog } from './EmailNotesDialog';
import { useSegments } from '../hooks';
import {
  useDraftNote,
  backendToLocal,
  type LocalDraftNote,
} from '../hooks/useDraftNote';
import { useNoteQCChecks } from '../hooks/useNoteQCChecks';
import { DraftNote, Version, SearchResult, NoteQCResult } from '@dna/core';
import { NoteEditor } from './NoteEditor';
import { UserAvatar } from './UserAvatar';
import { NoteQCResultPill } from './NoteQCResultPill';
import { NoteQCDiffModal } from './NoteQCDiffModal';
import { useFeatureFlags } from '../contexts';
import {
  noteProvenance,
  noteStatus,
  noteStatusLabel,
  noteStatusLetter,
  type NoteStatus,
} from './noteStatus';

interface PublishNotesDialogProps {
  open: boolean;
  onClose: () => void;
  playlistId: number;
  userEmail: string;
  notes: DraftNote[];
  versions?: Version[];
}

export interface PublishNotesTabContentProps {
  open: boolean;
  onClose: () => void;
  playlistId: number;
  userEmail: string;
  notes: DraftNote[];
  versions?: Version[];
  onPendingChange?: (isPending: boolean) => void;
  showTitle?: boolean;
}

const SpinnerIcon = styled(Loader2)`
  animation: spin 1s linear infinite;
  @keyframes spin {
    from {
      transform: rotate(0deg);
    }
    to {
      transform: rotate(360deg);
    }
  }
`;

const ResultList = styled.ul`
  margin: 0;
  padding-left: 20px;
  font-size: 14px;
`;

const SummaryBox = styled.div`
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  background: ${({ theme }) => theme.colors.bg.surfaceHover};
  border-radius: ${({ theme }) => theme.radii.md};
  margin-top: 12px;
`;

const ScrollBody = styled.div`
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 20px;
`;

const FooterBar = styled.div`
  flex-shrink: 0;
  padding: 16px 20px;
  border-top: 1px solid ${({ theme }) => theme.colors.border.subtle};
`;

const VersionCard = styled.div`
  background: ${({ theme }) => theme.colors.bg.surface};
  border: 1px solid ${({ theme }) => theme.colors.border.subtle};
  border-radius: ${({ theme }) => theme.radii.lg};
  margin-bottom: 16px;
  overflow: hidden;
`;

const VersionCardHeader = styled.div`
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: ${({ theme }) => theme.colors.bg.surfaceHover};
  border-bottom: 1px solid ${({ theme }) => theme.colors.border.subtle};
`;

const CardBody = styled.div`
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
`;

/* Inside the note row, after the checkbox — the tick has to be the leftmost
   control in both views, so the frame cannot sit outside the row. */
const BigThumb = styled.div`
  width: 240px;
  aspect-ratio: 16 / 9;
  border-radius: ${({ theme }) => theme.radii.md};
  overflow: hidden;
  flex-shrink: 0;
  background: ${({ theme }) => theme.colors.bg.base};
  border: 1px solid ${({ theme }) => theme.colors.border.default};

  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
`;

const VersionName = styled.span`
  font-size: 13px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.text.primary};
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 1;
  min-width: 0;
`;

const HeaderDivider = styled.span`
  width: 1px;
  height: 12px;
  flex-shrink: 0;
  background: ${({ theme }) => theme.colors.border.default};
`;

const ArtistName = styled.span`
  font-size: 12px;
  color: ${({ theme }) => theme.colors.text.muted};
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 0;
`;

/* An unticked row is not going to ShotGrid, and that has to read at a glance —
   a faint checkbox was too easy to miss. Everything but the checkbox fades and
   desaturates, and the editor beneath is made read-only to match. */
const NoteRowBlock = styled.div<{ $excluded?: boolean }>`
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding-bottom: 8px;
  transition: opacity ${({ theme }) => theme.transitions.fast};

  ${({ $excluded }) =>
    $excluded &&
    `
    > *:not(:first-child) {
      opacity: 0.4;
      filter: grayscale(0.8);
    }
  `}
  border-bottom: 1px solid ${({ theme }) => theme.colors.border.subtle};

  &:last-child {
    border-bottom: none;
    padding-bottom: 0;
  }
`;

const NoteRowMeta = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  padding-top: 6px;
`;

const NoteRowEditor = styled.div`
  flex: 1;
  min-width: 0;
`;

/* --- Grid view -------------------------------------------------------------
   One row per note rather than a card per version: the point is to scan what is
   about to reach ShotGrid, fix a line, and tick rows off. Editing here is a
   plain text box — no markdown toolbar, mentions or image paste — so the card
   view remains the one for composing. */
const PUBLISH_VIEW_KEY = 'dna-publish-view';

// Minimums stay small deliberately: they have to add up to less than the
// dialog's inner width or the note cell overflows its own row.
const GRID_COLUMNS = '30px 190px 110px minmax(260px, 1fr)';

const GridWrap = styled.div`
  border: 1px solid ${({ theme }) => theme.colors.border.subtle};
  border-radius: ${({ theme }) => theme.radii.lg};
  overflow: hidden;
`;

const GridHeader = styled.div`
  display: grid;
  grid-template-columns: ${GRID_COLUMNS};
  gap: 10px;
  padding: 8px 12px;
  background: ${({ theme }) => theme.colors.bg.surfaceHover};
  border-bottom: 1px solid ${({ theme }) => theme.colors.border.subtle};
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: ${({ theme }) => theme.colors.text.muted};
  position: sticky;
  top: 0;
  z-index: 1;
`;

const GridRow = styled.div<{ $selected: boolean }>`
  display: grid;
  grid-template-columns: ${GRID_COLUMNS};
  gap: 10px;
  align-items: start;
  padding: 8px 12px;
  border-bottom: 1px solid ${({ theme }) => theme.colors.border.subtle};
  /* A selected row is the norm, so the unselected one is what gets marked. */
  background: ${({ $selected, theme }) =>
    $selected ? theme.colors.bg.surfaceHover : 'transparent'};
  transition: opacity ${({ theme }) => theme.transitions.fast};

  ${({ $selected }) =>
    !$selected &&
    `
    > *:not(:first-child) {
      opacity: 0.4;
      filter: grayscale(0.8);
    }
  `}

  &:last-child {
    border-bottom: none;
  }
`;

const GridCell = styled.div`
  min-width: 0;
  font-size: 12px;
  color: ${({ theme }) => theme.colors.text.secondary};
  padding-top: 3px;
  overflow-wrap: anywhere;
`;

const GridStatusDot = styled.div<{ $status: NoteStatus }>`
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  font-size: 11px;
  font-weight: 700;
  color: #ffffff;
  cursor: default;
  background-color: ${({ theme, $status }) =>
    $status === 'published'
      ? theme.colors.status.success
      : $status === 'edited'
        ? theme.colors.status.warning
        : theme.colors.status.info};
`;

const GridVersionCell = styled(GridCell)`
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 0;
  font-variant-numeric: tabular-nums;
  color: ${({ theme }) => theme.colors.text.primary};
`;

const GridThumb = styled.div`
  width: 80px;
  height: 50px;
  border-radius: ${({ theme }) => theme.radii.sm};
  overflow: hidden;
  flex-shrink: 0;
  background: ${({ theme }) => theme.colors.bg.base};
  border: 1px solid ${({ theme }) => theme.colors.border.default};

  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
`;

/* Grows with its content so a long note is readable without opening anything,
   and stops at a height that keeps neighbouring rows on screen. */
const GridNoteInput = styled.textarea`
  width: 100%;
  min-height: 73px;
  max-height: 340px;
  resize: vertical;
  padding: 5px 8px;
  font-size: 12px;
  line-height: 1.5;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.primary};
  background: ${({ theme }) => theme.colors.bg.base};
  border: 1px solid ${({ theme }) => theme.colors.border.subtle};
  border-radius: ${({ theme }) => theme.radii.sm};
  outline: none;

  &::placeholder {
    color: ${({ theme }) => theme.colors.text.muted};
  }

  &:focus {
    border-color: ${({ theme }) => theme.colors.accent.main};
    box-shadow: 0 0 0 2px ${({ theme }) => theme.colors.accent.subtle};
  }

  &:disabled {
    cursor: not-allowed;
    text-decoration: line-through;
    background: transparent;
    border-style: dashed;
  }
`;

const ViewToggle = styled.div`
  display: inline-flex;
  border: 1px solid ${({ theme }) => theme.colors.border.subtle};
  border-radius: ${({ theme }) => theme.radii.sm};
  overflow: hidden;
`;

const ViewToggleButton = styled.button<{ $active: boolean }>`
  padding: 4px 10px;
  font-size: 12px;
  font-family: ${({ theme }) => theme.fonts.sans};
  cursor: pointer;
  border: none;
  background: ${({ $active, theme }) =>
    $active ? theme.colors.accent.subtle : 'transparent'};
  color: ${({ $active, theme }) =>
    $active ? theme.colors.text.primary : theme.colors.text.muted};

  &:hover {
    color: ${({ theme }) => theme.colors.text.primary};
  }
`;

const TranscriptRow = styled.div`
  display: flex;
  align-items: center;
  padding: 10px 0 4px;
`;

const TranscriptExpanded = styled.div`
  max-height: 220px;
  overflow-y: auto;
  padding: 8px 0 4px;
  display: flex;
  flex-direction: column;
  gap: 8px;
`;

const SegmentBlock = styled.div<{ $showHeader: boolean }>`
  padding: ${({ $showHeader }) => ($showHeader ? '6px 0 2px' : '0 0 2px')};
`;

const SegmentSpeakerRow = styled.div`
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2px;
`;

const SegmentSpeaker = styled.span`
  font-size: 11px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.text.primary};
`;

const SegmentTimestamp = styled.span`
  font-size: 10px;
  color: ${({ theme }) => theme.colors.text.muted};
`;

const ToggleTranscriptButton = styled.button`
  display: flex;
  align-items: center;
  justify-content: center;
  height: 20px;
  padding: 0 6px;
  font-size: 11px;
  background: transparent;
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.sm};
  color: ${({ theme }) => theme.colors.text.muted};
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.fast};
  flex-shrink: 0;
  margin-left: 2px;

  &:hover {
    background: ${({ theme }) => theme.colors.bg.surfaceHover};
    color: ${({ theme }) => theme.colors.text.primary};
    border-color: ${({ theme }) => theme.colors.border.strong};
  }

  &:disabled {
    opacity: 0.4;
    cursor: default;
    pointer-events: none;
  }
`;

const SegmentBody = styled.p`
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
  color: ${({ theme }) => theme.colors.text.secondary};
`;

function draftRowKey(d: DraftNote): string {
  return d._id;
}

function displayNameFromEmail(email: string): string {
  const local = email.split('@')[0] || email;
  return local.replace(/[._-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function fallbackVersion(versionId: number): Version {
  return {
    type: 'Version',
    id: versionId,
    name: `Version ${versionId}`,
    notes: [],
  };
}

const RegisterFlushContext = createContext<
  (fn: () => Promise<void>) => () => void
>(() => () => {});

interface PublishNoteRowProps {
  playlistId: number;
  version: Version;
  draftOwnerEmail: string;
  rowDraft: DraftNote;
  selected: boolean;
  onSelectedChange: (checked: boolean) => void;
  qcLoading: boolean;
  qcRowRefreshing: boolean;
  qcResults: NoteQCResult[];
  qcIgnored: Set<string>;
  onQcToggleIgnore: (checkId: string) => void;
  onQcRefreshDraft: () => Promise<void>;
  /** Only true when the version carries more than one note. */
  showOwner: boolean;
}

function PublishNoteRow({
  playlistId,
  version,
  draftOwnerEmail,
  rowDraft,
  selected,
  onSelectedChange,
  qcLoading,
  qcRowRefreshing,
  qcResults,
  qcIgnored,
  onQcToggleIgnore,
  onQcRefreshDraft,
  showOwner,
}: PublishNoteRowProps) {
  const { noteQcEnabled } = useFeatureFlags();
  const registerFlush = useContext(RegisterFlushContext);
  const [fixOpen, setFixOpen] = useState(false);
  const [fixResult, setFixResult] = useState<NoteQCResult | null>(null);
  const draftKey = draftRowKey(rowDraft);

  const currentVersionAsSearchResult: SearchResult = useMemo(
    () => ({
      type: 'Version',
      id: version.id,
      name: version.name || `Version ${version.id}`,
    }),
    [version.id, version.name]
  );

  const versionSubmitter: SearchResult | undefined = useMemo(() => {
    if (!version.user) return undefined;
    return {
      type: 'User',
      id: version.user.id,
      name: version.user.name || '',
    };
  }, [version.user]);

  const { draftNote, updateDraftNote, saveAttachmentIds, flushDebouncedSave } =
    useDraftNote({
      playlistId,
      versionId: version.id,
      userEmail: draftOwnerEmail,
      currentVersion: currentVersionAsSearchResult,
      submitter: versionSubmitter,
    });

  useEffect(() => {
    return registerFlush(flushDebouncedSave);
  }, [registerFlush, flushDebouncedSave]);

  const title = displayNameFromEmail(draftOwnerEmail);

  const draftForModal = draftNote ?? backendToLocal(rowDraft);

  const handleQcApply = async (patch: Partial<LocalDraftNote>) => {
    updateDraftNote(patch);
    void (async () => {
      try {
        await flushDebouncedSave();
        await onQcRefreshDraft();
      } catch {
        /* best-effort; refreshingDraftKey clears in hook finally */
      }
    })();
  };

  const handleNoteContentBlur = useCallback(() => {
    void (async () => {
      try {
        await flushDebouncedSave();
        await onQcRefreshDraft();
      } catch {
        /* best-effort */
      }
    })();
  }, [flushDebouncedSave, onQcRefreshDraft]);

  return (
    <NoteRowBlock $excluded={!selected}>
      {noteQcEnabled && (
        <NoteQCDiffModal
          open={fixOpen}
          onOpenChange={(o) => {
            setFixOpen(o);
            if (!o) setFixResult(null);
          }}
          draft={draftForModal}
          qcResult={fixResult}
          onApply={handleQcApply}
        />
      )}
      <NoteRowMeta>
        <Checkbox
          checked={selected}
          onCheckedChange={(c) => onSelectedChange(c === true)}
        />
        {/* One note-taker is the norm here, so naming them on every row is
            noise. It only earns its place when a version has more than one
            note and the rows would otherwise be indistinguishable. */}
        {showOwner && (
          <Text size="1" color="gray" truncate style={{ maxWidth: 110 }}>
            {title}
          </Text>
        )}
        {noteQcEnabled && (
          <NoteQCResultPill
            draftKey={draftKey}
            results={qcResults}
            loading={qcLoading || qcRowRefreshing}
            ignored={qcIgnored}
            onToggleIgnore={(checkId) => onQcToggleIgnore(checkId)}
            onFix={(r) => {
              setFixResult(r);
              setFixOpen(true);
            }}
            localDraft={draftForModal}
            onFixAll={handleQcApply}
          />
        )}
      </NoteRowMeta>
      <BigThumb>
        {version.thumbnail ? <img src={version.thumbnail} alt="" /> : null}
      </BigThumb>
      <NoteRowEditor>
        <NoteEditor
          projectId={version.project?.id ?? null}
          currentVersion={version}
          draftNote={draftNote}
          updateDraftNote={updateDraftNote}
          saveAttachmentIds={saveAttachmentIds}
          variant="embedded"
          onNoteContentBlur={handleNoteContentBlur}
          readOnly={!selected}
        />
      </NoteRowEditor>
    </NoteRowBlock>
  );
}

interface PublishGridRowProps {
  playlistId: number;
  version: Version;
  draftOwnerEmail: string;
  rowDraft: DraftNote;
  selected: boolean;
  onSelectedChange: (checked: boolean) => void;
}

function PublishGridRow({
  playlistId,
  version,
  draftOwnerEmail,
  rowDraft,
  selected,
  onSelectedChange,
}: PublishGridRowProps) {
  const registerFlush = useContext(RegisterFlushContext);

  const currentVersionAsSearchResult: SearchResult = useMemo(
    () => ({
      type: 'Version',
      id: version.id,
      name: version.name || `Version ${version.id}`,
    }),
    [version.id, version.name]
  );

  const versionSubmitter: SearchResult | undefined = useMemo(() => {
    if (!version.user) return undefined;
    return { type: 'User', id: version.user.id, name: version.user.name || '' };
  }, [version.user]);

  const { draftNote, updateDraftNote, flushDebouncedSave } = useDraftNote({
    playlistId,
    versionId: version.id,
    userEmail: draftOwnerEmail,
    currentVersion: currentVersionAsSearchResult,
    submitter: versionSubmitter,
  });

  useEffect(() => {
    return registerFlush(flushDebouncedSave);
  }, [registerFlush, flushDebouncedSave]);

  const draft = draftNote ?? backendToLocal(rowDraft);
  // Same rule as the sidebar's letters and the card view's badges.
  const status = noteStatus({
    published: draft.published,
    publishedNoteId: draft.publishedNoteId,
    content: draft.content,
    subject: draft.subject,
    origin: draft.origin,
  });

  return (
    <GridRow $selected={selected}>
      <GridCell>
        <Checkbox
          checked={selected}
          onCheckedChange={(c) => onSelectedChange(c === true)}
        />
      </GridCell>
      <GridVersionCell title={version.name || `Version ${version.id}`}>
        <GridThumb>
          {version.thumbnail && <img src={version.thumbnail} alt="" />}
        </GridThumb>
        {/* The site's JTS number (Version.sg_jts, surfaced as external_ref).
            Sites without that field configured fall back to the name. */}
        <span>
          {version.external_ref || version.name || `Version ${version.id}`}
        </span>
        {/* A new note is the norm and needs no marking. `E`/`P` mean this row
            already has an upstream note, so publishing will overwrite it rather
            than create one — the case worth catching before the button. */}
        {status && status !== 'draft' && (
          <GridStatusDot $status={status} title={noteStatusLabel(status)}>
            {noteStatusLetter(status)}
          </GridStatusDot>
        )}
      </GridVersionCell>
      <GridCell>{version.user?.name ?? '—'}</GridCell>
      <GridCell style={{ paddingTop: 0 }}>
        <GridNoteInput
          value={draft.content ?? ''}
          disabled={!selected}
          placeholder={
            selected
              ? 'Empty — nothing will be sent for this row'
              : 'Not publishing'
          }
          onChange={(e) => updateDraftNote({ content: e.target.value })}
          onBlur={() => void flushDebouncedSave()}
        />
      </GridCell>
    </GridRow>
  );
}

function formatSegmentTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '';
  }
}

function VersionTranscriptRow({
  playlistId,
  versionId,
  checked,
  onCheckedChange,
}: {
  playlistId: number;
  versionId: number;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  const { transcriptionEnabled, transcriptPublishEnabled } = useFeatureFlags();
  const { segments, isLoading } = useSegments({ playlistId, versionId });
  const [expanded, setExpanded] = useState(false);
  const segmentsCount = segments.length;
  const speakerCount = useMemo(
    () => new Set(segments.map((s) => s.speaker).filter(Boolean)).size,
    [segments]
  );

  // Transcription being on only means segments exist; pushing them upstream is a
  // separate opt-in that needs the backend flag and a provisioned SG entity.
  if (!transcriptionEnabled || !transcriptPublishEnabled) return null;

  return (
    <>
      <TranscriptRow>
        <Flex align="center" gap="2">
          <Checkbox
            checked={segmentsCount > 0 && checked}
            disabled={isLoading || segmentsCount === 0}
            onCheckedChange={(c) => onCheckedChange(c === true)}
          />
          <Text
            size="2"
            weight="medium"
            color={isLoading || segmentsCount === 0 ? 'gray' : undefined}
          >
            Transcript
          </Text>
          <Text size="1" color="gray">
            {isLoading
              ? '…'
              : segmentsCount === 0
                ? 'None recorded'
                : `${speakerCount} speaker${speakerCount !== 1 ? 's' : ''}`}
          </Text>
          {(isLoading || segmentsCount > 0) && (
            <ToggleTranscriptButton
              disabled={isLoading}
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? 'Hide' : 'Show'}
            </ToggleTranscriptButton>
          )}
        </Flex>
      </TranscriptRow>
      {expanded && segmentsCount > 0 && (
        <TranscriptExpanded>
          {segments.map((seg, idx) => {
            const prev = idx > 0 ? segments[idx - 1] : null;
            const showHeader = !prev || prev.speaker !== seg.speaker;
            return (
              <SegmentBlock key={seg.segment_id} $showHeader={showHeader}>
                {showHeader && (
                  <SegmentSpeakerRow>
                    <SegmentSpeaker>{seg.speaker || 'Unknown'}</SegmentSpeaker>
                    <SegmentTimestamp>
                      {formatSegmentTime(seg.absolute_start_time)}
                    </SegmentTimestamp>
                  </SegmentSpeakerRow>
                )}
                <SegmentBody>{seg.text}</SegmentBody>
              </SegmentBlock>
            );
          })}
        </TranscriptExpanded>
      )}
    </>
  );
}

interface VersionPublishCardProps {
  playlistId: number;
  version: Version;
  drafts: DraftNote[];
  currentUserEmail: string;
  selected: Record<string, boolean>;
  onToggle: (key: string, checked: boolean) => void;
  transcriptChecked: boolean;
  onTranscriptToggle: (checked: boolean) => void;
  qcLoading: boolean;
  qcRefreshingDraftKey: string | null;
  qcResults: Record<string, NoteQCResult[]>;
  qcIgnored: Set<string>;
  onQcToggleIgnore: (draftKey: string, checkId: string) => void;
  onQcRefreshDraft: (d: DraftNote) => Promise<void>;
}

function VersionPublishCard({
  playlistId,
  version,
  drafts,
  currentUserEmail,
  selected,
  onToggle,
  transcriptChecked,
  onTranscriptToggle,
  qcLoading,
  qcRefreshingDraftKey,
  qcResults,
  qcIgnored,
  onQcToggleIgnore,
  onQcRefreshDraft,
}: VersionPublishCardProps) {
  // Server rows rather than live drafts: the header is a summary, and the list
  // refreshes on autosave anyway.
  const headerStatus = useMemo<NoteStatus | null>(() => {
    const found = drafts
      .map((d) => noteStatus(noteProvenance(d)))
      .filter((x): x is NoteStatus => x !== null);
    return found.find((x) => x !== 'draft') ?? found[0] ?? null;
  }, [drafts]);

  const sortedDrafts = useMemo(
    () =>
      [...drafts].sort((a, b) => {
        const aMine = a.user_email === currentUserEmail;
        const bMine = b.user_email === currentUserEmail;
        if (aMine !== bMine) return aMine ? -1 : 1;
        return a.user_email.localeCompare(b.user_email);
      }),
    [drafts, currentUserEmail]
  );

  return (
    <VersionCard>
      <VersionCardHeader>
        {/* Version and artist share the line: the version is the heading, the
            artist trails it in muted weight, so one line carries both. */}
        <Flex align="center" gap="2" style={{ flex: 1, minWidth: 0 }}>
          <VersionName>{version.name || `Version ${version.id}`}</VersionName>
          {/* Same rule as the grid: a new note is the norm, so only mark the
              versions where publishing would overwrite an existing SG note. */}
          {headerStatus && headerStatus !== 'draft' && (
            <GridStatusDot
              $status={headerStatus}
              title={noteStatusLabel(headerStatus)}
            >
              {noteStatusLetter(headerStatus)}
            </GridStatusDot>
          )}
          {version.user ? (
            <>
              <HeaderDivider />
              <UserAvatar name={version.user.name} size="1" />
              <ArtistName>{version.user.name}</ArtistName>
            </>
          ) : (
            <>
              <HeaderDivider />
              <ArtistName>Unknown submitter</ArtistName>
            </>
          )}
        </Flex>
      </VersionCardHeader>
      <CardBody>
        {sortedDrafts.map((d) => (
          <PublishNoteRow
            key={draftRowKey(d)}
            playlistId={playlistId}
            version={version}
            draftOwnerEmail={d.user_email}
            rowDraft={d}
            selected={selected[draftRowKey(d)] ?? false}
            onSelectedChange={(c) => onToggle(draftRowKey(d), c)}
            qcLoading={qcLoading}
            qcRowRefreshing={qcRefreshingDraftKey === draftRowKey(d)}
            qcResults={qcResults[draftRowKey(d)] ?? []}
            qcIgnored={qcIgnored}
            onQcToggleIgnore={(checkId) =>
              onQcToggleIgnore(draftRowKey(d), checkId)
            }
            onQcRefreshDraft={() => onQcRefreshDraft(d)}
            showOwner={sortedDrafts.length > 1}
          />
        ))}
        <VersionTranscriptRow
          playlistId={playlistId}
          versionId={version.id}
          checked={transcriptChecked}
          onCheckedChange={onTranscriptToggle}
        />
      </CardBody>
    </VersionCard>
  );
}

export const PublishNotesTabContent: React.FC<PublishNotesTabContentProps> = ({
  open,
  onClose,
  playlistId,
  userEmail,
  notes,
  versions = [],
  onPendingChange,
  showTitle = true,
}) => {
  const { noteQcEnabled, transcriptPublishEnabled } = useFeatureFlags();
  const [emailOpen, setEmailOpen] = useState(false);
  const [viewMode, setViewMode] = useState<'cards' | 'grid'>(() => {
    try {
      return localStorage.getItem(PUBLISH_VIEW_KEY) === 'grid'
        ? 'grid'
        : 'cards';
    } catch {
      // Private windows and blocked site data throw on access; the default is fine.
      return 'cards';
    }
  });

  const changeViewMode = useCallback((mode: 'cards' | 'grid') => {
    setViewMode(mode);
    try {
      localStorage.setItem(PUBLISH_VIEW_KEY, mode);
    } catch {
      /* remembering the choice is a convenience, not a requirement */
    }
  }, []);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [transcriptSelected, setTranscriptSelected] = useState<
    Record<number, boolean>
  >({});
  const [successSummary, setSuccessSummary] = useState<{
    publishedCount: number;
    republishedCount: number;
    failedCount: number;
    imageCount: number;
    statusCount: number;
    transcriptPublishedCount: number;
    transcriptSkippedCount: number;
  } | null>(null);
  const {
    mutateAsync: publishNotes,
    isPending,
    isError,
    error,
    reset,
  } = usePublishNotes();
  const { mutateAsync: publishTranscriptAsync } = usePublishTranscript();

  const {
    results: qcResults,
    loading: qcLoading,
    ignored: qcIgnored,
    toggleIgnore: qcToggleIgnore,
    refreshDraft: qcRefreshDraft,
    hasBlockingErrors: qcHasBlockingErrors,
    refreshingDraftKey: qcRefreshingDraftKey,
  } = useNoteQCChecks({
    open: open && noteQcEnabled,
    playlistId,
    drafts: notes,
  });

  const flushFnsRef = useRef(new Set<() => Promise<void>>());
  const registerFlush = useCallback((fn: () => Promise<void>) => {
    flushFnsRef.current.add(fn);
    return () => {
      flushFnsRef.current.delete(fn);
    };
  }, []);

  const flushAllDrafts = useCallback(async () => {
    await Promise.all([...flushFnsRef.current].map((f) => f()));
  }, []);

  useEffect(() => {
    onPendingChange?.(isPending);
  }, [isPending, onPendingChange]);

  useEffect(() => {
    if (open) {
      reset();
      setSuccessSummary(null);
    }
  }, [open, reset]);

  const notesFingerprint = useMemo(
    () => notes.map(draftRowKey).sort().join('\0'),
    [notes]
  );

  useEffect(() => {
    if (!open) return;
    setSelected((prev) => {
      const next: Record<string, boolean> = {};
      for (const d of notes) {
        const k = draftRowKey(d);
        next[k] = prev[k] ?? true;
      }
      return next;
    });
  }, [open, notesFingerprint, notes]);

  const versionCards = useMemo(() => {
    const byVid = new Map<number, DraftNote[]>();
    for (const d of notes) {
      const arr = byVid.get(d.version_id) ?? [];
      arr.push(d);
      byVid.set(d.version_id, arr);
    }

    const ordered: { version: Version; drafts: DraftNote[] }[] = [];
    const seen = new Set<number>();

    for (const v of versions) {
      const drafts = byVid.get(v.id);
      if (drafts?.length) {
        ordered.push({ version: v, drafts });
        seen.add(v.id);
      }
    }

    for (const [vid, drafts] of byVid) {
      if (!seen.has(vid)) {
        ordered.push({ version: fallbackVersion(vid), drafts });
      }
    }

    return ordered;
  }, [notes, versions]);

  const gridRows = useMemo(
    () =>
      versionCards.flatMap(({ version, drafts }) =>
        [...drafts]
          .sort((a, b) => {
            const aMine = a.user_email === userEmail;
            const bMine = b.user_email === userEmail;
            if (aMine !== bMine) return aMine ? -1 : 1;
            return a.user_email.localeCompare(b.user_email);
          })
          .map((draft) => ({ version, draft }))
      ),
    [versionCards, userEmail]
  );

  useEffect(() => {
    if (!open) return;
    setTranscriptSelected((prev) => {
      const next: Record<number, boolean> = {};
      for (const { version } of versionCards) {
        next[version.id] = prev[version.id] ?? true;
      }
      return next;
    });
  }, [open, versionCards]);

  const selectedCount = useMemo(
    () => notes.filter((d) => selected[draftRowKey(d)]).length,
    [notes, selected]
  );

  const allNotesSelected = useMemo(
    () => notes.length > 0 && notes.every((d) => selected[draftRowKey(d)]),
    [notes, selected]
  );

  const allTranscriptsSelected = useMemo(
    () =>
      versionCards.every(
        ({ version }) => transcriptSelected[version.id] ?? true
      ),
    [versionCards, transcriptSelected]
  );

  const publishBlockedByQc = useMemo(
    () =>
      notes.some(
        (d) => selected[draftRowKey(d)] && qcHasBlockingErrors(draftRowKey(d))
      ),
    [notes, selected, qcHasBlockingErrors]
  );

  const countImages = (notes: DraftNote[]) =>
    notes.reduce((sum, n) => sum + (n.attachment_ids?.length ?? 0), 0);

  const countStatuses = (notes: DraftNote[]) =>
    notes.filter((n) => {
      if (!n.version_status) return false;
      const version = versions.find((v) => v.id === n.version_id);
      return n.version_status !== version?.status;
    }).length;

  const handleBatchSelect = useCallback(
    (mode: 'all' | 'none' | 'mine' | 'others') => {
      setSelected(() => {
        const next: Record<string, boolean> = {};
        for (const d of notes) {
          const k = draftRowKey(d);
          if (mode === 'all') next[k] = true;
          else if (mode === 'none') next[k] = false;
          else if (mode === 'mine') next[k] = d.user_email === userEmail;
          else next[k] = d.user_email !== userEmail;
        }
        return next;
      });
    },
    [notes, userEmail]
  );

  const handleToggle = useCallback((key: string, checked: boolean) => {
    setSelected((prev) => ({ ...prev, [key]: checked }));
  }, []);

  const handleTranscriptToggle = useCallback(
    (versionId: number, checked: boolean) => {
      setTranscriptSelected((prev) => ({ ...prev, [versionId]: checked }));
    },
    []
  );

  const handleBatchTranscriptSelect = useCallback(() => {
    const next: Record<number, boolean> = {};
    for (const { version } of versionCards) {
      next[version.id] = !allTranscriptsSelected;
    }
    setTranscriptSelected(next);
  }, [versionCards, allTranscriptsSelected]);

  const handlePublishSelected = async () => {
    const toPublish = notes.filter((d) => selected[draftRowKey(d)]);
    if (toPublish.length === 0) return;

    await flushAllDrafts();

    const targets = toPublish.map((d) => ({
      user_email: d.user_email,
      version_id: d.version_id,
    }));

    const selectedTranscriptVersionIds = transcriptPublishEnabled
      ? versionCards
          .filter(({ version }) => transcriptSelected[version.id] ?? true)
          .map(({ version }) => version.id)
      : [];

    const [notesResult, transcriptResults] = await Promise.all([
      publishNotes({ playlistId, request: { user_email: userEmail, targets } }),
      Promise.allSettled(
        selectedTranscriptVersionIds.map((versionId) =>
          publishTranscriptAsync({
            playlistId,
            request: { version_id: versionId },
          })
        )
      ),
    ]);

    const transcriptPublishedCount = transcriptResults.filter(
      (r) =>
        r.status === 'fulfilled' &&
        (r.value.outcome === 'created' || r.value.outcome === 'updated')
    ).length;
    const transcriptSkippedCount = transcriptResults.filter(
      (r) => r.status === 'fulfilled' && r.value.outcome === 'skipped'
    ).length;

    setSuccessSummary({
      publishedCount: notesResult.published_count,
      republishedCount: notesResult.republished_count,
      failedCount: notesResult.failed_count,
      imageCount: countImages(toPublish),
      statusCount: countStatuses(toPublish),
      transcriptPublishedCount,
      transcriptSkippedCount,
    });
  };

  const handleClose = () => {
    onClose();
  };

  return (
    <RegisterFlushContext.Provider value={registerFlush}>
      {successSummary ? (
        <Flex direction="column" gap="4" p="4">
          {showTitle && (
            <Dialog.Title style={{ margin: 0 }}>Publish Notes</Dialog.Title>
          )}
          <Callout.Root color="green">
            <Callout.Icon>
              <Info size={16} />
            </Callout.Icon>
            <Callout.Text>Publishing Complete!</Callout.Text>
          </Callout.Root>

          <SummaryBox>
            <Text weight="bold" size="2">
              Results:
            </Text>
            <ResultList>
              {successSummary.publishedCount > 0 && (
                <li>Notes Published: {successSummary.publishedCount}</li>
              )}
              {successSummary.republishedCount > 0 && (
                <li>Notes Republished: {successSummary.republishedCount}</li>
              )}
              {successSummary.imageCount > 0 && (
                <li>Images Attached: {successSummary.imageCount}</li>
              )}
              {successSummary.statusCount > 0 && (
                <li>Statuses Updated: {successSummary.statusCount}</li>
              )}
              {successSummary.transcriptPublishedCount > 0 && (
                <li>
                  Transcripts Published:{' '}
                  {successSummary.transcriptPublishedCount}
                </li>
              )}
              {successSummary.transcriptSkippedCount > 0 && (
                <li>
                  Transcripts Up to Date:{' '}
                  {successSummary.transcriptSkippedCount}
                </li>
              )}
              {successSummary.failedCount > 0 && (
                <li>Notes Failed: {successSummary.failedCount}</li>
              )}
            </ResultList>
          </SummaryBox>

          <Flex justify="end" mt="4">
            <Dialog.Close>
              <Button onClick={handleClose}>Close</Button>
            </Dialog.Close>
          </Flex>
        </Flex>
      ) : (
        <>
          <Flex
            align="center"
            justify={showTitle ? 'between' : 'end'}
            gap="3"
            p="4"
            style={{
              borderBottom: '1px solid var(--gray-a6)',
              flexShrink: 0,
            }}
          >
            {showTitle && (
              <Dialog.Title style={{ margin: 0 }}>Publish Notes</Dialog.Title>
            )}
            <Flex align="center" gap="2">
              <ViewToggle>
                <ViewToggleButton
                  type="button"
                  $active={viewMode === 'cards'}
                  onClick={() => changeViewMode('cards')}
                >
                  Cards
                </ViewToggleButton>
                <ViewToggleButton
                  type="button"
                  $active={viewMode === 'grid'}
                  onClick={() => changeViewMode('grid')}
                >
                  Grid
                </ViewToggleButton>
              </ViewToggle>
              <DropdownMenu.Root>
                <DropdownMenu.Trigger>
                  <IconButton
                    variant="ghost"
                    color="gray"
                    aria-label="Batch note selection"
                    disabled={notes.length === 0}
                  >
                    <MoreVertical size={18} />
                  </IconButton>
                </DropdownMenu.Trigger>
                <DropdownMenu.Content align="end">
                  <DropdownMenu.Item
                    onSelect={() =>
                      handleBatchSelect(allNotesSelected ? 'none' : 'all')
                    }
                  >
                    {allNotesSelected
                      ? 'Deselect all notes'
                      : 'Select all notes'}
                  </DropdownMenu.Item>
                  <DropdownMenu.Item onSelect={() => handleBatchSelect('mine')}>
                    Select only my notes
                  </DropdownMenu.Item>
                  <DropdownMenu.Item
                    onSelect={() => handleBatchSelect('others')}
                  >
                    Select only notes from others
                  </DropdownMenu.Item>
                  {transcriptPublishEnabled && (
                    <>
                      <DropdownMenu.Separator />
                      <DropdownMenu.Item onSelect={handleBatchTranscriptSelect}>
                        {allTranscriptsSelected
                          ? 'Deselect all transcripts'
                          : 'Select all transcripts'}
                      </DropdownMenu.Item>
                    </>
                  )}
                </DropdownMenu.Content>
              </DropdownMenu.Root>
            </Flex>
          </Flex>

          <ScrollBody>
            {notes.length === 0 ? (
              <Text size="2" color="gray">
                No notes to publish.
              </Text>
            ) : viewMode === 'grid' ? (
              <GridWrap>
                <GridHeader>
                  <span />
                  <span>JTS</span>
                  <span>Artist</span>
                  <span>Note going to ShotGrid</span>
                </GridHeader>
                {gridRows.map(({ version, draft }) => (
                  <PublishGridRow
                    key={draftRowKey(draft)}
                    playlistId={playlistId}
                    version={version}
                    draftOwnerEmail={draft.user_email}
                    rowDraft={draft}
                    selected={selected[draftRowKey(draft)] ?? false}
                    onSelectedChange={(c) =>
                      handleToggle(draftRowKey(draft), c)
                    }
                  />
                ))}
              </GridWrap>
            ) : (
              versionCards.map(({ version, drafts }) => (
                <VersionPublishCard
                  key={version.id}
                  playlistId={playlistId}
                  version={version}
                  drafts={drafts}
                  currentUserEmail={userEmail}
                  selected={selected}
                  onToggle={handleToggle}
                  transcriptChecked={transcriptSelected[version.id] ?? true}
                  onTranscriptToggle={(checked) =>
                    handleTranscriptToggle(version.id, checked)
                  }
                  qcLoading={qcLoading}
                  qcRefreshingDraftKey={qcRefreshingDraftKey}
                  qcResults={qcResults}
                  qcIgnored={qcIgnored}
                  onQcToggleIgnore={qcToggleIgnore}
                  onQcRefreshDraft={qcRefreshDraft}
                />
              ))
            )}
          </ScrollBody>

          {isError && (
            <Flex px="4" pb="2">
              <Callout.Root color="red" style={{ width: '100%' }}>
                <Callout.Icon>
                  <Info size={16} />
                </Callout.Icon>
                <Callout.Text>
                  {error?.message || 'Failed to publish notes'}
                </Callout.Text>
              </Callout.Root>
            </Flex>
          )}

          <FooterBar>
            <Flex justify="between" align="center" gap="3">
              <Button
                variant="soft"
                onClick={() => setEmailOpen(true)}
                disabled={isPending}
              >
                Email
              </Button>
              <Flex gap="3">
                <Dialog.Close>
                  <Button variant="soft" color="gray" disabled={isPending}>
                    Cancel
                  </Button>
                </Dialog.Close>
                <Button
                  disabled={
                    isPending ||
                    notes.length === 0 ||
                    selectedCount === 0 ||
                    publishBlockedByQc
                  }
                  onClick={() => void handlePublishSelected()}
                >
                  {isPending && <SpinnerIcon size={14} />}
                  {isPending
                    ? 'Publishing...'
                    : `Publish selected${selectedCount > 0 ? ` (${selectedCount})` : ''}`}
                </Button>
              </Flex>
            </Flex>
          </FooterBar>
          <EmailNotesDialog
            open={emailOpen}
            onClose={() => setEmailOpen(false)}
            playlistId={playlistId}
            userEmail={userEmail}
          />
        </>
      )}
    </RegisterFlushContext.Provider>
  );
};

export const PublishNotesDialog: React.FC<PublishNotesDialogProps> = ({
  open,
  onClose,
  playlistId,
  userEmail,
  notes,
  versions = [],
}) => {
  const [isPending, setIsPending] = useState(false);

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(isOpen) => !isOpen && !isPending && onClose()}
    >
      <Dialog.Content
        maxWidth="900px"
        style={{
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          padding: 0,
        }}
      >
        <Dialog.Description style={{ display: 'none' }}>
          Review and publish draft notes to production tracking.
        </Dialog.Description>
        <PublishNotesTabContent
          open={open}
          onClose={onClose}
          playlistId={playlistId}
          userEmail={userEmail}
          notes={notes}
          versions={versions}
          onPendingChange={setIsPending}
          showTitle
        />
      </Dialog.Content>
    </Dialog.Root>
  );
};
