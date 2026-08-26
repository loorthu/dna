import styled from 'styled-components';
import { Select, TextField } from '@radix-ui/themes';

export const StyledTextField = styled(TextField.Root)`
  &.rt-TextFieldRoot {
    height: 44px;
    background: ${({ theme }) => theme.colors.bg.surface};
    border: 1px solid ${({ theme }) => theme.colors.border.subtle};
    border-radius: ${({ theme }) => theme.radii.md};
    box-shadow: none;
    transition:
      border-color ${({ theme }) => theme.transitions.fast},
      box-shadow ${({ theme }) => theme.transitions.fast};

    &:focus-within {
      border-color: ${({ theme }) => theme.colors.accent.main};
      box-shadow: 0 0 0 1px ${({ theme }) => theme.colors.accent.main};
    }

    input {
      font-family: ${({ theme }) => theme.fonts.sans};
      font-size: 14px;
      color: ${({ theme }) => theme.colors.text.primary};

      &::placeholder {
        color: ${({ theme }) => theme.colors.text.muted};
      }
    }
  }
`;

export const StyledSelectTrigger = styled(Select.Trigger)`
  &&.rt-SelectTrigger {
    height: 44px;
    background: ${({ theme }) => theme.colors.bg.surface};
    border: 1px solid ${({ theme }) => theme.colors.border.subtle};
    border-radius: ${({ theme }) => theme.radii.md};
    box-shadow: none;
    font-family: ${({ theme }) => theme.fonts.sans};
    font-size: 14px;
    color: ${({ theme }) => theme.colors.text.primary};
    transition:
      border-color ${({ theme }) => theme.transitions.fast},
      box-shadow ${({ theme }) => theme.transitions.fast};

    &:focus,
    &[data-state='open'] {
      border-color: ${({ theme }) => theme.colors.accent.main};
      box-shadow: 0 0 0 1px ${({ theme }) => theme.colors.accent.main};
    }

    span {
      color: ${({ theme }) => theme.colors.text.primary};
    }

    span[data-placeholder] {
      color: ${({ theme }) => theme.colors.text.muted};
    }
  }
`;

/**
 * Secondary text inside a select item — a count or hint sitting beside the label. Its colours
 * live in StyledSelectContent below, which paints every span inside an item and would
 * otherwise win on specificity.
 */
export const SelectItemMeta = styled.span`
  margin-left: 8px;
  font-size: 12px;
`;

export const StyledSelectContent = styled(Select.Content)`
  &&.rt-SelectContent {
    background: ${({ theme }) => theme.colors.bg.elevated};
    border: 1px solid ${({ theme }) => theme.colors.border.subtle};
    border-radius: ${({ theme }) => theme.radii.md};
    box-shadow: ${({ theme }) => theme.shadows.lg};
  }

  && .rt-SelectItem {
    font-family: ${({ theme }) => theme.fonts.sans};
    font-size: 14px;
    color: ${({ theme }) => theme.colors.text.primary};
    border-radius: ${({ theme }) => theme.radii.sm};

    span {
      color: ${({ theme }) => theme.colors.text.primary};
    }

    ${SelectItemMeta} {
      color: ${({ theme }) => theme.colors.text.secondary};
    }

    ${SelectItemMeta}[data-warn='true'] {
      color: ${({ theme }) => theme.colors.status.warning};
    }

    &[data-highlighted] {
      background: ${({ theme }) => theme.colors.accent.subtle};
      color: ${({ theme }) => theme.colors.accent.main};

      span {
        color: ${({ theme }) => theme.colors.accent.main};
      }

      ${SelectItemMeta} {
        color: ${({ theme }) => theme.colors.text.secondary};
      }

      ${SelectItemMeta}[data-warn='true'] {
        color: ${({ theme }) => theme.colors.status.warning};
      }
    }
  }
`;
