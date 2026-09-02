import { useState } from 'react';
import styled from 'styled-components';
import { Pencil, X } from 'lucide-react';
import { SearchResult } from '@dna/core';
import { useFeatureFlags } from '../contexts/FeatureFlagsContext';
import {
  ADDRESSING_FIELDS_ENABLED,
  useNoteOptionsVisible,
} from './noteOptions';
import { EntitySearchInput } from './EntitySearchInput';
import { EntityPill, type EntityType } from './EntityPill/EntityPill';

interface NoteOptionsInlineProps {
  /** Selected users for To field */
  toValue?: SearchResult[];
  /** Selected users for CC field */
  ccValue?: SearchResult[];
  /** Subject line (text) */
  subjectValue?: string;
  /** Selected entities for Links field */
  linksValue?: SearchResult[];
  /** Project ID for scoping entity search */
  projectId?: number;
  /** Current version to auto-add to links (non-removable) */
  currentVersion?: SearchResult;
  /** Version submitter shown as locked (non-removable) To recipient */
  lockedTo?: SearchResult[];
  onToChange?: (value: SearchResult[]) => void;
  onCcChange?: (value: SearchResult[]) => void;
  onSubjectChange?: (value: string) => void;
  onLinksChange?: (value: SearchResult[]) => void;
}

const Wrapper = styled.div`
  display: flex;
  flex-direction: column;
  gap: 12px;
`;

const DisplayRow = styled.div`
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
`;

const OptionChip = styled.div`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  min-height: 28px;
  font-size: 12px;
  font-family: ${({ theme }) => theme.fonts.sans};
  background: ${({ theme }) => theme.colors.bg.base};
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.sm};
`;

const ChipLabel = styled.span`
  color: ${({ theme }) => theme.colors.text.muted};
`;

const ChipValue = styled.span`
  color: ${({ theme }) => theme.colors.text.primary};
  font-weight: 500;
`;

const EmptyValue = styled.span`
  color: ${({ theme }) => theme.colors.text.muted};
`;

const EditButton = styled.button`
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: transparent;
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.sm};
  color: ${({ theme }) => theme.colors.text.muted};
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.fast};
  flex-shrink: 0;

  &:hover {
    background: ${({ theme }) => theme.colors.bg.surfaceHover};
    color: ${({ theme }) => theme.colors.text.primary};
    border-color: ${({ theme }) => theme.colors.border.strong};
  }
`;

const EditForm = styled.div`
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  background: ${({ theme }) => theme.colors.bg.base};
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.md};
`;

const EditHeader = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
`;

const EditTitle = styled.span`
  font-size: 13px;
  font-weight: 500;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.secondary};
`;

const CloseButton = styled.button`
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

const FieldRow = styled.div`
  display: flex;
  gap: 12px;
`;

const FieldGroup = styled.div<{ $flex?: number }>`
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: ${({ $flex }) => $flex ?? 1};
`;

const FieldLabel = styled.label<{ $required?: boolean; $hasError?: boolean }>`
  font-size: 11px;
  font-weight: 500;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ $hasError, theme }) =>
    $hasError ? theme.colors.status.error : theme.colors.text.muted};
  text-transform: uppercase;
  letter-spacing: 0.5px;

  ${({ $required }) =>
    $required &&
    `
    &::after {
      content: ' *';
      color: inherit;
    }
  `}
`;

const RequiredIndicator = styled.span`
  font-size: 10px;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.status.error};
  margin-left: 4px;
  font-weight: 500;
`;

const TextInput = styled.input`
  padding: 8px 10px;
  font-size: 13px;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.primary};
  background: ${({ theme }) => theme.colors.bg.surface};
  border: 1px solid ${({ theme }) => theme.colors.border.subtle};
  border-radius: ${({ theme }) => theme.radii.sm};
  outline: none;
  transition: all ${({ theme }) => theme.transitions.fast};

  &::placeholder {
    color: ${({ theme }) => theme.colors.text.muted};
  }

  &:focus {
    border-color: ${({ theme }) => theme.colors.accent.main};
    box-shadow: 0 0 0 2px ${({ theme }) => theme.colors.accent.subtle};
  }
`;

/* The whole options panel collapses to this when Subject is all that is left. */
const SubjectRow = styled.label`
  display: flex;
  align-items: center;
  gap: 8px;
`;

const SubjectLabel = styled.span`
  font-size: 12px;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.muted};
  flex-shrink: 0;
`;

const SubjectInput = styled(TextInput)`
  flex: 1;
  min-width: 0;
`;

