import type { ReviewFocus, ReviewFocusParser } from './types';

/**
 * Element names carrying each field of a "current clip" broadcast.
 *
 * The defaults describe the payload DNA was first pointed at, where the clip
 * identity travels as `<jts>`. A site whose player names things differently
 * builds its own parser with {@link createCurrentClipParser} rather than
 * patching this file.
 */
export interface CurrentClipElementNames {
  session: string;
  show: string;
  shot: string;
  externalRef: string;
  clipRef: string;
}

export const DEFAULT_CURRENT_CLIP_ELEMENTS: CurrentClipElementNames = {
  session: 'session',
  show: 'show',
  shot: 'shot',
  externalRef: 'jts',
  clipRef: 'guid',
};

/**
 * Text of the first element with this name, in document order.
 *
 * Names are looked up anywhere in the tree rather than at a fixed path, because
 * payloads nest inconsistently: an announcement may carry the session at the
 * top level and the clip's own fields inside a wrapper element. Where a name
 * appears more than once (a clip repeating its show, say), the outermost one
 * comes first in document order and wins.
 */
function elementText(doc: Document, tagName: string): string {
  const element = doc.getElementsByTagName(tagName)[0];
  return element?.textContent?.trim() ?? '';
}

/**
 * Builds a parser for XML "current clip" payloads.
 *
 * Parsing goes through `DOMParser` rather than regular expressions so shot
 * names containing `-`, `.` or other non-word characters survive intact.
 */
export function createCurrentClipParser(
  elements: Partial<CurrentClipElementNames> = {}
): ReviewFocusParser {
  const names: CurrentClipElementNames = {
    ...DEFAULT_CURRENT_CLIP_ELEMENTS,
    ...elements,
  };

  return (body: string): ReviewFocus | null => {
    if (!body?.trim()) {
      return null;
    }
    if (typeof DOMParser === 'undefined') {
      return null;
    }

    let doc: Document;
    try {
      doc = new DOMParser().parseFromString(body, 'text/xml');
    } catch {
      return null;
    }

    if (doc.getElementsByTagName('parsererror').length > 0) {
      return null;
    }

    const externalRef = elementText(doc, names.externalRef);
    if (!externalRef) {
      return null;
    }

    return {
      session: elementText(doc, names.session),
      show: elementText(doc, names.show),
      shot: elementText(doc, names.shot),
      externalRef,
      clipRef: elementText(doc, names.clipRef),
    };
  };
}

export const parseCurrentClip: ReviewFocusParser = createCurrentClipParser();
