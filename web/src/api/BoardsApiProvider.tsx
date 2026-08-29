import type { ReactNode } from "react";
import { BoardsApiContext } from "./useBoardsApi";
import type { BoardsApi } from "./boardsApi";

export function BoardsApiProvider({
  api,
  children,
}: {
  api: BoardsApi;
  children: ReactNode;
}) {
  return (
    <BoardsApiContext.Provider value={api}>
      {children}
    </BoardsApiContext.Provider>
  );
}
