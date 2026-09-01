import styled, { css, keyframes, type DefaultTheme } from 'styled-components';
import { Tooltip } from '@radix-ui/themes';
import {
  AlertTriangle,
  ChevronLeft,
  Eye,
  ChevronRight,
  RotateCw,
  Target,
  ChevronDown,
  ExternalLink,
  Users,
} from 'lucide-react';
import { UserAvatar } from './UserAvatar';
import { FollowAlongMenu } from './FollowAlongMenu';
import { useHotkeyConfig } from '../hotkeys';
import { useVersionStatuses } from '../hooks';
import { useFeatureFlags } from '../contexts';

interface VersionHeaderProps {
  shotCode?: string;
  versionNumber?: string;
  submittedBy?: string;
  submittedByImageUrl?: string;
  dateSubmitted?: string;
  versionStatus?: string;
  projectId?: number;
  thumbnailUrl?: string;
  links?: string[];
  onBack?: () => void;
  onNext?: () => void;
  onInReview?: () => void;
  onRefresh?: () => void;
  onSetInReview?: () => void;
  onVersionStatusChange?: (code: string) => void;
  prodtrackDetailUrl?: string | null;
  prodtrackTabUsesExtension?: boolean;
  onSyncProdtrackTab?: () => void | Promise<void>;
  syncProdtrackDisabled?: boolean;
  syncProdtrackTitle?: string;
  /** Address of this shot on the artist review page; absent hides the button. */
  reviewUrl?: string | null;
  canGoBack?: boolean;
  canGoNext?: boolean;
  hasInReview?: boolean;
  isCurrentVersionInReview?: boolean;
  isSettingInReview?: boolean;
  isDiscardingSegments?: boolean;
}

const HeaderWrapper = styled.div`
  display: flex;
  flex-direction: column;
  gap: 16px;
`;

const TopBar = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
`;

const BackButton = styled.button`
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 12px;
  font-size: 14px;
  font-weight: 500;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.secondary};
  background: transparent;
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.md};
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.fast};

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.colors.bg.surfaceHover};
    color: ${({ theme }) => theme.colors.text.primary};
    border-color: ${({ theme }) => theme.colors.border.strong};
  }

  &:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
`;

const TopBarActions = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
`;

const InReviewButton = styled.button`
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  font-size: 14px;
  font-weight: 500;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.secondary};
  background: transparent;
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.md};
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.fast};

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.colors.bg.surfaceHover};
    color: ${({ theme }) => theme.colors.text.primary};
    border-color: ${({ theme }) => theme.colors.border.strong};
  }

  &:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
`;

// Shared by every outlined action in the top bar — the production-tracking tab and the artist
// view. They sit side by side and do the same kind of thing (open this shot somewhere else), so
// one surface keeps them from drifting into two slightly different buttons.
const topBarActionSurface = css`
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  font-size: 14px;
  font-weight: 500;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.secondary};
  background: transparent;
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.md};
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.fast};
  box-sizing: border-box;
`;

const TopBarActionButton = styled.button`
  ${topBarActionSurface}

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.colors.bg.surfaceHover};
    color: ${({ theme }) => theme.colors.text.primary};
    border-color: ${({ theme }) => theme.colors.border.strong};
  }

  &:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
`;

const TopBarActionLink = styled.a`
  ${topBarActionSurface}
  text-decoration: none;

  &:hover {
    background: ${({ theme }) => theme.colors.bg.surfaceHover};
    color: ${({ theme }) => theme.colors.text.primary};
    border-color: ${({ theme }) => theme.colors.border.strong};
  }
`;

const NextVersionButton = styled.button`
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  font-size: 14px;
  font-weight: 500;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: #ffffff;
  background: ${({ theme }) => theme.colors.accent.main};
  border: none;
  border-radius: ${({ theme }) => theme.radii.md};
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.fast};

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.colors.accent.hover};
  }

  &:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
`;

const RefreshButton = styled.button`
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  background: transparent;
  border: 1px dashed ${({ theme }) => theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.md};
  color: ${({ theme }) => theme.colors.text.secondary};
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.fast};

  &:hover {
    background: ${({ theme }) => theme.colors.bg.surfaceHover};
    color: ${({ theme }) => theme.colors.text.primary};
    border-color: ${({ theme }) => theme.colors.border.strong};
  }
`;

const MainContent = styled.div`
  display: flex;
  gap: 24px;
`;

const ThumbnailWrapper = styled.div`
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 8px;
  flex-shrink: 0;
  height: 224px;
`;

