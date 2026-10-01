import { Chat, useChat } from '@ai-sdk/react';
import { css, cx, keyframes } from '@emotion/css';
import {
    DefaultChatTransport,
    type UIMessage,
    getToolName,
    isTextUIPart,
    isToolUIPart,
    lastAssistantMessageIsCompleteWithApprovalResponses,
} from 'ai';
import React from 'react';

import { readLocal, writeLocal } from '../hooks.ts';
import { useHud, useHudTick } from '../hud/HudContext.ts';
import { HudModal } from '../hud/HudModal.tsx';
import { frameCss } from '../hud/frame.ts';
import { L } from '../log.ts';
import { isLive } from '../perception/Telemetry.ts';
import { Activity } from './Activity.tsx';
import { Approval } from './Approval.tsx';
import { ChatActionsContext } from './ChatActions.ts';
import { Markdown } from './Markdown.tsx';
import { StartScreen } from './StartScreen.tsx';
import { clearMessages, loadMessages, saveMessages } from './persistence.ts';
import { isChartLike, readResult } from './results.ts';
import { CHAT_URL, chatFetch } from './session.ts';
import { useBackendHealth } from './useBackendHealth.ts';
import { ResultView } from './widgets/ResultView.tsx';

const LAYOUT_KEY = 'rabbit.chat.layout';
const THROTTLE_MS = 50;
const MIN_WIDTH = 320;
const MIN_HEIGHT = 240;
const NAV_TIMEOUT_MS = 2000;
const MOVING_MPS = 0.05;
const MOTION_MODES = new Set(['driving', 'maneuvering', 'blocked']);

type Layout = { open: boolean; expanded?: boolean; width: number; height: number };

const createChat = () => {
    const chat: Chat<UIMessage> = new Chat<UIMessage>({
        messages: loadMessages(),
        transport: new DefaultChatTransport({ api: CHAT_URL, fetch: chatFetch }),
        sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithApprovalResponses,
        onFinish: () => saveMessages(chat.messages),
        onError: (error) => L.error('Chat request failed', error),
    });
    return chat;
};

const isTyping = (target: EventTarget | null) =>
    target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement;

const useRobotMoving = () => {
    const { store } = useHud();
    const [moving, setMoving] = React.useState(false);
    useHudTick((now) => {
        const nav = isLive(store.nav, now, NAV_TIMEOUT_MS) ? store.nav.value : null;
        setMoving((nav != null && MOTION_MODES.has(nav.mode)) || store.derived.speed > MOVING_MPS);
    });
    return moving;
};

