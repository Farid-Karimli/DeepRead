import { createContext } from 'react';

export type User = {
    username: string,
    id: number,
}

type sidePanelContext = {
    currentUser: User | null;
    setUser: (user: User | null) => void;
  };
  
export const UserContext = createContext<sidePanelContext>({
    currentUser: null,
    setUser: () => {},
});