export interface FollowAlongConfig {
  brokerURL: string;
  topic: string;
  sessionsUrl: string;
}

function trimmed(value: string | undefined): string {
  return value?.trim() ?? '';
}

/**
 * Build-time configuration for Follow Along.
 *
 * There are no defaults: the broker address and topic name belong to whichever
 * review player a site runs, so DNA ships knowing neither. Follow Along is
 * unavailable until both are configured.
 */
export function readFollowAlongConfig(
  env: ImportMetaEnv = import.meta.env
): FollowAlongConfig | null {
  const brokerURL = trimmed(env.VITE_FOLLOW_ALONG_BROKER_URL);
  const topic = trimmed(env.VITE_FOLLOW_ALONG_TOPIC);

  if (!brokerURL || !topic) {
    return null;
  }

  return {
    brokerURL,
    topic,
    sessionsUrl: trimmed(env.VITE_FOLLOW_ALONG_SESSIONS_URL),
  };
}
