// @vitest-environment jsdom

import { describe, it, expect } from 'vitest';
import { createCurrentClipParser, parseCurrentClip } from './parseCurrentClip';

function clipXml(fields: Record<string, string>): string {
  const body = Object.entries(fields)
    .map(([name, value]) => `  <${name}>${value}</${name}>`)
    .join('\n');
  return `<?xml version="1.0"?>\n<current_clip>\n${body}\n</current_clip>`;
}

describe('parseCurrentClip', () => {
  it('extracts session, show, shot and external ref', () => {
    const focus = parseCurrentClip(
      clipXml({
        session: 'director_review',
        show: 'nite',
        shot: 'abc0100',
        jts: '4815162342',
      })
    );

    expect(focus).toEqual({
      session: 'director_review',
      show: 'nite',
      shot: 'abc0100',
      externalRef: '4815162342',
    });
  });

  it('keeps shot names containing dashes and dots intact', () => {
    const focus = parseCurrentClip(
      clipXml({ session: 's', show: 'nite', shot: 'abc-0100.v2', jts: '7' })
    );

    expect(focus?.shot).toBe('abc-0100.v2');
  });

  it('keeps the external ref as a string', () => {
    const focus = parseCurrentClip(
      clipXml({ session: 's', show: 'nite', shot: 'abc0100', jts: '007' })
    );

    expect(focus?.externalRef).toBe('007');
  });

  it('trims surrounding whitespace from element text', () => {
    const focus = parseCurrentClip(
      '<current_clip><session> review </session><show>\n nite \n</show>' +
        '<shot> abc0100 </shot><jts> 42 </jts></current_clip>'
    );

    expect(focus).toEqual({
      session: 'review',
      show: 'nite',
      shot: 'abc0100',
      externalRef: '42',
    });
  });

  it('returns null when the external ref is missing', () => {
    expect(
      parseCurrentClip(clipXml({ session: 's', show: 'nite', shot: 'abc0100' }))
    ).toBeNull();
  });

  it('returns null when the external ref is empty', () => {
    expect(
      parseCurrentClip(
        clipXml({ session: 's', show: 'nite', shot: 'abc0100', jts: '' })
      )
    ).toBeNull();
  });

  it('returns null on malformed XML', () => {
    expect(parseCurrentClip('<current_clip><jts>42</jts>')).toBeNull();
  });

  it('returns null on a non-XML payload', () => {
    expect(parseCurrentClip('not xml at all')).toBeNull();
  });

  it('returns null on an empty payload', () => {
    expect(parseCurrentClip('')).toBeNull();
    expect(parseCurrentClip('   ')).toBeNull();
  });

  it('defaults missing optional fields to empty strings', () => {
    expect(
      parseCurrentClip('<current_clip><jts>42</jts></current_clip>')
    ).toEqual({
      session: '',
      show: '',
      shot: '',
      externalRef: '42',
    });
  });

  it('reads site-specific element names when configured', () => {
    const parse = createCurrentClipParser({
      externalRef: 'clip_id',
      session: 'room',
    });

    const focus = parse(
      clipXml({
        room: 'stage_a',
        show: 'nite',
        shot: 'abc0100',
        clip_id: 'xyz',
      })
    );

    expect(focus).toEqual({
      session: 'stage_a',
      show: 'nite',
      shot: 'abc0100',
      externalRef: 'xyz',
    });
  });
});