const Thumbnail = styled.div`
  width: 280px;
  height: 180px;
  background: ${({ theme }) => theme.colors.bg.overlay};
  border-radius: ${({ theme }) => theme.radii.lg};
  flex-shrink: 0;
  overflow: hidden;

  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
`;

/* The fill and the border carry the pulse, not just a halo around it. A glow spreading outside an
   already-amber border on a dark page is the kind of motion peripheral vision misses entirely —
   the whole button brightening is what actually registers while someone is reading notes. */
const warnPulse = keyframes`
  0%, 100% {
    background-color: rgba(245, 158, 11, 0.08);
    border-color: rgba(245, 158, 11, 0.65);
    box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.6);
  }
  50% {
    background-color: rgba(245, 158, 11, 0.34);
    border-color: rgba(245, 158, 11, 1);
    box-shadow: 0 0 0 8px rgba(245, 158, 11, 0);
  }
`;

interface SetInReviewTone {
  fg: string;
  bg: string;
  border: string;
  borderStyle: 'solid' | 'dashed';
}

/* Three states share this button. It is the version in review (accent, settled); a bot is live
   with nothing in review, so the transcript is being thrown away and pressing this is the only
   fix (warning); or it is an ordinary version nobody is reviewing (quiet, dashed). */
function setInReviewTone(
  theme: DefaultTheme,
  isInReview: boolean,
  warn: boolean
): SetInReviewTone {
  if (warn) {
    return {
      fg: theme.colors.status.warning,
      bg: theme.colors.status.warning + '1f',
      border: theme.colors.status.warning,
      borderStyle: 'solid',
    };
  }
  if (isInReview) {
    return {
      fg: theme.colors.accent.main,
      bg: theme.colors.accent.main + '15',
      border: theme.colors.accent.main,
      borderStyle: 'solid',
    };
  }
  return {
    fg: theme.colors.text.secondary,
    bg: 'transparent',
    border: theme.colors.border.default,
    borderStyle: 'dashed',
  };
}

const SetInReviewButton = styled.button<{
  $isInReview?: boolean;
  $warn?: boolean;
}>`
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  /* Padding gives back what the thicker border and the oversized triangle take, so the button
     keeps its height inside the fixed-height thumbnail column and nothing below it shifts. */
  padding: ${({ $warn }) => ($warn ? '6px 11px' : '8px 12px')};
  font-size: 13px;
  font-weight: ${({ $warn }) => ($warn ? 600 : 500)};
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme, $isInReview, $warn }) =>
    setInReviewTone(theme, !!$isInReview, !!$warn).fg};
  background: ${({ theme, $isInReview, $warn }) =>
    setInReviewTone(theme, !!$isInReview, !!$warn).bg};
  border: ${({ $warn }) => ($warn ? '2px' : '1px')}
    ${({ theme, $isInReview, $warn }) =>
      setInReviewTone(theme, !!$isInReview, !!$warn).borderStyle}
    ${({ theme, $isInReview, $warn }) =>
      setInReviewTone(theme, !!$isInReview, !!$warn).border};
  border-radius: ${({ theme }) => theme.radii.md};
  cursor: ${({ $isInReview }) => ($isInReview ? 'default' : 'pointer')};
  transition: all ${({ theme }) => theme.transitions.fast};
  animation: ${({ $warn }) => ($warn ? warnPulse : 'none')} 2s ease-in-out
    infinite;

  /* Someone who has asked the OS for less motion still has a transcript going nowhere. They get
     the loud end of the pulse as a fixed colour rather than nothing at all. */
  @media (prefers-reduced-motion: reduce) {
    animation: none;
    ${({ theme, $warn }) =>
      $warn &&
      css`
        background: ${theme.colors.status.warning}3d;
      `}
  }

  &:hover:not(:disabled) {
    background: ${({ theme, $isInReview, $warn }) =>
      $warn || $isInReview
        ? setInReviewTone(theme, !!$isInReview, !!$warn).bg
        : theme.colors.bg.surfaceHover};
    color: ${({ theme, $isInReview, $warn }) =>
      $warn || $isInReview
        ? setInReviewTone(theme, !!$isInReview, !!$warn).fg
        : theme.colors.text.primary};
    border-color: ${({ theme, $isInReview, $warn }) =>
      $warn || $isInReview
        ? setInReviewTone(theme, !!$isInReview, !!$warn).border
        : theme.colors.border.strong};
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
`;