export const ChatPanel: React.FC = () => {
    const { stopRobot } = useHud();
    const moving = useRobotMoving();
    const [chat] = React.useState(createChat);
    const [layout, setLayout] = React.useState<Layout>(() =>
        readLocal<Layout>(LAYOUT_KEY, (raw) => raw as Layout, { open: false, width: 440, height: 520 }),
    );
    const panelRef = React.useRef<HTMLElement | null>(null);
    const inputRef = React.useRef<HTMLTextAreaElement | null>(null);

    const updateLayout = (next: Partial<Layout>) =>
        setLayout((prev) => {
            const merged = { ...prev, ...next };
            writeLocal(LAYOUT_KEY, merged);
            return merged;
        });

    React.useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (isTyping(event.target) || event.ctrlKey || event.metaKey || event.altKey || event.key.toLowerCase() !== 'c')
                return;
            event.preventDefault();
            setLayout((prev) => (prev.open ? prev : { ...prev, open: true }));
            requestAnimationFrame(() => inputRef.current?.focus());
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, []);

    const startResize = (event: React.PointerEvent<HTMLDivElement>) => {
        const panel = panelRef.current;
        if (panel == null) return;
        event.preventDefault();
        const handle = event.currentTarget;
        handle.setPointerCapture(event.pointerId);
        const start = { x: event.clientX, y: event.clientY, width: layout.width, height: layout.height };
        const size = { width: start.width, height: start.height };
        const onMove = (move: PointerEvent) => {
            size.width = Math.max(MIN_WIDTH, start.width + start.x - move.clientX);
            size.height = Math.max(MIN_HEIGHT, start.height + start.y - move.clientY);
            panel.style.setProperty('--chat-width', `${size.width}px`);
            panel.style.setProperty('--chat-height', `${size.height}px`);
        };
        const onUp = () => {
            handle.removeEventListener('pointermove', onMove);
            handle.removeEventListener('pointerup', onUp);
            updateLayout(size);
        };
        handle.addEventListener('pointermove', onMove);
        handle.addEventListener('pointerup', onUp);
    };

    return (
        <>
            <button className={stopCss} data-moving={moving} onClick={stopRobot} title='Cancel navigation and stop the drive'>
                ■ STOP
            </button>
            {layout.expanded === true ? (
                <HudModal code='AI' title='RABBIT // AI LINK' onClose={() => updateLayout({ expanded: false })}>
                    <ChatBody
                        chat={chat}
                        inputRef={inputRef}
                        expanded
                        onExpand={() => updateLayout({ expanded: false })}
                        onCollapse={() => updateLayout({ expanded: false, open: false })}
                    />
                </HudModal>
            ) : layout.open ? (
                <section
                    ref={panelRef}
                    className={cx(frameCss, panelCss)}
                    style={
                        { '--chat-width': `${layout.width}px`, '--chat-height': `${layout.height}px` } as React.CSSProperties
                    }>
                    <div className={resizeCss} onPointerDown={startResize} title='Resize' />
                    <ChatBody
                        chat={chat}
                        inputRef={inputRef}
                        expanded={false}
                        onExpand={() => updateLayout({ expanded: true })}
                        onCollapse={() => updateLayout({ open: false })}
                    />
                </section>
            ) : (
                <button className={cx(frameCss, tabCss)} onClick={() => updateLayout({ open: true })}>
                    ◆ AI LINK <span className={hotkeyCss}>[C]</span>
                </button>
            )}
        </>
    );
};

type ChatBodyProps = {
    chat: Chat<UIMessage>;
    inputRef: React.RefObject<HTMLTextAreaElement | null>;
    expanded: boolean;
    onExpand: () => void;
    onCollapse: () => void;
};

const ChatBody: React.FC<ChatBodyProps> = ({ chat, inputRef, expanded, onExpand, onCollapse }) => {
    const { messages, sendMessage, status, stop, error, regenerate, clearError, setMessages, addToolApprovalResponse } =
        useChat({
            chat,
            experimental_throttle: THROTTLE_MS,
        });
    const health = useBackendHealth();
    const [input, setInput] = React.useState('');
    const scrollRef = React.useRef<HTMLDivElement | null>(null);
    const busy = status === 'submitted' || status === 'streaming';

    React.useLayoutEffect(() => {
        const scroller = scrollRef.current;
        if (scroller == null) return;
        if (scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120)
            scroller.scrollTop = scroller.scrollHeight;
    }, [messages, status]);

    const send = (text: string) => {
        const trimmed = text.trim();
        if (trimmed === '' || busy) return;
        void sendMessage({ text: trimmed });
        setInput('');
        requestAnimationFrame(() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight }));
    };

    const approve = (id: string, approved: boolean) => {
        void Promise.resolve(addToolApprovalResponse({ id, approved })).then(() => saveMessages(chat.messages));
    };

    const clear = () => {
        stop();
        setMessages([]);
        clearMessages();
    };

    return (
        <div className={bodyCss}>
            <header className={headerCss}>
                {!expanded && (
                    <>
                        <span className={codeCss}>AI</span>
                        <span className={titleCss}>RABBIT // AI LINK</span>
                    </>
                )}
                <span className={healthCss} data-state={health.state} title={health.detail}>
                    ● {health.label}
                </span>
                {messages.length > 0 && (
                    <button className={iconCss} onClick={clear} title='Clear conversation'>
                        CLEAR
                    </button>
                )}
                <button className={iconCss} onClick={onExpand} title={expanded ? 'Restore' : 'Expand'}>
                    {expanded ? '⤡' : '⤢'}
                </button>
                <button className={iconCss} onClick={onCollapse} title='Collapse'>
                    ▾
                </button>
            </header>
            {!expanded && <div className={ticksCss} />}

            <div ref={scrollRef} className={scrollCss}>
                {messages.length === 0 && <StartScreen onAsk={send} />}
                <ChatActionsContext value={{ ask: send }}>
                    {messages.map((message) => (
                        <MessageView key={message.id} message={message} onApproval={approve} />
                    ))}
                </ChatActionsContext>
                {status === 'submitted' && <div className={thinkingCss}>▮ LINKING…</div>}
                {error != null && (
                    <div className={errorCss}>
                        <div>{`LINK ERROR · ${error.message}`}</div>
                        <div className={errorActionsCss}>
                            <button className={iconCss} onClick={() => void regenerate()}>
                                RETRY
                            </button>
                            <button className={iconCss} onClick={clearError}>
                                DISMISS
                            </button>
                        </div>
                    </div>
                )}
            </div>

            <form
                className={formCss}
                onKeyDown={(event) => {
                    if (event.key !== 'Escape') event.stopPropagation();
                }}
                onKeyUp={(event) => event.stopPropagation()}
                onSubmit={(event) => {
                    event.preventDefault();
                    send(input);
                }}>
                <textarea
                    ref={inputRef}
                    className={inputCss}
                    value={input}
                    rows={2}
                    placeholder='Ask or command… (Enter to send, Shift+Enter for a new line)'
                    onChange={(event) => setInput(event.target.value)}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter' && !event.shiftKey) {
                            event.preventDefault();
                            send(input);
                        } else if (event.key === 'Escape') {
                            event.currentTarget.blur();
                        }
                    }}
                />
                {busy ? (
                    <button type='button' className={sendCss} onClick={() => void stop()}>
                        ■ STOP REPLY
                    </button>
                ) : (
                    <button type='submit' className={sendCss} disabled={input.trim() === ''}>
                        SEND ›
                    </button>
                )}
            </form>
        </div>
    );
};

