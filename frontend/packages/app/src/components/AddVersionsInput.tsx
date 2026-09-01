import { useEffect, useMemo, useRef, useState } from 'react';
import styled from 'styled-components';
import { Plus, X } from 'lucide-react';
import { Tooltip } from '@radix-ui/themes';
import { useToast } from '../contexts';
import {
  useAddVersionsToPlaylist,
  parseJtsNumbers,
  summariseAddOutcomes,
} from '../hooks';

interface AddVersionsInputProps {
  playlistId: number | null;
  /** Tells the title row to stand aside while the pill is open, as the search does. */
  onExpandedChange?: (isExpanded: boolean) => void;
}

// Same pill as the version search it sits beside, and for the same reason: this is a small,
// one-line question asked of the list below, and a modal over the whole app to ask it made adding
// a version feel heavier than reading the review it is being added to.
const Container = styled.div<{ $isOpen: boolean }>`
  position: relative;
  display: flex;
  align-items: center;
  flex: ${({ $isOpen }) => ($isOpen ? 1 : 'none')};
  min-width: 0;
`;

const PillContainer = styled.div<{ $isOpen: boolean }>`
  display: flex;
  align-items: center;
  height: 32px;
  padding: 0 4px 0 12px;
  border-radius: 16px;
  border: 1px solid ${({ theme }) => theme.colors.accent.main};
  background: ${({ theme }) => theme.colors.bg.surface};
  box-shadow: 0 0 0 2px ${({ theme }) => theme.colors.accent.glow};
  width: ${({ $isOpen }) => ($isOpen ? '100%' : '0')};
  opacity: ${({ $isOpen }) => ($isOpen ? 1 : 0)};
  overflow: hidden;
  transition:
    width 300ms cubic-bezier(0.34, 1.56, 0.64, 1),
    opacity 200ms ease-out,
    box-shadow ${({ theme }) => theme.transitions.base};
  pointer-events: ${({ $isOpen }) => ($isOpen ? 'auto' : 'none')};

  &:focus-within {
    box-shadow: 0 0 0 3px ${({ theme }) => theme.colors.accent.glow};
  }
`;

const StyledInput = styled.input`
  flex: 1;
  min-width: 0;
  height: 100%;
  padding: 0;
  border: none;
  background: transparent;
  color: ${({ theme }) => theme.colors.text.primary};
  font-family: ${({ theme }) => theme.fonts.sans};
  font-size: 13px;
  outline: none;

  &::placeholder {
    color: ${({ theme }) => theme.colors.text.muted};
  }
`;

// How many numbers were read out of what is in the box, in the same slot the search puts its
// match count. A paste is unreadable at a glance, and this is the only thing standing between
// someone and adding a column they did not mean to.
const ParsedCounter = styled.span`
  font-size: 11px;
  font-family: ${({ theme }) => theme.fonts.mono};
  color: ${({ theme }) => theme.colors.text.muted};
  white-space: nowrap;
  padding: 0 4px;
  flex-shrink: 0;
`;

const IconButton = styled.button`
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: none;
  background: transparent;
  color: ${({ theme }) => theme.colors.accent.main};
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.base};
  flex-shrink: 0;

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.colors.accent.subtle};
    transform: scale(1.1);
  }

  &:active:not(:disabled) {
    transform: scale(0.95);
  }

  &:disabled {
    opacity: 0.4;
    cursor: default;
  }

  svg {
    width: 18px;
    height: 18px;
  }
`;

// Matches the Reload Playlist button it stands beside — same height, weight and border — so the
// two read as one row of things you can do to the playlist, rather than a button and an icon.
const TriggerButton = styled.button`
  display: flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  font-size: 14px;
  font-weight: 500;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.secondary};
  background: transparent;
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.md};
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.fast};
  white-space: nowrap;
  flex-shrink: 0;

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.colors.bg.surfaceHover};
    color: ${({ theme }) => theme.colors.text.primary};
    border-color: ${({ theme }) => theme.colors.border.strong};
  }

  &:active:not(:disabled) {
    background: ${({ theme }) => theme.colors.bg.overlay};
    transform: translateY(1px);
  }

  &:disabled {
    opacity: 0.5;
    // A disabled button swallows its own pointer events, tooltip included, so the wrapper below
    // is what the cursor actually meets.
    pointer-events: none;
  }

  svg {
    width: 16px;
    height: 16px;
  }
`;

