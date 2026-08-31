import styles from "./ActiveToggle.module.scss";

// A two-state switch: `role="switch"` with `aria-checked` rather than a styled
// checkbox, so the control is operable by keyboard and announced as a switch.
export function ActiveToggle({
  active,
  onToggle,
  disabled,
  label,
}: {
  active: boolean;
  onToggle: () => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={active}
      aria-label={label}
      className={active ? styles.on : styles.off}
      onClick={onToggle}
      disabled={disabled}
    >
      <span className={active ? styles.knobOn : styles.knobOff} />
    </button>
  );
}
