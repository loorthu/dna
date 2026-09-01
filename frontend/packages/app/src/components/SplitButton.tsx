import { Fragment, type ReactNode } from 'react';
import styled from 'styled-components';
import { ChevronDown } from 'lucide-react';
import { DropdownMenu } from '@radix-ui/themes';

export interface SplitButtonMenuItem {
  label: string;
  /** Muted text at the right of the row — a count, a date, anything secondary to the label. */
  meta?: ReactNode;
  onSelect?: () => void;
  /** Rule above this item, for parting a list of things from the actions below it. */
  separatorBefore?: boolean;
  disabled?: boolean;
}

interface SplitButtonProps {
  children?: ReactNode;
  onClick?: () => void;
  menuItems?: SplitButtonMenuItem[];
  onRightClick?: () => void;
  leftSlot?: ReactNode;
  rightSlot?: ReactNode;
  disabled?: boolean;
}

const SplitButtonWrapper = styled.div`
  display: flex;
  align-items: stretch;
  height: 32px;

  &:hover button {
    border-color: ${({ theme }) => theme.colors.border.strong};
  }
`;

const MainButton = styled.button`
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  font-size: 14px;
  font-weight: 500;
  font-family: ${({ theme }) => theme.fonts.sans};
  color: ${({ theme }) => theme.colors.text.secondary};
  background: transparent;
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-right: none;
  border-top-left-radius: ${({ theme }) => theme.radii.md};
  border-bottom-left-radius: ${({ theme }) => theme.radii.md};
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.fast};
  white-space: nowrap;

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.colors.bg.surfaceHover};
    color: ${({ theme }) => theme.colors.text.primary};
    border-color: ${({ theme }) => theme.colors.border.strong};
  }

  &:active:not(:disabled) {
    background: ${({ theme }) => theme.colors.bg.overlay};
    transform: translateY(1px);
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
`;

const TriggerButton = styled.button`
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  border: 1px solid ${({ theme }) => theme.colors.border.default};
  border-left: 1px solid ${({ theme }) => theme.colors.border.subtle};
  border-top-right-radius: ${({ theme }) => theme.radii.md};
  border-bottom-right-radius: ${({ theme }) => theme.radii.md};
  background: transparent;
  color: ${({ theme }) => theme.colors.text.secondary};
  cursor: pointer;
  transition: all ${({ theme }) => theme.transitions.fast};

  &:hover {
    background: ${({ theme }) => theme.colors.bg.surfaceHover};
    color: ${({ theme }) => theme.colors.text.primary};
    border-color: ${({ theme }) => theme.colors.border.strong};
  }

  &:active {
    background: ${({ theme }) => theme.colors.bg.overlay};
    transform: translateY(1px);
  }
`;

// Menus here list things as well as actions — recent playlists, for one — so a long name has to
// give way. The cap is on the label rather than on the menu: the menu sizes itself to its widest
// row, so capping the menu instead would leave the row wider than the box and hide the meta off
// the right edge.
const MenuItemLabel = styled.span`
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const MenuItemMeta = styled.span`
  margin-left: auto;
  padding-left: 16px;
  font-size: 12px;
  color: ${({ theme }) => theme.colors.text.muted};
`;

export function SplitButton({
  children,
  onClick,
  menuItems,
  onRightClick,
  leftSlot,
  rightSlot,
  disabled = false,
}: SplitButtonProps) {
  const renderRightButton = () => {
    if (menuItems && menuItems.length > 0) {
      return (
        <DropdownMenu.Root>
          <DropdownMenu.Trigger>
            <TriggerButton>
              {rightSlot ?? <ChevronDown size={14} />}
            </TriggerButton>
          </DropdownMenu.Trigger>
          <DropdownMenu.Content>
            {menuItems.map((item, index) => (
              <Fragment key={index}>
                {item.separatorBefore && <DropdownMenu.Separator />}
                <DropdownMenu.Item
                  onSelect={item.onSelect}
                  disabled={item.disabled}
                >
                  <MenuItemLabel>{item.label}</MenuItemLabel>
                  {item.meta != null && (
                    <MenuItemMeta>{item.meta}</MenuItemMeta>
                  )}
                </DropdownMenu.Item>
              </Fragment>
            ))}
          </DropdownMenu.Content>
        </DropdownMenu.Root>
      );
    }

    const handleRightClick = (e: React.MouseEvent) => {
      e.stopPropagation();
      onRightClick?.();
    };

    return (
      <TriggerButton onClick={handleRightClick}>
        {rightSlot ?? <ChevronDown size={14} />}
      </TriggerButton>
    );
  };

  return (
    <SplitButtonWrapper>
      <MainButton onClick={onClick} disabled={disabled}>
        {leftSlot}
        {children}
      </MainButton>
      {renderRightButton()}
    </SplitButtonWrapper>
  );
}
