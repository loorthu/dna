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
      clipRef: '',
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
      clipRef: '',
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
      clipRef: '',
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
      clipRef: '',
    });
  });
});

// Verbatim frame body captured from a live broker. Guards the two things a
// hand-written fixture keeps getting wrong: the clip's own fields are nested
// inside a wrapper while the session sits at the top level, and the show is
// announced twice.
const LIVE_FRAME = `<currentClip messageProducerHostName="edbot3.example.com" syncApiVersion="19">
        <show>ccf</show>
        <session>rounds</session>
        <pguid>076aaddaa07442fdaba2eb68062748c4</pguid>
        <clip>
      <guid>7a2d3562372141d89f1e4d3c75c148ee</guid>
      <element>/net/media/vfo/spj/ccf/taf0140/ccf-192358-taf0140.spj</element>
      <inFrame>1001</inFrame>
      <show>ccf</show>
      <shot>taf0140</shot>
      <jts>192358</jts>
      <greenDot>false</greenDot>
    </clip>
      </currentClip>`;

describe('parseCurrentClip, against a live frame', () => {
  it('reads fields whether they are nested or top level', () => {
    expect(parseCurrentClip(LIVE_FRAME)).toEqual({
      session: 'rounds',
      show: 'ccf',
      shot: 'taf0140',
      externalRef: '192358',
      clipRef: '7a2d3562372141d89f1e4d3c75c148ee',
    });
  });

  it('does not mistake the playlist guid for the clip guid', () => {
    expect(parseCurrentClip(LIVE_FRAME)?.clipRef).not.toBe(
      '076aaddaa07442fdaba2eb68062748c4'
    );
  });
});
