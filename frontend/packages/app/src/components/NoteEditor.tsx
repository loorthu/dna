import {
  forwardRef,
  useImperativeHandle,
  useMemo,
  useState,
  useRef,
  useCallback,
  useEffect,
} from 'react';
import styled from 'styled-components';
import { X, Image, ImageOff } from 'lucide-react';
import { SearchResult, Version } from '@dna/core';
import { NoteOptionsInline } from './NoteOptionsInline';
import { useNoteOptionsVisible } from './noteOptions';
import { MarkdownEditor } from './MarkdownEditor';
import { MentionIndexProvider } from '../contexts/MentionIndexContext';
import type { LocalDraftNote } from '../hooks';
import { noteStatus } from './noteStatus';
import { apiHandler } from '../api';

export interface StagedAttachment {
  id: string;
  file?: File;
  previewUrl: string;
  backendId?: string;
  broken?: boolean;
}

interface NoteEditorProps {
  projectId?: number | null;
  currentVersion?: Version | null;
  draftNote: LocalDraftNote | null;
  updateDraftNote: (updates: Partial<LocalDraftNote>) => void;
  saveAttachmentIds: (ids: string[]) => Promise<void>;
  variant?: 'default' | 'embedded';
  /** Publish dialog: run after note body editor loses focus (e.g. refresh QC). */
  onNoteContentBlur?: () => void;
  /** Override the initial editor height (pixels). Defaults to DEFAULT_HEIGHT. */
  defaultHeight?: number;
  /** Show the note but refuse edits — used for rows excluded from a publish. */
  readOnly?: boolean;
}

export interface NoteEditorHandle {
  appendContent: (content: string) => void;
}

const DEFAULT_HEIGHT = 140;
// Sized against the 240px 16:9 thumbnail (135px) this sits beside in the publish
// dialog's card view: this box carries the toolbar too, and the drag handle and
// row padding add ~20px, so ~116 lands the row level with the frame. A one-line
// note next to a big thumbnail looked broken at half the height.
const EMBEDDED_MIN_HEIGHT = 116;
// Embedded rows grow with their content instead of reserving a fixed box, up to
// this cap — past it a single long note would crowd out every other row.
const EMBEDDED_MAX_HEIGHT = 320;
const MIN_HEIGHT = 60;

const EditorWrapper = styled.div<{
  $height: number;
  $isDragOver: boolean;
  $embedded?: boolean;
}>`
  position: relative;
  display: flex;
  flex-direction: column;
  gap: ${({ $embedded }) => ($embedded ? '8px' : '16px')};
  padding: ${({ $embedded }) => ($embedded ? '0' : '20px 20px 8px')};
  background: ${({ theme }) => theme.colors.bg.surface};
  border: ${({ $embedded, $isDragOver, theme }) =>
    $embedded
      ? 'none'
      : `1px solid ${
          $isDragOver ? theme.colors.accent.main : theme.colors.border.subtle
        }`};
  box-shadow: ${({ $embedded, $isDragOver, theme }) =>
    $embedded && $isDragOver
      ? `inset 0 0 0 2px ${theme.colors.accent.main}`
      : 'none'};
  border-radius: ${({ theme }) => theme.radii.lg};
  transition:
    border-color ${({ theme }) => theme.transitions.fast},
    box-shadow ${({ theme }) => theme.transitions.fast};
`;

const EditorContent = styled.div<{ $height: number; $auto?: boolean }>`
  display: flex;
  flex-direction: column;
  /* Embedded rows size to their note: a one-line note should not reserve the
     same box as a twenty-line one when a dialog stacks dozens of them. */
  height: ${({ $auto, $height }) => ($auto ? 'auto' : `${$height}px`)};
  min-height: ${({ $auto }) => ($auto ? EMBEDDED_MIN_HEIGHT : MIN_HEIGHT)}px;
  ${({ $auto }) =>
    $auto ? `max-height: ${EMBEDDED_MAX_HEIGHT}px; overflow-y: auto;` : ''}
`;

