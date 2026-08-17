import { useState } from 'react';
import styled from 'styled-components';
import { Popover, Tooltip } from '@radix-ui/themes';
import { ChevronDown, Radio, RotateCw } from 'lucide-react';
import { useFollowAlongContext } from '../contexts';

const TriggerButton = styled.button<{ $following: boolean }>`
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  font-size: 14px;
  font-weight: 500;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme, $following }) =>
    $following ? theme.colors.text.primary : theme.colors.text.secondary};
  background: ${({ theme, $following }) =>
    $following ? theme.colors.accent.subtle : 'transparent'};
  border: 1px solid
    ${({ theme, $following }) =>
      $following ? theme.colors.accent.main : theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.md};
  cursor: pointer;
  max-width: 220px;
  transition: all ${({ theme }) => theme.transitions.fast};

  &:hover {
    background: ${({ theme, $following }) =>
      $following ? theme.colors.accent.subtle : theme.colors.bg.surfaceHover};
    color: ${({ theme }) => theme.colors.text.primary};
    border-color: ${({ theme, $following }) =>
      $following ? theme.colors.accent.hover : theme.colors.border.strong};
  }
`;

const TriggerLabel = styled.span`
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const StatusDot = styled.div<{ $connected: boolean; $following: boolean }>`
  width: 6px;
  height: 6px;
  flex-shrink: 0;
  border-radius: 50%;
  background: ${({ $connected, $following, theme }) => {
    if (!$following) return theme.colors.text.muted;
    return $connected
      ? theme.colors.status.success
      : theme.colors.status.warning;
  }};
`;

const MenuHeader = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-bottom: 8px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: ${({ theme }) => theme.colors.text.muted};
`;

const RefreshButton = styled.button`
  display: flex;
  align-items: center;
  padding: 2px;
  color: ${({ theme }) => theme.colors.text.muted};
  background: transparent;
  border: none;
  border-radius: ${({ theme }) => theme.radii.sm};
  cursor: pointer;

  &:hover {
    color: ${({ theme }) => theme.colors.text.primary};
  }
`;

const SessionList = styled.div`
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 260px;
  overflow-y: auto;
`;

const SessionButton = styled.button<{ $selected: boolean }>`
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 6px 8px;
  font-size: 13px;
  font-family: ${({ theme }) => theme.fonts.sans};
  text-align: left;
  color: ${({ theme }) => theme.colors.text.primary};
  background: ${({ theme, $selected }) =>
    $selected ? theme.colors.accent.subtle : 'transparent'};
  border: none;
  border-radius: ${({ theme }) => theme.radii.sm};
  cursor: pointer;

  &:hover {
    background: ${({ theme }) => theme.colors.bg.surfaceHover};
  }
`;

// The name is what a session is picked by, so it keeps its width and the
// viewer list gives way. A busy session can list a dozen people, which is far
// wider than this menu.
const SessionName = styled.span`
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const SessionUsers = styled.span`
  flex: 1 1 0;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: right;
  font-size: 12px;
  color: ${({ theme }) => theme.colors.text.muted};
`;

const Message = styled.p`
  margin: 0;
  padding: 4px 0;
  font-size: 12px;
  color: ${({ theme }) => theme.colors.text.muted};
`;

const ManualEntry = styled.form`
  display: flex;
  gap: 6px;
  padding-top: 8px;
  margin-top: 8px;
  border-top: 1px solid ${({ theme }) => theme.colors.border.subtle};
`;

const ManualInput = styled.input`
  flex: 1;
  min-width: 0;
  padding: 6px 8px;
  font-size: 13px;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.primary};
  background: ${({ theme }) => theme.colors.bg.base};
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.sm};

  &:focus {
    outline: none;
    border-color: ${({ theme }) => theme.colors.accent.main};
  }
`;

const StopButton = styled.button`
  width: 100%;
  margin-top: 8px;
  padding: 6px 8px;
  font-size: 13px;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.secondary};
  background: transparent;
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.sm};
  cursor: pointer;

  &:hover {
    color: ${({ theme }) => theme.colors.text.primary};
    border-color: ${({ theme }) => theme.colors.border.strong};
  }
`;

export function FollowAlongMenu() {
  const {
    available,
    hasSessionDirectory,
    connected,
    sessions,
    sessionsLoading,
    sessionsError,
    refreshSessions,
    session,
    setSession,
    focus,
    show,
  } = useFollowAlongContext();
  const [open, setOpen] = useState(false);
  const [manualSession, setManualSession] = useState('');

  if (!available) {
    return null;
  }

  const following = !!session;
  const tooltip = following
    ? connected
      ? `Following ${session}${focus?.shot ? ` — ${focus.shot}` : ''}`
      : `Connecting to ${session}...`
    : 'Follow a live review session';

  const choose = (name: string | null) => {
    setSession(name);
    setOpen(false);
  };

  return (
    <Popover.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          refreshSessions();
        }
      }}
    >
      <Tooltip content={tooltip}>
        <Popover.Trigger>
          <TriggerButton type="button" $following={following}>
            <StatusDot $connected={connected} $following={following} />
            <Radio size={14} />
            <TriggerLabel>{session ?? 'Follow'}</TriggerLabel>
            <ChevronDown size={14} />
          </TriggerButton>
        </Popover.Trigger>
      </Tooltip>
      <Popover.Content size="1" style={{ width: 260 }}>
        <MenuHeader>
          Review sessions
          <RefreshButton
            type="button"
            onClick={refreshSessions}
            title="Refresh session list"
          >
            <RotateCw size={12} />
          </RefreshButton>
        </MenuHeader>

        {sessionsLoading && <Message>Loading sessions...</Message>}

        {!sessionsLoading && sessionsError && (
          <Message>
            Could not reach the session directory. Type a session name below.
          </Message>
        )}

        {!sessionsLoading && !sessionsError && sessions.length === 0 && (
          <Message>
            {!hasSessionDirectory
              ? 'No session directory configured. Type a session name below.'
              : show
                ? `No active sessions for ${show}.`
                : 'No show selected.'}
          </Message>
        )}

        {sessions.length > 0 && (
          <SessionList>
            {sessions.map((reviewSession) => (
              <SessionButton
                key={reviewSession.id || reviewSession.name}
                type="button"
                $selected={reviewSession.name === session}
                onClick={() => choose(reviewSession.name)}
              >
                <SessionName>{reviewSession.name}</SessionName>
                {reviewSession.users.length > 0 &&
                  (() => {
                    // One person can hold several connections to a session, so
                    // the raw list repeats them.
                    const names = [
                      ...new Set(
                        reviewSession.users
                          .map((user) => user.username)
                          .filter(Boolean)
                      ),
                    ];
                    const label =
                      names.join(', ') ||
                      `${reviewSession.users.length} watching`;
                    return <SessionUsers title={label}>{label}</SessionUsers>;
                  })()}
              </SessionButton>
            ))}
          </SessionList>
        )}

        <ManualEntry
          onSubmit={(event) => {
            event.preventDefault();
            if (manualSession.trim()) {
              choose(manualSession.trim());
              setManualSession('');
            }
          }}
        >
          <ManualInput
            value={manualSession}
            onChange={(event) => setManualSession(event.target.value)}
            placeholder="Session name"
            aria-label="Session name"
          />
          <StopButton type="submit" style={{ width: 'auto', marginTop: 0 }}>
            Follow
          </StopButton>
        </ManualEntry>

        {following && (
          <StopButton type="button" onClick={() => choose(null)}>
            Stop following
          </StopButton>
        )}
      </Popover.Content>
    </Popover.Root>
  );
}