/** Hover target for the disabled trigger's tooltip — the button itself cannot be one. */
const DisabledTriggerWrapper = styled.span`
  display: inline-flex;
  cursor: not-allowed;
`;

// The button says what it does; the tooltip is where the how — a JTS number, and that a whole
// pasted list of them is fine — actually lives.
const HOW_TO = 'Paste a JTS number, or a whole list of them';

export function AddVersionsInput({
  playlistId,
  onExpandedChange,
}: AddVersionsInputProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [pasted, setPasted] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const { showToast } = useToast();
  const { mutateAsync, isPending } = useAddVersionsToPlaylist();

  const jts = useMemo(() => parseJtsNumbers(pasted), [pasted]);

  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 150);
    }
  }, [isOpen]);

  useEffect(() => {
    onExpandedChange?.(isOpen);
  }, [isOpen, onExpandedChange]);

  if (!playlistId) {
    return (
      <Tooltip content="Open a playlist first">
        <DisabledTriggerWrapper>
          <TriggerButton disabled>
            <Plus />
            Add Version
          </TriggerButton>
        </DisabledTriggerWrapper>
      </Tooltip>
    );
  }

  const close = () => {
    setIsOpen(false);
    setPasted('');
  };

  const handleAdd = async () => {
    if (!jts.length || isPending) {
      return;
    }
    try {
      const result = await mutateAsync({ playlistId, jts });
      showToast(summariseAddOutcomes(result.outcomes));
      // Numbers that found nothing stay in the box, and the box stays open: those are the ones
      // to check against the turnover sheet, and the toast has already gone by the time anyone
      // has looked them up. Everything landed means there is nothing left to do here.
      const unresolved = result.outcomes
        .filter((o) => o.status === 'not_found')
        .map((o) => o.jts);
      if (unresolved.length) {
        setPasted(unresolved.join(', '));
        inputRef.current?.focus();
      } else {
        close();
      }
    } catch (error) {
      const detail = (
        error as { response?: { data?: { detail?: unknown } } } | undefined
      )?.response?.data?.detail;
      showToast({
        title: 'Could not add versions',
        // The backend refuses for reasons a person can act on and says so in FastAPI's `detail`;
        // axios throws that away in `message`, leaving only a status code.
        description:
          typeof detail === 'string' && detail
            ? detail
            : (error as Error)?.message || 'The request failed.',
        type: 'error',
      });
    }
  };

  return (
    <Container $isOpen={isOpen}>
      {!isOpen && (
        <Tooltip content={HOW_TO}>
          <TriggerButton onClick={() => setIsOpen(true)}>
            <Plus />
            Add Version
          </TriggerButton>
        </Tooltip>
      )}
      {/* Kept mounted so it can animate open, and kept out of the accessibility tree and the
          tab order while it is shut -- a zero-width field is not something to land on. */}
      <PillContainer $isOpen={isOpen} aria-hidden={!isOpen}>
        <StyledInput
          ref={inputRef}
          tabIndex={isOpen ? 0 : -1}
          aria-label="JTS numbers"
          placeholder="Paste JTS numbers, e.g. 1786, 1787"
          value={pasted}
          disabled={isPending}
          onChange={(e) => setPasted(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              close();
            } else if (e.key === 'Enter') {
              e.preventDefault();
              void handleAdd();
            }
          }}
        />
        {jts.length > 0 && <ParsedCounter>{jts.length}</ParsedCounter>}
        <IconButton
          onClick={() => void handleAdd()}
          disabled={isPending || jts.length === 0}
          tabIndex={isOpen ? 0 : -1}
          aria-label="Add to playlist"
        >
          <Plus />
        </IconButton>
        <IconButton onClick={close} aria-label="Close" tabIndex={-1}>
          <X />
        </IconButton>
      </PillContainer>
    </Container>
  );
}
