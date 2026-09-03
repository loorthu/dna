import { useEffect, useMemo, useRef } from 'react';
import styled from 'styled-components';
import { Spinner } from '@radix-ui/themes';
import type { ReviewPlaylistRef } from '@dna/core';
import { SignInCard } from '../components/ProjectSelector';
import { Logo } from '../components/Logo';
import { useAuth } from '../contexts';
import { useVersionStatuses } from '../hooks';
import { ShotCard } from './ShotCard';
import type { ReviewRoute } from './route';
import { withBase } from '../basePath';
import {
  resolvedPlaylistId,
  useReviewPlaylist,
  useReviewResolution,
} from './useReviewPlaylist';

/**
 * The artist's view of a review: every shot, with the notes, the transcript and the recording.
 *
 * This is the read-only half of DNA. Nothing here writes: no note editor, no status field, no
 * publish, no bot. An artist opening a link from the notes email should be able to read what was
 * said about their work and hear it, and should not be one mis-click from changing a version's
 * status on the show.
 *
 * The whole playlist is one page rather than one shot with a sidebar, because that is the shape
 * the email already put the review in — a numbered list, top to bottom — and because the link the
 * artist followed points at a shot inside it. A page that shows one shot at a time would make
 * "what else was said today" a navigation problem.
 */

const Page = styled.div`
  min-height: 100vh;
  background: ${({ theme }) => theme.colors.bg.base};
  color: ${({ theme }) => theme.colors.text.primary};
  font-family: ${({ theme }) => theme.fonts.sans};
`;

const Header = styled.header`
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 32px;
  background: ${({ theme }) => theme.colors.bg.elevated};
  border-bottom: 1px solid ${({ theme }) => theme.colors.border.subtle};
`;

const Heading = styled.div`
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
`;

const PlaylistName = styled.h1`
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.text.primary};
`;

const Meta = styled.div`
  font-size: 12px;
  color: ${({ theme }) => theme.colors.text.muted};
`;

const Spacer = styled.div`
  flex: 1;
`;

const Viewer = styled.div`
  font-size: 12px;
  color: ${({ theme }) => theme.colors.text.muted};
`;

const Body = styled.main`
  max-width: 980px;
  margin: 0 auto;
  padding: 24px 32px 64px;
  display: flex;
  flex-direction: column;
  gap: 16px;
`;

const Centered = styled.div`
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 80px 32px;
  text-align: center;
  color: ${({ theme }) => theme.colors.text.secondary};
`;

const CenteredTitle = styled.h2`
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.text.primary};
`;

const CenteredText = styled.p`
  margin: 0;
  max-width: 520px;
  font-size: 14px;
  line-height: 1.6;
  color: ${({ theme }) => theme.colors.text.muted};
`;

const ChoiceList = styled.ul`
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  max-width: 520px;
`;

const ChoiceLink = styled.a`
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  border-radius: ${({ theme }) => theme.radii.md};
  background: ${({ theme }) => theme.colors.bg.elevated};
  border: 1px solid ${({ theme }) => theme.colors.border.subtle};
  color: ${({ theme }) => theme.colors.text.primary};
  font-size: 14px;
  text-decoration: none;

  &:hover {
    border-color: ${({ theme }) => theme.colors.accent.main};
  }
`;

const ChoiceMeta = styled.span`
  font-size: 12px;
  color: ${({ theme }) => theme.colors.text.muted};
  white-space: nowrap;
`;

function formatScreened(iso: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      });
}

interface ReviewPageProps {
  route: ReviewRoute;
}