const EditorHeader = styled.div`
  display: flex;
  flex-direction: column;
  gap: 12px;
`;

const TitleRow = styled.div`
  display: flex;
  align-items: center;
`;

const EditorTitle = styled.h2`
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.primary};
  flex-shrink: 0;
`;

const StatusBadge = styled.div<{
  $isWarning?: boolean;
  $isDraft?: boolean;
  $compact?: boolean;
}>`
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  background-color: ${({ theme, $isWarning, $isDraft }) => {
    const color = $isDraft
      ? theme.colors.status.info
      : $isWarning
        ? theme.colors.status.warning
        : theme.colors.status.success;
    return color + '20';
  }};
  color: ${({ theme, $isWarning, $isDraft }) =>
    $isDraft
      ? theme.colors.status.info
      : $isWarning
        ? theme.colors.status.warning
        : theme.colors.status.success};
  margin-left: ${({ $compact }) => ($compact ? '0' : '12px')};
`;

const InlineBadgeWrap = styled.div`
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  flex-shrink: 0;
`;

export type NoteDraftStatusFields = Pick<
  LocalDraftNote,
  'published' | 'publishedNoteId' | 'content' | 'subject' | 'origin'
>;

export function NoteDraftStatusBadges({
  draft,
  layout = 'title',
}: {
  draft: NoteDraftStatusFields | null;
  layout?: 'title' | 'inline';
}) {
  // Same rule as the sidebar's letters, deliberately: a note is published, edited or a draft in
  // one place only, and the two used to disagree about ShotGrid's seeded notes.
  const status = noteStatus(draft);
  if (!status) return null;

  const compact = layout === 'inline';

  const badges = (
    <>
      {status === 'published' && (
        <StatusBadge $compact={compact}>Published</StatusBadge>
      )}
      {status === 'edited' && (
        <StatusBadge $isWarning $compact={compact}>
          Published (Edited)
        </StatusBadge>
      )}
      {status === 'draft' && (
        <StatusBadge $isDraft $compact={compact}>
          Draft
        </StatusBadge>
      )}
    </>
  );

  if (layout === 'inline') {
    return <InlineBadgeWrap>{badges}</InlineBadgeWrap>;
  }

  return <>{badges}</>;
}

const DropOverlay = styled.div`
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: ${({ theme }) => theme.colors.accent.subtle};
  display: flex;
  align-items: center;
  justify-content: center;
  color: ${({ theme }) => theme.colors.accent.main};
  z-index: 1;
`;

const AttachmentTray = styled.div`
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  background: ${({ theme }) => theme.colors.bg.base};
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.md};
`;

const AttachmentTrayHeader = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
`;

const AttachmentTrayTitle = styled.span`
  font-size: 13px;
  font-weight: 500;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.secondary};
`;

const AttachmentTrayClose = styled.button`
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: transparent;
  border: none;
  color: ${({ theme }) => theme.colors.text.muted};
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.fast};

  &:hover {
    color: ${({ theme }) => theme.colors.text.primary};
  }
`;

const ThumbnailGrid = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
`;

const ThumbnailBox = styled.div`
  position: relative;
  width: 72px;
  height: 72px;
  border-radius: ${({ theme }) => theme.radii.md};
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  box-shadow: ${({ theme }) => theme.shadows.sm};
  overflow: visible;
  flex-shrink: 0;

  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    border-radius: inherit;
    display: block;
  }
`;

const BrokenThumbnail = styled.div`
  width: 100%;
  height: 100%;
  border-radius: inherit;
  background: ${({ theme }) => theme.colors.bg.surfaceHover};
  display: flex;
  align-items: center;
  justify-content: center;
  color: ${({ theme }) => theme.colors.text.muted};
`;

const RemoveButton = styled.button`
  position: absolute;
  top: -6px;
  right: -6px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: ${({ theme }) => theme.colors.bg.overlay};
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  color: ${({ theme }) => theme.colors.text.secondary};
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  padding: 0;
  transition: all ${({ theme }) => theme.transitions.fast};

  &:hover {
    background: ${({ theme }) => theme.colors.bg.surfaceHover};
    color: ${({ theme }) => theme.colors.text.primary};
    border-color: ${({ theme }) => theme.colors.border.strong};
  }
`;

