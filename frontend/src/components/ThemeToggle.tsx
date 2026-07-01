import { IoDesktopOutline, IoMoonOutline, IoSunnyOutline } from 'react-icons/io5';
import { useTheme, type ThemePreference } from '../context/ThemeContext';

const THEME_LABELS: Record<ThemePreference, string> = {
  light: 'Light theme',
  dark: 'Dark theme',
  system: 'System theme',
};

export default function ThemeToggle({ className }: { className?: string }) {
  const { theme, cycleTheme } = useTheme();

  const Icon =
    theme === 'light' ? IoSunnyOutline : theme === 'dark' ? IoMoonOutline : IoDesktopOutline;

  return (
    <button
      type="button"
      className={className ?? 'theme-toggle'}
      aria-label={THEME_LABELS[theme]}
      title={THEME_LABELS[theme]}
      onClick={cycleTheme}
    >
      <Icon aria-hidden />
    </button>
  );
}