const MessageView: React.FC<{ message: UIMessage; onApproval: (id: string, approved: boolean) => void }> = React.memo(
    ({ message, onApproval }) => {
        const texts = message.parts.filter(isTextUIPart);
        if (message.role === 'user') return <div className={userTextCss}>{texts.map((part) => part.text).join('\n')}</div>;
        const tools = message.parts.filter(isToolUIPart);
        const results = tools.flatMap((part) => {
            const result = part.state === 'output-available' ? readResult(getToolName(part), part.output) : null;
            return result == null ? [] : [{ id: part.toolCallId, result }];
        });
        const charted = results.some(({ result }) => isChartLike(result));
        return (
            <div className={assistantCss}>
                {tools.length > 0 && <Activity parts={tools} />}
                {texts.map((part, i) => (
                    <Markdown key={i} text={part.text} />
                ))}
                {tools.map((part) =>
                    part.state === 'approval-requested' && part.approval.isAutomatic !== true ? (
                        <Approval
                            key={part.toolCallId}
                            name={getToolName(part)}
                            input={part.input}
                            reason={part.approval.requestReason}
                            onDecision={(approved) => onApproval(part.approval.id, approved)}
                        />
                    ) : null,
                )}
                {results.map(({ id, result }) => (
                    <ResultView key={id} result={result} quiet={charted && result.kind === 'table'} />
                ))}
            </div>
        );
    },
);

const stopPulse = keyframes`
    50% { box-shadow: 0 0 22px rgba(255, 90, 74, 0.75); }
`;

const stopCss = css`
    position: absolute;
    right: calc(var(--hud-column) + 24px);
    bottom: 12px;
    z-index: 20;
    padding: 6px 14px;
    border: 1px solid rgba(255, 90, 74, 0.45);
    background: var(--hud-bg);
    color: var(--hud-alert);
    font: inherit;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.16em;
    cursor: pointer;
    pointer-events: auto;

    &[data-moving='true'] {
        border-color: var(--hud-alert);
        background: rgba(255, 90, 74, 0.28);
        color: #fff;
        text-shadow: 0 0 8px rgba(255, 90, 74, 0.8);
        animation: ${stopPulse} 1.2s ease-in-out infinite;
    }

    &:hover {
        background: var(--hud-alert);
        color: #fff;
    }
`;

const tabCss = css`
    position: absolute;
    right: calc(var(--hud-column) + 128px);
    bottom: 12px;
    z-index: 20;
    border: none;
    font: inherit;
    font-weight: 600;
    letter-spacing: 0.12em;
    cursor: pointer;
    pointer-events: auto;
`;