const ResizeHandle = styled.div`
  display: flex;
  align-items: center;
  justify-content: center;
  height: 12px;
  cursor: ns-resize;
  flex-shrink: 0;
  border-radius: 0 0 ${({ theme }) => theme.radii.lg}
    ${({ theme }) => theme.radii.lg};
  color: ${({ theme }) => theme.colors.border.default};
  transition: color ${({ theme }) => theme.transitions.fast};

  &:hover {
    color: ${({ theme }) => theme.colors.border.strong};
  }

  &::before {
    content: '';
    display: block;
    width: 32px;
    height: 3px;
    border-radius: 2px;
    background: currentColor;
  }
`;

export const NoteEditor = forwardRef<NoteEditorHandle, NoteEditorProps>(
  function NoteEditor(
    {
      projectId,
      currentVersion,
      draftNote,
      updateDraftNote,
      saveAttachmentIds,
      variant = 'default',
      onNoteContentBlur,
      defaultHeight,
      readOnly = false,
    },
    ref
  ) {
    const isEmbedded = variant === 'embedded';
    const optionsVisible = useNoteOptionsVisible();
    // Embedded hides the title row, so with the options row empty too the
    // header would be a bare flex box contributing only its gap.
    const showHeader = !isEmbedded || optionsVisible;

    const currentVersionAsSearchResult: SearchResult | undefined =
      useMemo(() => {
        if (!currentVersion) return undefined;
        return {
          type: 'Version',
          id: currentVersion.id,
          name: currentVersion.name || `Version ${currentVersion.id}`,
        };
      }, [currentVersion]);

    const versionSubmitter: SearchResult | undefined = useMemo(() => {
      if (!currentVersion?.user) return undefined;
      return {
        type: 'User',
        id: currentVersion.user.id,
        name: currentVersion.user.name || '',
      };
    }, [currentVersion?.user]);

    const [editorHeight, setEditorHeight] = useState(
      defaultHeight ?? DEFAULT_HEIGHT
    );
    const [isResized, setIsResized] = useState(false);
    // Measured so a drag starts from the auto-fitted size, not from a default
    // the reader never saw.
    const contentRef = useRef<HTMLDivElement>(null);

    // Embedded rows start fitted to their note, then pin to whatever the reader
    // drags them to — same handle as the standalone editor, just a better
    // starting size than one fixed box per row.
    const autoHeight = isEmbedded && defaultHeight == null && !isResized;
    const [attachments, setAttachments] = useState<StagedAttachment[]>([]);
    const [isAttachmentTrayOpen, setIsAttachmentTrayOpen] = useState(false);
    const [attachFlashKey, setAttachFlashKey] = useState(0);
    const [animatePill, setAnimatePill] = useState(false);
    const [isDragOver, setIsDragOver] = useState(false);

    const attachmentsRef = useRef<StagedAttachment[]>([]);
    const attachmentsByVersion = useRef<
      Map<number | null | undefined, StagedAttachment[]>
    >(new Map());
    const versionIdRef = useRef(currentVersion?.id);

    useEffect(() => {
      versionIdRef.current = currentVersion?.id;
      const saved = attachmentsByVersion.current.get(currentVersion?.id) ?? [];
      attachmentsRef.current = saved;
      setAttachments(saved);
      setIsAttachmentTrayOpen(false);
      setAnimatePill(false);
    }, [currentVersion?.id]);

    useEffect(() => {
      if (attachments.length === 0) setIsAttachmentTrayOpen(false);
    }, [attachments.length]);

    const attachmentIdsKey = draftNote?.attachmentIds?.join(',') ?? '';
    useEffect(() => {
      const serverIds = draftNote?.attachmentIds ?? [];
      if (!serverIds.length) return;
      const existingBackendIds = new Set(
        attachmentsRef.current.map((a) => a.backendId).filter(Boolean)
      );
      const newIds = serverIds.filter((id) => !existingBackendIds.has(id));
      if (!newIds.length) return;

      let cancelled = false;
      const blobUrls: string[] = [];

      void (async () => {
        const results = await Promise.allSettled(
          newIds.map(async (id) => {
            const previewUrl = await apiHandler.getAttachmentBlobUrl(id);
            blobUrls.push(previewUrl);
            return { id, previewUrl, backendId: id } as StagedAttachment;
          })
        );

        if (cancelled) {
          blobUrls.forEach((u) => URL.revokeObjectURL(u));
          return;
        }

        const entries: StagedAttachment[] = results.map((result, i) =>
          result.status === 'fulfilled'
            ? result.value
            : ({
                id: newIds[i],
                previewUrl: '',
                backendId: newIds[i],
                broken: true,
              } as StagedAttachment)
        );

        const next = [...attachmentsRef.current, ...entries];
        attachmentsRef.current = next;
        attachmentsByVersion.current.set(versionIdRef.current, next);
        setAttachments(next);
        setIsAttachmentTrayOpen(true);
      })();

      return () => {
        cancelled = true;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [attachmentIdsKey, currentVersion?.id]);

    const handleAttach = useCallback(
      async (file: File) => {
        const previewUrl = URL.createObjectURL(file);
        const localId = crypto.randomUUID();
        const staged: StagedAttachment = { id: localId, file, previewUrl };
        const next = [...attachmentsRef.current, staged];
        attachmentsRef.current = next;
        attachmentsByVersion.current.set(versionIdRef.current, next);
        setAttachments(next);
        setAnimatePill(true);
        setAttachFlashKey((k) => k + 1);

        const result = await apiHandler.uploadAttachment(file);

        const updated = attachmentsRef.current.map((a) =>
          a.id === localId ? { ...a, backendId: result.id } : a
        );
        attachmentsRef.current = updated;
        attachmentsByVersion.current.set(versionIdRef.current, updated);
        setAttachments(updated);

        const allBackendIds = updated
          .map((a) => a.backendId)
          .filter((id): id is string => Boolean(id));
        await saveAttachmentIds(allBackendIds);
      },
      [saveAttachmentIds]
    );

    const handleRemoveAttachment = useCallback(
      async (id: string) => {
        const removed = attachmentsRef.current.find((a) => a.id === id);
        if (removed) {
          URL.revokeObjectURL(removed.previewUrl);
          if (removed.backendId) {
            try {
              await apiHandler.deleteAttachment(removed.backendId);
            } catch {
              // File may already be gone (e.g. after publishing) — still remove from UI
            }
          }
        }
        const next = attachmentsRef.current.filter((a) => a.id !== id);
        attachmentsRef.current = next;
        attachmentsByVersion.current.set(versionIdRef.current, next);
        setAttachments(next);

        const allBackendIds = next
          .map((a) => a.backendId)
          .filter((id): id is string => Boolean(id));
        await saveAttachmentIds(allBackendIds);
      },
      [saveAttachmentIds]
    );

    const handleDragOver = useCallback((e: React.DragEvent) => {
      e.preventDefault();
      if (e.dataTransfer.types.includes('Files')) setIsDragOver(true);
    }, []);

    const handleDragLeave = useCallback((e: React.DragEvent) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node))
        setIsDragOver(false);
    }, []);

    const handleDrop = useCallback(
      (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragOver(false);
        Array.from(e.dataTransfer.files)
          .filter((f) => f.type.startsWith('image/'))
          .forEach(handleAttach);
      },
      [handleAttach]
    );

    const handlePaste = useCallback(
      (e: React.ClipboardEvent) => {
        const images = Array.from(e.clipboardData.items)
          .filter((item) => item.type.startsWith('image/'))
          .map((item) => item.getAsFile())
          .filter((f): f is File => f !== null);
        if (images.length === 0) return;
        e.preventDefault();
        images.forEach(handleAttach);
      },
      [handleAttach]
    );

    // Revoke all object URLs on unmount
    useEffect(() => {
      const byVersion = attachmentsByVersion.current;
      return () => {
        byVersion.forEach((list) =>
          list.forEach((a) => URL.revokeObjectURL(a.previewUrl))
        );
      };
    }, []);

    const dragStartY = useRef<number>(0);
    const dragStartHeight = useRef<number>(DEFAULT_HEIGHT);

    const handleResizeMouseDown = useCallback(
      (e: React.MouseEvent) => {
        e.preventDefault();
        dragStartY.current = e.clientY;
        // Taking the drag off the auto-fitted box means pinning a height, and
        // the height it must pin is the one on screen. Seeding state from the
        // measurement is what stops the first press jumping to DEFAULT_HEIGHT,
        // which the reader never saw.
        const measured = contentRef.current?.offsetHeight ?? editorHeight;
        dragStartHeight.current = measured;
        setEditorHeight(measured);
        setIsResized(true);

        const floor = isEmbedded ? EMBEDDED_MIN_HEIGHT : MIN_HEIGHT;
        const onMouseMove = (moveEvent: MouseEvent) => {
          const delta = moveEvent.clientY - dragStartY.current;
          const newHeight = Math.max(floor, dragStartHeight.current + delta);
          setEditorHeight(newHeight);
        };

        const onMouseUp = () => {
          document.removeEventListener('mousemove', onMouseMove);
          document.removeEventListener('mouseup', onMouseUp);
          document.body.style.cursor = '';
          document.body.style.userSelect = '';
        };

        document.body.style.cursor = 'ns-resize';
        document.body.style.userSelect = 'none';
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
      },
      [editorHeight, isEmbedded]
    );

    useImperativeHandle(
      ref,
      () => ({
        appendContent: (content: string) => {
          const currentContent = draftNote?.content ?? '';
          const separator = currentContent.trim() ? '\n\n---\n\n' : '';
          updateDraftNote({ content: currentContent + separator + content });
        },
      }),
      [draftNote?.content, updateDraftNote]
    );

    const handleFieldChange = useCallback(
      <K extends keyof NonNullable<typeof draftNote>>(
        key: K,
        value: NonNullable<typeof draftNote>[K]
      ) => {
        updateDraftNote({ [key]: value });
      },
      [updateDraftNote]
    );

    // The submitter is stored in draftNote.to but shown as a locked (non-removable)
    // entity. Filter it from the editable portion and re-add it on save.
    const editableTo = useMemo(() => {
      return (draftNote?.to ?? []).filter(
        (u) =>
          !(
            versionSubmitter &&
            u.id === versionSubmitter.id &&
            u.type === versionSubmitter.type
          )
      );
    }, [draftNote?.to, versionSubmitter]);

    // The current version is stored in draftNote.links but displayed separately
    // as a locked (non-removable) entity. Filter it from the editable portion to
    // avoid showing it twice, and re-add it whenever links are saved.
    const editableLinks = useMemo(() => {
      return (draftNote?.links ?? []).filter(
        (l) =>
          !(
            currentVersionAsSearchResult &&
            l.id === currentVersionAsSearchResult.id &&
            l.type === currentVersionAsSearchResult.type
          )
      );
    }, [draftNote?.links, currentVersionAsSearchResult]);

    // When a @mention is inserted in the editor, sync it to the properties panel.
    // Users → CC field; everything else → Links field. Duplicates are skipped.
    const handleMentionInsert = useCallback(
      (entity: SearchResult) => {
        if (entity.type.toLowerCase() === 'user') {
          const currentCc = draftNote?.cc ?? [];
          if (
            !currentCc.some((e) => e.id === entity.id && e.type === entity.type)
          ) {
            handleFieldChange('cc', [...currentCc, entity]);
          }
        } else {
          const fullLinks = draftNote?.links ?? [];
          if (
            !fullLinks.some((e) => e.id === entity.id && e.type === entity.type)
          ) {
            handleFieldChange('links', [...fullLinks, entity]);
          }
        }
      },
      [draftNote?.cc, draftNote?.links, handleFieldChange]
    );

    return (
      <MentionIndexProvider projectId={projectId ?? null}>
        <EditorWrapper
          $height={editorHeight}
          $isDragOver={isDragOver}
          $embedded={isEmbedded}
          onDragOver={readOnly ? undefined : handleDragOver}
          onDragLeave={readOnly ? undefined : handleDragLeave}
          onDrop={readOnly ? undefined : handleDrop}
          onPaste={readOnly ? undefined : handlePaste}
        >
          {isDragOver && (
            <DropOverlay>
              <Image size={32} />
            </DropOverlay>
          )}
          {showHeader && (
            <EditorHeader>
              {!isEmbedded && (
                <TitleRow>
                  <EditorTitle>Notes</EditorTitle>
                  <NoteDraftStatusBadges draft={draftNote} layout="title" />
                </TitleRow>
              )}
              <NoteOptionsInline
                toValue={editableTo}
                ccValue={draftNote?.cc ?? []}
                subjectValue={draftNote?.subject ?? ''}
                linksValue={editableLinks}
                projectId={projectId ?? undefined}
                currentVersion={currentVersionAsSearchResult}
                lockedTo={versionSubmitter ? [versionSubmitter] : []}
                onToChange={(v) => {
                  const to = versionSubmitter ? [versionSubmitter, ...v] : v;
                  handleFieldChange('to', to);
                }}
                onCcChange={(v) => handleFieldChange('cc', v)}
                onSubjectChange={(v) => handleFieldChange('subject', v)}
                onLinksChange={(v) => {
                  const links = currentVersionAsSearchResult
                    ? [currentVersionAsSearchResult, ...v]
                    : v;
                  handleFieldChange('links', links);
                }}
              />
            </EditorHeader>
          )}

          <EditorContent
            ref={contentRef}
            $height={editorHeight}
            $auto={autoHeight}
          >
            <MarkdownEditor
              value={draftNote?.content ?? ''}
              onChange={(v) => handleFieldChange('content', v)}
              onContentBlur={onNoteContentBlur}
              onAttach={handleAttach}
              attachmentCount={attachments.length}
              attachmentFlashKey={attachFlashKey}
              animatePill={animatePill}
              onToggleAttachmentTray={() => setIsAttachmentTrayOpen((o) => !o)}
              placeholder="Write your notes here... (supports **markdown**, type @ to mention)"
              minHeight={autoHeight ? EMBEDDED_MIN_HEIGHT : MIN_HEIGHT}
              readOnly={readOnly}
              projectId={projectId}
              onMentionInsert={handleMentionInsert}
            />
          </EditorContent>

          {isAttachmentTrayOpen && (
            <AttachmentTray>
              <AttachmentTrayHeader>
                <AttachmentTrayTitle>Images</AttachmentTrayTitle>
                <AttachmentTrayClose
                  onClick={() => setIsAttachmentTrayOpen(false)}
                >
                  <X size={14} />
                </AttachmentTrayClose>
              </AttachmentTrayHeader>
              <ThumbnailGrid>
                {attachments.map((a) => {
                  const displayName = a.file?.name ?? a.backendId ?? '';
                  return (
                    <ThumbnailBox key={a.id}>
                      {a.broken ? (
                        <BrokenThumbnail title="Image unavailable (re-upload to restore)">
                          <ImageOff size={20} />
                        </BrokenThumbnail>
                      ) : (
                        <img
                          src={a.previewUrl}
                          alt={displayName}
                          title={displayName}
                        />
                      )}
                      <RemoveButton
                        onClick={() => handleRemoveAttachment(a.id)}
                        title="Remove attachment"
                      >
                        <X size={10} />
                      </RemoveButton>
                    </ThumbnailBox>
                  );
                })}
              </ThumbnailGrid>
            </AttachmentTray>
          )}

          {!readOnly && (
            <ResizeHandle
              onMouseDown={handleResizeMouseDown}
              title="Drag to resize"
            />
          )}
        </EditorWrapper>
      </MentionIndexProvider>
    );
  }
);
