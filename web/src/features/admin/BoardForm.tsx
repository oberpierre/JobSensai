import { useState } from "react";
import { MicroLabel } from "../../components/MicroLabel";
import { ActiveToggle } from "../../components/ActiveToggle";
import type { BoardType } from "../../api/types";
import styles from "./AdminBoards.module.scss";

// Shares AdminBoards.module.scss with the screen it sits in: the form renders as a
// row of that table.
export function BoardForm({
  mode,
  initialName = "",
  initialUrl = "",
  initialActive = true,
  submitting,
  error,
  onCancel,
  onSubmit,
}: {
  mode: "create" | "edit";
  initialName?: string;
  initialUrl?: string;
  initialActive?: boolean;
  submitting: boolean;
  error: string | null;
  onCancel: () => void;
  onSubmit: (values: {
    name: string;
    url: string;
    active: boolean;
    type?: BoardType;
  }) => void;
}) {
  const [name, setName] = useState(initialName);
  const [url, setUrl] = useState(initialUrl);
  const [type, setType] = useState<BoardType>("html_crawl");
  const [active, setActive] = useState(initialActive);

  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(
          mode === "create"
            ? { name, url, active, type }
            : { name, url, active },
        );
      }}
    >
      <MicroLabel>{mode === "create" ? "New board" : "Edit board"}</MicroLabel>
      <div className={styles.formFields}>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>Name</span>
          <input
            type="text"
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Google · security roles"
          />
        </label>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>URL</span>
          <input
            type="text"
            required
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://…"
          />
        </label>
      </div>

      <div className={styles.field}>
        <span className={styles.fieldLabel}>Active</span>
        <div className={styles.activeField}>
          <ActiveToggle
            active={active}
            onToggle={() => setActive((v) => !v)}
            label="Active"
          />
          <span className={styles.activeNote}>crawls on next run</span>
        </div>
      </div>

      {mode === "create" && (
        <div className={styles.field}>
          <span className={styles.fieldLabel}>Type</span>
          <div className={styles.typeToggle}>
            <button
              type="button"
              className={
                type === "html_crawl"
                  ? styles.typeOptionActive
                  : styles.typeOption
              }
              onClick={() => setType("html_crawl")}
            >
              HTML crawl
            </button>
            <button
              type="button"
              className={
                type === "json_api"
                  ? styles.typeOptionActive
                  : styles.typeOption
              }
              onClick={() => setType("json_api")}
            >
              JSON API
            </button>
          </div>
        </div>
      )}

      <div className={styles.formActions}>
        <button
          type="submit"
          className={styles.saveButton}
          disabled={submitting}
        >
          Save
        </button>
        <button
          type="button"
          className={styles.cancelButton}
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
      {error && <p className={styles.formError}>{error}</p>}
    </form>
  );
}