const MetadataSection = styled.div`
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 12px;
`;

const VersionTitle = styled.h1`
  margin: 0;
  font-size: 28px;
  font-weight: 600;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.primary};
`;

const VersionTitleCode = styled.span`
  color: ${({ theme }) => theme.colors.text.secondary};
`;

const MetadataRow = styled.div`
  display: flex;
  align-items: center;
  gap: 12px;
`;

const MetadataLabel = styled.span`
  font-size: 14px;
  color: ${({ theme }) => theme.colors.text.muted};
  min-width: 110px;
`;

const MetadataValue = styled.span`
  font-size: 14px;
  color: ${({ theme }) => theme.colors.text.primary};
  display: flex;
  align-items: center;
  gap: 8px;
`;

const LinkBadge = styled.span`
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  height: 26px;
  box-sizing: border-box;
  font-size: 12px;
  font-weight: 500;
  line-height: 1;
  color: ${({ theme }) => theme.colors.text.primary};
  background: ${({ theme }) => theme.colors.bg.surface};
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.sm};
`;

const StatusSelectWrapper = styled.div`
  position: relative;
`;

const StatusSelect = styled.select`
  appearance: none;
  padding: 4px 28px 4px 10px;
  height: 26px;
  box-sizing: border-box;
  font-size: 12px;
  font-weight: 500;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.primary};
  background: ${({ theme }) => theme.colors.bg.surface};
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-radius: ${({ theme }) => theme.radii.sm};
  outline: none;
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.fast};

  &:focus {
    border-color: ${({ theme }) => theme.colors.accent.main};
    box-shadow: 0 0 0 2px ${({ theme }) => theme.colors.accent.subtle};
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
`;

const StatusSelectIcon = styled.div`
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  pointer-events: none;
  color: ${({ theme }) => theme.colors.text.muted};
  display: flex;
  align-items: center;
  justify-content: center;
`;

const LinksContainer = styled.div`
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
`;