const hotkeyCss = css`
    opacity: 0.5;
`;

const panelCss = css`
    position: absolute;
    right: calc(var(--hud-column) + 24px);
    bottom: 50px;
    z-index: 20;
    width: min(var(--chat-width), calc(100vw - 2 * var(--hud-column) - 48px));
    height: min(var(--chat-height), calc(100vh - 110px));
    display: flex;
    flex-direction: column;
    pointer-events: auto;
`;

const bodyCss = css`
    flex: 1;
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    text-transform: none;
`;

const resizeCss = css`
    position: absolute;
    left: -3px;
    top: -3px;
    width: 14px;
    height: 14px;
    cursor: nwse-resize;
    border-left: 2px solid var(--hud);
    border-top: 2px solid var(--hud);
    opacity: 0.6;

    &:hover {
        opacity: 1;
    }
`;

const headerCss = css`
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 6px;
    text-transform: uppercase;
`;

const codeCss = css`
    padding: 0 5px;
    font-size: 9px;
    line-height: 12px;
    color: #031016;
    background: var(--hud);
    clip-path: polygon(4px 0, calc(100% - 4px) 0, 100% 50%, calc(100% - 4px) 100%, 4px 100%, 0 50%);
    text-shadow: none;
`;

const titleCss = css`
    flex: 1;
    font-weight: 600;
`;

const healthCss = css`
    font-size: 8px;
    color: var(--hud-dim);

    &[data-state='ok'] {
        color: var(--hud);
    }

    &[data-state='degraded'] {
        color: var(--hud-amber);
    }

    &[data-state='down'] {
        color: var(--hud-alert);
    }
`;

const iconCss = css`
    padding: 1px 4px;
    border: none;
    background: none;
    color: var(--hud);
    font: inherit;
    font-size: 8.5px;
    letter-spacing: 0.08em;
    cursor: pointer;
    opacity: 0.6;

    &:hover {
        opacity: 1;
        background: var(--hud-faint);
    }
`;

const ticksCss = css`
    height: 4px;
    margin: 3px 0 4px;
    border-top: 1px solid var(--hud-faint);
    background: repeating-linear-gradient(90deg, var(--hud-faint) 0 1px, transparent 1px 6px);
`;

const scrollCss = css`
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding-right: 4px;
`;

const assistantCss = css`
    margin: 6px 0 14px;
`;

const userTextCss = css`
    margin: 10px 0 8px auto;
    width: fit-content;
    max-width: 85%;
    padding: 4px 8px;
    background: rgba(255, 181, 71, 0.08);
    box-shadow: inset -2px 0 0 var(--hud-amber);
    color: #fff;
    font-size: 11px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
`;

const pulse = keyframes`
    50% { opacity: 0.2; }
`;

const thinkingCss = css`
    font-size: 9px;
    letter-spacing: 0.12em;
    opacity: 0.7;
    animation: ${pulse} 1s steps(2) infinite;
`;

const errorCss = css`
    margin: 6px 0;
    padding: 4px 6px;
    border: 1px solid var(--hud-alert);
    color: var(--hud-alert);
    font-size: 10px;
`;

const errorActionsCss = css`
    display: flex;
    gap: 6px;
    margin-top: 4px;
`;

const formCss = css`
    display: flex;
    gap: 6px;
    margin-top: 6px;
`;

const inputCss = css`
    flex: 1;
    min-height: 34px;
    resize: none;
    padding: 4px 6px;
    border: 1px solid var(--hud-dim);
    background: rgba(0, 0, 0, 0.45);
    color: #fff;
    font: inherit;
    font-size: 11px;

    &:focus {
        border-color: var(--hud);
        box-shadow: 0 0 8px var(--hud-glow);
    }

    &::placeholder {
        color: var(--hud-dim);
        opacity: 0.6;
    }
`;

const sendCss = css`
    padding: 0 10px;
    border: 1px solid var(--hud);
    background: var(--hud-faint);
    color: var(--hud);
    font: inherit;
    font-weight: 700;
    letter-spacing: 0.1em;
    cursor: pointer;

    &:disabled {
        opacity: 0.35;
        cursor: default;
    }

    &:not(:disabled):hover {
        background: var(--hud);
        color: #031016;
    }
`;
