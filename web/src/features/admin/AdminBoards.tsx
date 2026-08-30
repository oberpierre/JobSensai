import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MicroLabel } from "../../components/MicroLabel";
import {
  StateCard,
  LoadingState,
  ErrorState,
} from "../../components/StateCard";
import { useBoardsApi } from "../../api/useBoardsApi";
import { ApiError } from "../../api/ApiError";
import type { Board, BoardType } from "../../api/types";
import styles from "./AdminBoards.module.scss";

const BOARDS_QUERY_KEY = ["boards"];

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong";
}

// Lists start URLs from /api/boards and adds, edits and deletes them, so a board
// can be added with no redeploy. Type is chosen once at creation and the edit
// form carries no control for it, matching the PUT payload's shape.
export function AdminBoards() {
  const api = useBoardsApi();
  const queryClient = useQueryClient();
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: BOARDS_QUERY_KEY,
    queryFn: () => api.listBoards(),
  });

  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: BOARDS_QUERY_KEY });

  const createMutation = useMutation({
    mutationFn: (params: { name: string; url: string; type: BoardType }) =>
      api.createBoard(params),
    onSuccess: async () => {
      setAdding(false);
      setFormError(null);
      await invalidate();
    },
    onError: (mutationError) => setFormError(errorMessage(mutationError)),
  });

  const updateMutation = useMutation({
    mutationFn: (args: { boardId: string; name: string; url: string }) =>
      api.updateBoard(args.boardId, { name: args.name, url: args.url }),
    onSuccess: async () => {
      setEditingId(null);
      setFormError(null);
      await invalidate();
    },
    onError: (mutationError) => setFormError(errorMessage(mutationError)),
  });

  const deleteMutation = useMutation({
    mutationFn: (boardId: string) => api.deleteBoard(boardId),
    onSuccess: () => invalidate(),
    onError: (mutationError) => setFormError(errorMessage(mutationError)),
  });

  function startAdding() {
    setEditingId(null);
    setFormError(null);
    setAdding(true);
  }

  function startEditing(boardId: string) {
    setAdding(false);
    setFormError(null);
    setEditingId(boardId);
  }

  function cancelForm() {
    setAdding(false);
    setEditingId(null);
    setFormError(null);
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div className={styles.headings}>
          <h1 className={styles.title}>Job boards</h1>
          <p className={styles.subtitle}>
            One row per start URL. Re-scraped roughly every 6 hours.
          </p>
        </div>
        <button
          type="button"
          className={styles.addButton}
          onClick={startAdding}
        >
          + Add board
        </button>
      </div>

      {formError && !adding && !editingId && (
        <p className={styles.formError}>{formError}</p>
      )}

      {isPending && <LoadingState />}
      {isError && (
        <ErrorState
          message="Couldn't load boards"
          endpoint="GET /api/boards"
          status={error instanceof ApiError ? error.status : undefined}
          onRetry={() => refetch()}
        />
      )}

      {!isPending && !isError && data && (
        <div className={styles.table}>
          <div className={styles.rowHead}>
            <span>Name / URL</span>
            <span>Type</span>
            <span>Postings</span>
            <span />
          </div>

          {data.items.length === 0 && !adding && (
            <StateCard>
              <MicroLabel>no boards</MicroLabel>
              <p className={styles.message}>Nothing here yet.</p>
            </StateCard>
          )}

          {data.items.map((board) =>
            editingId === board.id ? (
              <BoardForm
                key={board.id}
                mode="edit"
                initialName={board.name}
                initialUrl={board.url}
                submitting={updateMutation.isPending}
                error={formError}
                onCancel={cancelForm}
                onSubmit={(values) =>
                  updateMutation.mutate({ boardId: board.id, ...values })
                }
              />
            ) : (
              <BoardRow
                key={board.id}
                board={board}
                onEdit={() => startEditing(board.id)}
                onRemove={() => deleteMutation.mutate(board.id)}
              />
            ),
          )}

          {adding && (
            <BoardForm
              mode="create"
              submitting={createMutation.isPending}
              error={formError}
              onCancel={cancelForm}
              onSubmit={(values) =>
                createMutation.mutate({
                  ...values,
                  type: values.type ?? "html_crawl",
                })
              }
            />
          )}
        </div>
      )}
    </div>
  );
}

function BoardRow({
  board,
  onEdit,
  onRemove,
}: {
  board: Board;
  onEdit: () => void;
  onRemove: () => void;
}) {
  const isJsonApi = board.type === "json_api";
  return (
    <div className={isJsonApi ? styles.rowGreyed : styles.row}>
      <div className={styles.nameCell}>
        <span className={styles.name}>{board.name}</span>
        <span className={styles.url}>{board.url}</span>
      </div>
      <span className={styles.type}>
        {isJsonApi ? "JSON API" : "HTML crawl"}
      </span>
      <span className={styles.count}>
        {board.posting_count === null ? "—" : board.posting_count}
      </span>
      <span className={styles.actions}>
        <button type="button" className={styles.editAction} onClick={onEdit}>
          Edit
        </button>
        <button
          type="button"
          className={styles.removeAction}
          onClick={onRemove}
        >
          Remove
        </button>
      </span>
    </div>
  );
}

function BoardForm({
  mode,
  initialName = "",
  initialUrl = "",
  submitting,
  error,
  onCancel,
  onSubmit,
}: {
  mode: "create" | "edit";
  initialName?: string;
  initialUrl?: string;
  submitting: boolean;
  error: string | null;
  onCancel: () => void;
  onSubmit: (values: { name: string; url: string; type?: BoardType }) => void;
}) {
  const [name, setName] = useState(initialName);
  const [url, setUrl] = useState(initialUrl);
  const [type, setType] = useState<BoardType>("html_crawl");

  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(mode === "create" ? { name, url, type } : { name, url });
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
