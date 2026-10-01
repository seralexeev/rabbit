import React from 'react';

export type ChatActions = { ask: (text: string) => void };

export const ChatActionsContext = React.createContext<ChatActions>({ ask: () => undefined });

export const useChatActions = () => React.useContext(ChatActionsContext);
