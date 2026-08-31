import styled from 'styled-components';
import { Text, Flex } from '@radix-ui/themes';
import { Check, Loader2, Minus, CircleHelp } from 'lucide-react';
import type {
  ReadinessCheck,
  ReadinessState,
  RecordingReadiness as Readiness,
} from '../hooks/useRecordingReadiness';

/**
 * The two facts that decide whether a meeting has finished landing, as a checklist.
 *
 * Presentational on purpose — it takes a computed `RecordingReadiness` rather than a playlist id,
 * so the same panel can front the Email dialog now and the Publish flow later without either of
 * them owning the rule.
 *
 * Every row is named even when it passes. A gate that only speaks up when it blocks leaves the
 * person who waited wondering what they waited for, and the two checks are not interchangeable:
 * knowing which one is outstanding is the difference between "wait about a minute" and "the
 * meeting is still running".
 */

const Panel = styled.div`
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  background: ${({ theme }) => theme.colors.bg.surfaceHover};
  border-radius: ${({ theme }) => theme.radii.md};
`;

const Row = styled.div`
  display: flex;
  align-items: flex-start;
  gap: 8px;
`;

const Spinner = styled(Loader2)`
  animation: spin 1s linear infinite;
  flex-shrink: 0;
  @keyframes spin {
    from {
      transform: rotate(0deg);
    }
    to {
      transform: rotate(360deg);
    }
  }
`;

const ICON_COLOR: Record<ReadinessState, string> = {
  pass: 'var(--green-9)',
  waiting: 'var(--amber-9)',
  checking: 'var(--gray-8)',
  unknown: 'var(--gray-8)',
  skipped: 'var(--gray-8)',
};

const ICON_STYLE = { marginTop: 3, flexShrink: 0 } as const;

function StateIcon({ state }: { state: ReadinessState }) {
  const color = ICON_COLOR[state];
  if (state === 'waiting' || state === 'checking') {
    return <Spinner size={14} color={color} style={ICON_STYLE} />;
  }
  if (state === 'pass') {
    return <Check size={14} color={color} style={ICON_STYLE} />;
  }
  if (state === 'unknown') {
    return <CircleHelp size={14} color={color} style={ICON_STYLE} />;
  }
  return <Minus size={14} color={color} style={ICON_STYLE} />;
}

function CheckRow({ check }: { check: ReadinessCheck }) {
  const muted = check.state === 'skipped' || check.state === 'unknown';
  return (
    <Row>
      <StateIcon state={check.state} />
      <Flex direction="column">
        <Text size="2" color={muted ? 'gray' : undefined}>
          {check.label}
        </Text>
        <Text size="1" color="gray">
          {check.detail}
        </Text>
      </Flex>
    </Row>
  );
}

export function RecordingReadinessPanel({
  readiness,
}: {
  readiness: Readiness;
}) {
  if (!readiness.applicable) {
    return null;
  }
  return (
    <Panel>
      <Text size="1" weight="medium" color="gray">
        MEETING READINESS
      </Text>
      {readiness.checks.map((check) => (
        <CheckRow key={check.id} check={check} />
      ))}
    </Panel>
  );
}