export function VersionHeader({
  shotCode,
  versionNumber,
  submittedBy,
  submittedByImageUrl,
  dateSubmitted,
  versionStatus,
  projectId,
  thumbnailUrl,
  links = [],
  onBack,
  onNext,
  onInReview,
  onRefresh,
  onSetInReview,
  onVersionStatusChange,
  prodtrackDetailUrl,
  prodtrackTabUsesExtension = false,
  onSyncProdtrackTab,
  syncProdtrackDisabled = false,
  syncProdtrackTitle = 'Open current version in production tracking (browser tab)',
  reviewUrl,
  canGoBack = true,
  canGoNext = true,
  hasInReview = true,
  isCurrentVersionInReview = false,
  isSettingInReview = false,
  isDiscardingSegments = false,
}: VersionHeaderProps) {
  const { getLabel } = useHotkeyConfig();
  const { inReviewEnabled } = useFeatureFlags();
  const { statuses, isLoading: isLoadingStatuses } = useVersionStatuses({
    projectId,
  });
  const displayTitle = shotCode && versionNumber ? `${shotCode} - ` : '';
  const displayCode = versionNumber || shotCode || 'Untitled Version';

  // The bot joins long before anyone starts reviewing shots, and until a version is marked the
  // transcript it produces is dropped on arrival. Saying so here, on the button that fixes it,
  // rather than in the dialog that sends the bot: that dialog is open minutes too early, while
  // the meeting is still small talk and the warning reads as noise.
  const showDiscardWarning = isDiscardingSegments && !isCurrentVersionInReview;
  const setInReviewTooltip = showDiscardWarning
    ? 'A bot is transcribing, but no version is marked In Review — every line is discarded as ' +
      'it arrives. Mark this version to start keeping them; what was already said is not ' +
      'backfilled.'
    : `Set In Review (${getLabel('setInReview')})`;

  return (
    <HeaderWrapper>
      <TopBar>
        <Tooltip content={`Previous Version (${getLabel('previousVersion')})`}>
          <BackButton onClick={onBack} disabled={!canGoBack}>
            <ChevronLeft size={16} />
            Previous Version
          </BackButton>
        </Tooltip>
        <TopBarActions>
          <FollowAlongMenu />
          {inReviewEnabled && (
            <InReviewButton onClick={onInReview} disabled={!hasInReview}>
              <Eye size={14} />
              In Review
            </InReviewButton>
          )}
          {prodtrackDetailUrl &&
            prodtrackTabUsesExtension &&
            onSyncProdtrackTab && (
              <Tooltip content={syncProdtrackTitle}>
                <TopBarActionButton
                  type="button"
                  onClick={() => void onSyncProdtrackTab()}
                  disabled={syncProdtrackDisabled}
                >
                  <ExternalLink size={14} />
                  PT tab
                </TopBarActionButton>
              </Tooltip>
            )}
          {prodtrackDetailUrl && !prodtrackTabUsesExtension && (
            <Tooltip content={syncProdtrackTitle}>
              <TopBarActionLink
                href={prodtrackDetailUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                <ExternalLink size={14} />
                PT tab
              </TopBarActionLink>
            </Tooltip>
          )}
          {reviewUrl && (
            <Tooltip content="Open the artist view of this shot — the notes, transcript and recording as the artist receives them, read-only. Same page the notes email links to.">
              <TopBarActionLink
                href={reviewUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Users size={14} />
                Artist view
              </TopBarActionLink>
            </Tooltip>
          )}
          <Tooltip content={`Next Version (${getLabel('nextVersion')})`}>
            <NextVersionButton onClick={onNext} disabled={!canGoNext}>
              Next Version
              <ChevronRight size={16} />
            </NextVersionButton>
          </Tooltip>
          <RefreshButton onClick={onRefresh} title="Refresh version info">
            <RotateCw size={16} />
          </RefreshButton>
        </TopBarActions>
      </TopBar>
      <MainContent>
        <ThumbnailWrapper>
          <Thumbnail>
            {thumbnailUrl && <img src={thumbnailUrl} alt={displayCode} />}
          </Thumbnail>
          {inReviewEnabled && (
            <Tooltip content={setInReviewTooltip}>
              <SetInReviewButton
                $isInReview={isCurrentVersionInReview}
                $warn={showDiscardWarning}
                aria-label={
                  showDiscardWarning
                    ? 'Set In Review — transcript is not being saved'
                    : undefined
                }
                onClick={onSetInReview}
                disabled={isCurrentVersionInReview || isSettingInReview}
              >
                {isSettingInReview ? (
                  <>Setting...</>
                ) : isCurrentVersionInReview ? (
                  <>
                    <Eye size={14} />
                    In Review
                  </>
                ) : (
                  <>
                    {showDiscardWarning ? (
                      // Deliberately larger than the 14px every other icon here uses. At icon
                      // size it read as decoration next to the label and went unnoticed; at 19
                      // it is the first thing on the button the eye lands on.
                      <AlertTriangle size={19} strokeWidth={2.5} />
                    ) : (
                      <Target size={14} />
                    )}
                    Set In Review
                  </>
                )}
              </SetInReviewButton>
            </Tooltip>
          )}
        </ThumbnailWrapper>
        <MetadataSection>
          <VersionTitle>
            {displayTitle}
            <VersionTitleCode>{displayCode}</VersionTitleCode>
          </VersionTitle>
          <MetadataRow>
            <MetadataLabel>Submitted by:</MetadataLabel>
            <MetadataValue>
              <UserAvatar
                name={submittedBy}
                imageUrl={submittedByImageUrl}
                size="1"
              />
              {submittedBy}
            </MetadataValue>
          </MetadataRow>
          <MetadataRow>
            <MetadataLabel>Date Submitted:</MetadataLabel>
            <MetadataValue>{dateSubmitted}</MetadataValue>
          </MetadataRow>
          <MetadataRow>
            <MetadataLabel>Version Status:</MetadataLabel>
            <MetadataValue>
              <StatusSelectWrapper>
                <StatusSelect
                  value={versionStatus ?? ''}
                  onChange={(e) => onVersionStatusChange?.(e.target.value)}
                  disabled={isLoadingStatuses}
                >
                  {isLoadingStatuses && <option value="">Loading...</option>}
                  {statuses.map((status) => (
                    <option key={status.code} value={status.code}>
                      {status.name}
                    </option>
                  ))}
                </StatusSelect>
                <StatusSelectIcon>
                  <ChevronDown size={12} />
                </StatusSelectIcon>
              </StatusSelectWrapper>
            </MetadataValue>
          </MetadataRow>
          <MetadataRow>
            <MetadataLabel>Links:</MetadataLabel>
            <LinksContainer>
              {links.map((link, index) => (
                <LinkBadge key={index}>{link}</LinkBadge>
              ))}
            </LinksContainer>
          </MetadataRow>
        </MetadataSection>
      </MainContent>
    </HeaderWrapper>
  );
}
