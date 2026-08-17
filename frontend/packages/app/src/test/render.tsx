import { type ReactElement, type ReactNode } from 'react';
import { render, type RenderOptions } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from 'styled-components';
import { Theme } from '@radix-ui/themes';
import { theme } from '../styles';
import { AuthProvider } from '../contexts/AuthContext';
import { ThemeModeProvider } from '../contexts/ThemeContext';
import { FeatureFlagsProvider } from '../contexts/FeatureFlagsContext';
import { FollowAlongProvider } from '../contexts/FollowAlongContext';
import { ToastProvider } from '../contexts/ToastContext';
import { EventProvider } from '../contexts/EventContext';

interface WrapperProps {
  children: ReactNode;
}

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  });
}

function AllTheProviders({ children }: WrapperProps) {
  const queryClient = createTestQueryClient();

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>
        <Theme>
          <ThemeModeProvider>
            <FeatureFlagsProvider>
              <AuthProvider>
                <ToastProvider>
                  <EventProvider>
                    <FollowAlongProvider>{children}</FollowAlongProvider>
                  </EventProvider>
                </ToastProvider>
              </AuthProvider>
            </FeatureFlagsProvider>
          </ThemeModeProvider>
        </Theme>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

function customRender(
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'>
) {
  return render(ui, { wrapper: AllTheProviders, ...options });
}

export * from '@testing-library/react';
export { customRender as render };
