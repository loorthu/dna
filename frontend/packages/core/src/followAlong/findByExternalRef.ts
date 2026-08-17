export interface HasExternalRef {
  external_ref?: string | number | null;
}

/**
 * Resolves a review player's clip id onto a loaded entity.
 *
 * Comparison is string-based and trimmed on both sides: production tracking
 * systems type custom id fields inconsistently, so a version may carry `42`
 * where the player announces `"42"`.
 */
export function findByExternalRef<T extends HasExternalRef>(
  items: readonly T[],
  externalRef: string | null | undefined
): T | null {
  const wanted = externalRef?.trim();
  if (!wanted) {
    return null;
  }

  return (
    items.find((item) => {
      const ref = item.external_ref;
      if (ref === null || ref === undefined) {
        return false;
      }
      return String(ref).trim() === wanted;
    }) ?? null
  );
}
