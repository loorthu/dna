import { ThemeProvider } from 'styled-components';
import { Theme } from '@radix-ui/themes';
import App from './App';
import { darkTheme, lightTheme, GlobalStyles } from './styles';
import {
  EventProvider,
  FollowAlongProvider,
  ToastProvider,
  AuthProvider,
  useThemeMode,
} from './contexts';
import { HotkeysProvider } from './hotkeys';
import { ReviewPage, useReviewRoute } from './review';

export function ThemedApp() {
  const { mode } = useThemeMode();
  const activeTheme = mode === 'light' ? lightTheme : darkTheme;
  // The one fork in the app. `/review/...` is the artist-facing read of a playlist and shares
  // only the theme and the sign-in with the reviewing tool — it deliberately does not get the
  // hotkeys, the live event socket or the follow-along session, none of which mean anything to
  // someone reading a review that already happened.
  const reviewRoute = useReviewRoute();
  return (
    <ThemeProvider theme={activeTheme}>
      <Theme appearance={mode} accentColor="violet">
        <GlobalStyles />
        <AuthProvider>
          {reviewRoute ? (
            <ReviewPage route={reviewRoute} />
          ) : (
            <HotkeysProvider>
              <ToastProvider>
                <EventProvider>
                  <FollowAlongProvider>
                    <App />
                  </FollowAlongProvider>
                </EventProvider>
              </ToastProvider>
            </HotkeysProvider>
          )}
        </AuthProvider>
      </Theme>
    </ThemeProvider>
  );
}
