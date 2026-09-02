import styles from "./ActiveToggle.module.scss";

// A two-state switch: `role="switch"` with `aria-checked` rather than a styled
// checkbox, so the control is operable by keyboard and announced as a switch.
// `label` is required because the button's only child is an empty span, so a
// switch without one is announced with its state and no subject.
export function ActiveToggle({
  active,
  onToggle,
  label,
  disabled,
}: {
  active: boolean;
  onToggle: () => void;
  label: string;
  disabled?: boolean;
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
