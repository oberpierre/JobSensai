import { createContext, useContext } from "react";
import { createHttpBoardsApi, type BoardsApi } from "./boardsApi";

// The default context value is the real implementation, so nothing needs to wrap
// the app in a provider just to reach the network. Tests override it to inject a
// stub without touching main.tsx.
export const BoardsApiContext = createContext<BoardsApi>(createHttpBoardsApi());

export function useBoardsApi(): BoardsApi {
  return useContext(BoardsApiContext);
}
