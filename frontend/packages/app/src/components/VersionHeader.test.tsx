import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '../test/render';
import { HotkeysProvider } from '../hotkeys';
import { VersionHeader } from './VersionHeader';
import { apiHandler } from '../api';

beforeEach(() => {
  vi.spyOn(apiHandler, 'getVersionStatuses').mockResolvedValue([]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('VersionHeader', () => {
  it('renders PT tab button when extension sync is enabled', () => {
    const onSync = vi.fn();
    render(
      <HotkeysProvider>
        <VersionHeader
          shotCode="SHOT"
          versionNumber="v001"
          projectId={1}
          prodtrackDetailUrl="https://studio.shotgrid.autodesk.com/detail/Version/1"
          prodtrackTabUsesExtension
          onSyncProdtrackTab={onSync}
          syncProdtrackDisabled={false}
        />
      </HotkeysProvider>
    );
    expect(screen.getByRole('button', { name: /PT tab/i })).toBeInTheDocument();
  });

  it('renders PT tab as a new-tab link when extension sync is off', () => {
    render(
      <HotkeysProvider>
        <VersionHeader
          shotCode="SHOT"
          versionNumber="v001"
          projectId={1}
          prodtrackDetailUrl="https://studio.shotgrid.autodesk.com/detail/Version/2"
          prodtrackTabUsesExtension={false}
          syncProdtrackDisabled={false}
        />
      </HotkeysProvider>
    );
    const link = screen.getByRole('link', { name: /PT tab/i });
    expect(link).toHaveAttribute(
      'href',
      'https://studio.shotgrid.autodesk.com/detail/Version/2'
    );
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('flags Set In Review while a live bot has nowhere to file its transcript', () => {
    render(
      <HotkeysProvider>
        <VersionHeader
          shotCode="SHOT"
          versionNumber="v001"
          projectId={1}
          isDiscardingSegments
        />
      </HotkeysProvider>
    );
    const button = screen.getByRole('button', {
      name: /transcript is not being saved/i,
    });
    expect(button).toBeEnabled();
  });

  it('leaves Set In Review unflagged when no bot is discarding segments', () => {
    render(
      <HotkeysProvider>
        <VersionHeader shotCode="SHOT" versionNumber="v001" projectId={1} />
      </HotkeysProvider>
    );
    expect(
      screen.getByRole('button', { name: /^Set In Review$/i })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /transcript is not being saved/i })
    ).not.toBeInTheDocument();
  });
});