const PillsDisplay = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
`;

export function NoteOptionsInline({
  toValue = [],
  ccValue = [],
  subjectValue = '',
  linksValue = [],
  projectId,
  currentVersion,
  lockedTo = [],
  onToChange,
  onCcChange,
  onSubjectChange,
  onLinksChange,
}: NoteOptionsInlineProps) {
  const { noteLinksEnabled, noteSubjectEnabled } = useFeatureFlags();
  const visible = useNoteOptionsVisible();
  const [isEditing, setIsEditing] = useState(false);

  const otherFields = ADDRESSING_FIELDS_ENABLED || noteLinksEnabled;

  // Everything is off: render nothing rather than an empty bar above the body.
  if (!visible) return null;

  // Subject alone doesn't earn the chip row and the "Note Options" form behind
  // the pencil — that is two clicks to reach one text field. Edit it in place.
  // The panel returns as soon as a second field does, since there is then more
  // than one thing for it to hold.
  if (!otherFields) {
    return (
      <SubjectRow>
        <SubjectLabel>Subject</SubjectLabel>
        <SubjectInput
          type="text"
          placeholder="Optional — titles the note in ShotGrid"
          value={subjectValue}
          onChange={(e) => onSubjectChange?.(e.target.value)}
        />
      </SubjectRow>
    );
  }

  if (isEditing) {
    return (
      <Wrapper>
        <EditForm>
          <EditHeader>
            <EditTitle>Note Options</EditTitle>
            <CloseButton onClick={() => setIsEditing(false)}>
              <X size={14} />
            </CloseButton>
          </EditHeader>

          {ADDRESSING_FIELDS_ENABLED && (
            <>
              <FieldRow>
                <FieldGroup>
                  <FieldLabel
                    $required
                    $hasError={lockedTo.length === 0 && toValue.length === 0}
                  >
                    To
                  </FieldLabel>
                  <EntitySearchInput
                    entityTypes={['user']}
                    projectId={projectId}
                    value={toValue}
                    onChange={(entities) => onToChange?.(entities)}
                    placeholder="Search users..."
                    lockedEntities={lockedTo}
                  />
                </FieldGroup>
              </FieldRow>

              <FieldRow>
                <FieldGroup>
                  <FieldLabel>CC</FieldLabel>
                  <EntitySearchInput
                    entityTypes={['user']}
                    projectId={projectId}
                    value={ccValue}
                    onChange={(entities) => onCcChange?.(entities)}
                    placeholder="Search users..."
                  />
                </FieldGroup>
              </FieldRow>
            </>
          )}

          {noteSubjectEnabled && (
            <FieldRow>
              <FieldGroup>
                <FieldLabel>Subject</FieldLabel>
                <TextInput
                  type="text"
                  placeholder="Subject..."
                  value={subjectValue}
                  onChange={(e) => onSubjectChange?.(e.target.value)}
                />
              </FieldGroup>
            </FieldRow>
          )}

          {noteLinksEnabled && (
            <FieldRow>
              <FieldGroup>
                <FieldLabel>Links</FieldLabel>
                <EntitySearchInput
                  entityTypes={['shot', 'asset', 'task', 'version']}
                  projectId={projectId}
                  value={linksValue}
                  onChange={(entities) => onLinksChange?.(entities)}
                  placeholder="Search shots, assets, tasks..."
                  lockedEntities={currentVersion ? [currentVersion] : []}
                />
              </FieldGroup>
            </FieldRow>
          )}
        </EditForm>
      </Wrapper>
    );
  }

  // Combine locked + editable for display only
  const allTo = [...lockedTo, ...toValue];
  const allLinks = currentVersion
    ? [currentVersion, ...linksValue]
    : linksValue;

  return (
    <Wrapper>
      <DisplayRow>
        {ADDRESSING_FIELDS_ENABLED && (
          <>
            <OptionChip>
              <ChipLabel>To:</ChipLabel>
              {allTo.length > 0 ? (
                <PillsDisplay>
                  {allTo.slice(0, 2).map((entity) => (
                    <EntityPill
                      key={`${entity.type}-${entity.id}`}
                      entity={{
                        type: entity.type.toLowerCase() as EntityType,
                        id: entity.id,
                        name: entity.name,
                      }}
                      size="compact"
                    />
                  ))}
                  {allTo.length > 2 && (
                    <ChipValue>+{allTo.length - 2} more</ChipValue>
                  )}
                </PillsDisplay>
              ) : (
                <>
                  <EmptyValue>—</EmptyValue>
                  <RequiredIndicator>(required)</RequiredIndicator>
                </>
              )}
            </OptionChip>
            <OptionChip>
              <ChipLabel>CC:</ChipLabel>
              {ccValue.length > 0 ? (
                <PillsDisplay>
                  {ccValue.slice(0, 2).map((entity) => (
                    <EntityPill
                      key={`${entity.type}-${entity.id}`}
                      entity={{
                        type: entity.type.toLowerCase() as EntityType,
                        id: entity.id,
                        name: entity.name,
                      }}
                      size="compact"
                    />
                  ))}
                  {ccValue.length > 2 && (
                    <ChipValue>+{ccValue.length - 2} more</ChipValue>
                  )}
                </PillsDisplay>
              ) : (
                <EmptyValue>—</EmptyValue>
              )}
            </OptionChip>
          </>
        )}
        {noteSubjectEnabled && (
          <OptionChip>
            <ChipLabel>Subject:</ChipLabel>
            {subjectValue ? (
              <ChipValue>{subjectValue}</ChipValue>
            ) : (
              <EmptyValue>—</EmptyValue>
            )}
          </OptionChip>
        )}
        {noteLinksEnabled && (
          <OptionChip>
            <ChipLabel>Links:</ChipLabel>
            {allLinks.length > 0 ? (
              <PillsDisplay>
                {allLinks.slice(0, 2).map((entity) => (
                  <EntityPill
                    key={`${entity.type}-${entity.id}`}
                    entity={{
                      type: entity.type.toLowerCase() as EntityType,
                      id: entity.id,
                      name: entity.name,
                    }}
                    size="compact"
                  />
                ))}
                {allLinks.length > 2 && (
                  <ChipValue>+{allLinks.length - 2} more</ChipValue>
                )}
              </PillsDisplay>
            ) : (
              <EmptyValue>—</EmptyValue>
            )}
          </OptionChip>
        )}
        <EditButton
          onClick={() => setIsEditing(true)}
          title="Edit note options"
        >
          <Pencil size={14} />
        </EditButton>
      </DisplayRow>
    </Wrapper>
  );
}