export function ReviewPage({ route }: ReviewPageProps) {
  const { isAuthenticated, isLoading: isAuthLoading, user } = useAuth();

  const resolution = useReviewResolution(isAuthenticated ? route : null);
  const playlistId = resolvedPlaylistId(route, resolution.data);
  const playlist = useReviewPlaylist(isAuthenticated ? playlistId : null);

  const { statuses } = useVersionStatuses({
    projectId: playlist.data?.project_id ?? undefined,
  });
  const statusLabels = useMemo(() => {
    const labels = new Map<string, string>();
    for (const status of statuses) labels.set(status.code, status.name);
    return labels;
  }, [statuses]);

  // Scroll to the linked shot once — and only once. The browser cannot do it for us: the element
  // the fragment names does not exist until the playlist has loaded, by which time the browser
  // has long since given up on the hash. Repeating it would yank the page back every time the
  // reader scrolled away and something re-rendered.
  const scrolledRef = useRef(false);
  useEffect(() => {
    if (scrolledRef.current || !route.anchor || !playlist.data) return;
    const target = document.getElementById(route.anchor);
    if (!target) return;
    scrolledRef.current = true;
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [route.anchor, playlist.data]);

  if (isAuthLoading) {
    return (
      <Page>
        <Centered>
          <Spinner size="3" />
        </Centered>
      </Page>
    );
  }

  if (!isAuthenticated) {
    // The address is left alone, so signing in lands back on the shot that was linked to rather
    // than on the project picker.
    return <SignInCard subtitle="Sign in to read the notes for this review" />;
  }

  if (resolution.isError) {
    return (
      <Message
        title="No such review"
        text={
          route.kind === 'name'
            ? `Nothing in "${route.projectSlug}" is called "${route.playlistSlug}". The playlist may have been renamed or removed, or it may be on a show you do not have access to.`
            : 'That playlist could not be found.'
        }
      />
    );
  }

  if (resolution.data && resolution.data.playlist_id === null) {
    return (
      <Ambiguous
        playlistSlug={route.kind === 'name' ? route.playlistSlug : ''}
        matches={resolution.data.matches}
        anchor={route.anchor}
      />
    );
  }

  if (resolution.isLoading || playlist.isLoading || playlistId === null) {
    return (
      <Page>
        <Centered>
          <Spinner size="3" />
          <CenteredText>Loading the review…</CenteredText>
        </Centered>
      </Page>
    );
  }

  if (playlist.isError || !playlist.data) {
    return (
      <Message
        title="Could not load this review"
        text={playlist.error?.message ?? 'The playlist could not be loaded.'}
      />
    );
  }

  const data = playlist.data;
  const screened = formatScreened(data.screened_at);

  return (
    <Page>
      <Header>
        <Logo width={32} />
        <Heading>
          <PlaylistName>
            {data.playlist_name || `Playlist ${data.playlist_id}`}
          </PlaylistName>
          <Meta>
            {[
              data.project_name || data.project_code,
              screened,
              `${data.shots.length} ${data.shots.length === 1 ? 'shot' : 'shots'}`,
            ]
              .filter(Boolean)
              .join(' · ')}
          </Meta>
        </Heading>
        <Spacer />
        {user?.email && <Viewer>{user.email}</Viewer>}
      </Header>

      <Body>
        {data.shots.length === 0 ? (
          <CenteredText>This playlist has no versions in it.</CenteredText>
        ) : (
          data.shots.map((shot) => (
            <ShotCard
              key={shot.version_id}
              shot={shot}
              recording={data.recording}
              highlighted={shot.anchor === route.anchor}
              statusLabel={statusLabels.get(shot.status) ?? shot.status}
            />
          ))
        )}
      </Body>
    </Page>
  );
}

function Message({ title, text }: { title: string; text: string }) {
  return (
    <Page>
      <Centered>
        <CenteredTitle>{title}</CenteredTitle>
        <CenteredText>{text}</CenteredText>
      </Centered>
    </Page>
  );
}

/**
 * Several playlists answer to one name, so the reader picks.
 *
 * The alternative is guessing, and the newest is the wrong guess for exactly the person this page
 * is for: someone following a link to a review that happened weeks ago. Each choice keeps the
 * fragment, so picking one still lands on the shot the email pointed at.
 */
function Ambiguous({
  playlistSlug,
  matches,
  anchor,
}: {
  playlistSlug: string;
  matches: ReviewPlaylistRef[];
  anchor: string | null;
}) {
  return (
    <Page>
      <Centered>
        <CenteredTitle>Which review did you mean?</CenteredTitle>
        <CenteredText>
          {matches.length} playlists on this show are called &ldquo;
          {matches[0]?.playlist_name || playlistSlug}&rdquo;.
        </CenteredText>
        <ChoiceList>
          {matches.map((match) => (
            <li key={match.playlist_id}>
              {/* The ref's own path, not one rebuilt here: it is deliberately the id form, since
                  the name form is the address that was ambiguous in the first place. */}
              <ChoiceLink
                href={`${withBase(match.url_path)}${anchor ? `#${anchor}` : ''}`}
              >
                <span>{match.playlist_name}</span>
                <ChoiceMeta>
                  {[
                    formatScreened(match.created_at),
                    match.version_count != null
                      ? `${match.version_count} shots`
                      : '',
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </ChoiceMeta>
              </ChoiceLink>
            </li>
          ))}
        </ChoiceList>
      </Centered>
    </Page>
  );
}
