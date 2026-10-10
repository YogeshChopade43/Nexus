import { expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { Dropdown } from './Dropdown';

test('the open menu is drawn above the page, so cards below never cover it', () => {
  const edit = vi.fn();
  const { container } = render(
    <div style={{ overflow: 'hidden', position: 'relative', zIndex: 1 }}>
      <Dropdown trigger={<span>⋮</span>} items={[{ label: 'Edit', onClick: edit }, { label: 'Delete', onClick: () => {}, danger: true }]} />
    </div>,
  );
  fireEvent.click(screen.getByText('⋮'));
  const menu = screen.getByRole('menu');
  expect(container.contains(menu)).toBe(false);  // not inside the card (or anything that clips or covers it)
  expect(menu.parentElement).toBe(document.body);
  // A press on a menu item isn't an "outside click": the menu stays open until the item runs.
  fireEvent.mouseDown(screen.getByRole('menuitem', { name: 'Edit' }));
  fireEvent.click(screen.getByRole('menuitem', { name: 'Edit' }));
  expect(edit).toHaveBeenCalled();
  expect(screen.queryByRole('menu')).toBeNull();
});

test('clicking elsewhere or pressing Escape closes it', () => {
  render(<div><p>outside</p><Dropdown trigger={<span>⋮</span>} items={[{ label: 'Edit', onClick: () => {} }]} /></div>);
  fireEvent.click(screen.getByText('⋮'));
  fireEvent.mouseDown(screen.getByText('outside'));
  expect(screen.queryByRole('menu')).toBeNull();
  fireEvent.click(screen.getByText('⋮'));
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('menu')).toBeNull();
});
