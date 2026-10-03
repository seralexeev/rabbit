import type { Chat } from '@ai-sdk/react';
import { type UIMessage, isTextUIPart, isToolUIPart } from 'ai';

import { L } from '../log.ts';
import { saveMessages } from './persistence.ts';
import { VOICE_CALL_URL, VOICE_TOOL_URL } from './session.ts';

export type VoiceState = 'off' | 'connecting' | 'listening' | 'hearing' | 'thinking' | 'speaking';

type Part = UIMessage['parts'][number];

type FunctionCall = { call_id: string; name: string; arguments: string };

type ToolReply = { status: 'approval' } | { status: 'ok'; output: unknown; model: string } | { status: 'error'; error: string };

type ServerEvent = {
    type: string;
    item_id?: string;
    delta?: string;
    transcript?: string;
    item?: { id?: string; type?: string; role?: string } & Partial<FunctionCall>;
    response?: { id?: string; status?: string };
    error?: { message?: string };
};

const APPROVAL_PREFIX = 'voice-';
const APPROVAL_HINT = 'Say "да" or "approve" to confirm, "нет" or "deny" to refuse.';
const MAX_DECISION_WORDS = 5;

const APPROVE_WORDS = new Set([
    'да',
    'подтверждаю',
    'подтверди',
    'подтвердить',
    'одобряю',
    'поехали',
    'давай',
    'вперед',
    'выполняй',
    'approve',
    'approved',
    'yes',
    'yeah',
    'confirm',
    'confirmed',
    'go',
]);

const DENY_WORDS = new Set([
    'нет',
    'не',
    'отмена',
    'отмени',
    'отменить',
    'отклоняю',
    'стоп',
    'стой',
    'no',
    'deny',
    'cancel',
    'stop',
    'abort',
]);

export const spokenDecision = (text: string) => {
    const words = text.toLowerCase().replace(/ё/g, 'е').match(/\p{L}+/gu) ?? [];
    if (words.length === 0 || words.length > MAX_DECISION_WORDS) return null;
    if (words.some((word) => DENY_WORDS.has(word))) return false;
    return words.some((word) => APPROVE_WORDS.has(word)) ? true : null;
};
const MAX_HISTORY_CHARS = 4000;

const parseArgs = (args: string): unknown => {
    try {
        return args.trim() === '' ? {} : JSON.parse(args);
    } catch {
        return { raw: args };
    }
};

const textOf = (message: UIMessage) =>
    message.parts
        .filter(isTextUIPart)
        .map((part) => part.text)
        .join('\n')
        .trim();

const settleOpen = (part: Part): Part =>
    isToolUIPart(part) && (part.state === 'input-available' || part.state === 'approval-requested')
        ? ({ ...part, state: 'output-error', errorText: 'Voice session ended', approval: undefined } as unknown as Part)
        : part;

export class VoiceLink {
    #state: VoiceState = 'off';
    #error: string | null = null;
    #muted = false;
    #listeners = new Set<() => void>();
    #pc: RTCPeerConnection | null = null;
    #channel: RTCDataChannel | null = null;
    #mic: MediaStream | null = null;
    #audio: HTMLAudioElement | null = null;
    #turn: string | null = null;
    #textParts = new Map<string, number>();
    #pending = new Map<string, FunctionCall>();
    #approvalsAt = new Map<string, number>();
    #userItemsAt = new Map<string, number>();
    #responding = false;
    #owesReply = false;

    readonly chat: Chat<UIMessage>;

    constructor(chat: Chat<UIMessage>) {
        this.chat = chat;
    }

    get state() {
        return this.#state;
    }

    get error() {
        return this.#error;
    }

    get muted() {
        return this.#muted;
    }

    get active() {
        return this.#state !== 'off';
    }

    subscribe = (listener: () => void) => {
        this.#listeners.add(listener);
        return () => this.#listeners.delete(listener);
    };

    snapshot = () => `${this.#state}|${this.#muted}|${this.#error ?? ''}`;

    async start() {
        if (this.active) return;
        this.#error = null;
        this.#setState('connecting');
        try {
            this.#mic = await navigator.mediaDevices.getUserMedia({
                audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
            });
            const pc = new RTCPeerConnection();
            this.#pc = pc;
            const audio = new Audio();
            audio.autoplay = true;
            this.#audio = audio;
            pc.ontrack = (event) => {
                audio.srcObject = event.streams[0] ?? null;
            };
            for (const track of this.#mic.getAudioTracks()) pc.addTrack(track, this.#mic);
            const channel = pc.createDataChannel('oai-events');
            this.#channel = channel;
            channel.onmessage = (event) => this.#onEvent(JSON.parse(String(event.data)) as ServerEvent);
            channel.onopen = () => this.#setState('listening');
            pc.onconnectionstatechange = () => {
                if (pc.connectionState === 'failed' && this.#pc === pc) this.#fail('Voice link lost');
            };
            const offer = await pc.createOffer();
            await pc.setLocalDescription(offer);
            const response = await fetch(VOICE_CALL_URL, {
                method: 'POST',
                headers: { 'content-type': 'application/json' },
                body: JSON.stringify({ sdp: offer.sdp, history: this.#history() }),
            });
            const body = (await response.json()) as { sdp?: string; error?: string };
            if (!response.ok || body.sdp == null) throw new Error(body.error ?? `Voice call failed (${response.status})`);
            if (this.#pc !== pc) return;
            await pc.setRemoteDescription({ type: 'answer', sdp: body.sdp });
        } catch (error) {
            this.#fail(error instanceof Error ? error.message : String(error));
        }
    }

    stop() {
        this.#error = null;
        this.#channel?.close();
        this.#pc?.close();
        for (const track of this.#mic?.getTracks() ?? []) track.stop();
        if (this.#audio != null) this.#audio.srcObject = null;
        this.#channel = null;
        this.#pc = null;
        this.#mic = null;
        this.#audio = null;
        this.#turn = null;
        this.#textParts.clear();
        this.#pending.clear();
        this.#approvalsAt.clear();
        this.#userItemsAt.clear();
        this.#responding = false;
        this.#owesReply = false;
        this.#muted = false;
        this.chat.messages = this.chat.messages.map((message) => ({
            ...message,
            parts: message.parts.map(settleOpen),
        }));
        saveMessages(this.chat.messages);
        this.#setState('off');
    }

    toggleMute() {
        this.#muted = !this.#muted;
        for (const track of this.#mic?.getAudioTracks() ?? []) track.enabled = !this.#muted;
        this.#emit();
    }

    sendText(text: string) {
        const id = `text${crypto.randomUUID().replace(/-/g, '').slice(0, 28)}`;
        this.#onUserItem(id);
        this.#setUserText(id, text);
        this.#decideBySpeech(id, text);
        this.#send({
            type: 'conversation.item.create',
            item: { id, type: 'message', role: 'user', content: [{ type: 'input_text', text }] },
        });
        this.#send({ type: 'response.create' });
    }

    decide(approvalId: string, approved: boolean) {
        if (!approvalId.startsWith(APPROVAL_PREFIX)) return false;
        const call = this.#pending.get(approvalId.slice(APPROVAL_PREFIX.length));
        if (call == null || !this.#approvalsAt.delete(call.call_id)) return true;
        if (approved) {
            this.#updatePart(call.call_id, (part) => ({ ...part, state: 'input-available', approval: undefined }));
            void this.#runTool(call, true);
        } else {
            this.#updatePart(call.call_id, (part) => ({
                ...part,
                state: 'output-error',
                errorText: 'Denied by the operator',
                approval: undefined,
            }));
            this.#reply(call.call_id, JSON.stringify({ denied: true, reason: 'The operator denied this action.' }));
        }
        return true;
    }

    #emit() {
        for (const listener of this.#listeners) listener();
    }

    #setState(state: VoiceState) {
        if (this.#state === state) return;
        this.#state = state;
        this.#emit();
    }

    #fail(message: string) {
        L.error('Voice link failed', message);
        this.stop();
        this.#error = message;
        this.#emit();
    }

    #send(event: Record<string, unknown>) {
        if (this.#channel?.readyState === 'open') this.#channel.send(JSON.stringify(event));
    }

    #history() {
        return this.chat.messages
            .filter((message) => message.role === 'user' || message.role === 'assistant')
            .map((message) => ({ role: message.role, text: textOf(message).slice(0, MAX_HISTORY_CHARS) }))
            .filter((turn) => turn.text !== '');
    }

    #updateMessage(id: string, fn: (message: UIMessage) => UIMessage) {
        this.chat.messages = this.chat.messages.map((message) => (message.id === id ? fn(message) : message));
    }

    #updatePart(callId: string, fn: (part: Record<string, unknown>) => Record<string, unknown>) {
        this.chat.messages = this.chat.messages.map((message) =>
            message.parts.some((part) => isToolUIPart(part) && part.toolCallId === callId)
                ? {
                      ...message,
                      parts: message.parts.map((part) =>
                          isToolUIPart(part) && part.toolCallId === callId
                              ? (fn(part as unknown as Record<string, unknown>) as unknown as Part)
                              : part,
                      ),
                  }
                : message,
        );
    }

    #turnMessage() {
        if (this.#turn == null) {
            const id = `voice-${crypto.randomUUID()}`;
            this.chat.messages = [...this.chat.messages, { id, role: 'assistant', parts: [] }];
            this.#turn = id;
        }
        return this.#turn;
    }

    #addPart(part: Part) {
        const id = this.#turnMessage();
        let index = -1;
        this.#updateMessage(id, (message) => {
            index = message.parts.length;
            return { ...message, parts: [...message.parts, part] };
        });
        return index;
    }

    #onEvent(event: ServerEvent) {
        switch (event.type) {
            case 'input_audio_buffer.speech_started':
                this.#setState('hearing');
                break;
            case 'input_audio_buffer.speech_stopped':
                this.#setState('thinking');
                break;
            case 'conversation.item.added':
            case 'conversation.item.created':
                if (event.item?.role === 'user' && event.item.id != null) this.#onUserItem(event.item.id);
                break;
            case 'conversation.item.input_audio_transcription.completed':
                if (event.item_id != null) {
                    this.#setUserText(event.item_id, event.transcript?.trim() || '…');
                    this.#decideBySpeech(event.item_id, event.transcript ?? '');
                }
                break;
            case 'response.created':
                this.#responding = true;
                this.#setState('thinking');
                break;
            case 'response.output_audio_transcript.delta':
            case 'response.output_text.delta':
                if (event.item_id != null && event.delta != null) this.#appendText(event.item_id, event.delta);
                break;
            case 'output_audio_buffer.started':
                this.#setState('speaking');
                break;
            case 'output_audio_buffer.stopped':
            case 'output_audio_buffer.cleared':
                this.#setState('listening');
                break;
            case 'response.output_item.done':
                if (event.item?.type === 'function_call') this.#onFunctionCall(event.item as FunctionCall);
                break;
            case 'response.done':
                this.#responding = false;
                if (this.#state === 'thinking' && this.#pending.size === 0) this.#setState('listening');
                saveMessages(this.chat.messages);
                this.#continue();
                break;
            case 'error':
                L.warn('Voice event error', event.error?.message);
                break;
        }
    }

    #onUserItem(itemId: string) {
        if (this.chat.messages.some((message) => message.id === itemId)) return;
        this.#userItemsAt.set(itemId, performance.now());
        this.#turn = null;
        this.#textParts.clear();
        this.chat.messages = [...this.chat.messages, { id: itemId, role: 'user', parts: [{ type: 'text', text: '…' }] }];
    }

    #setUserText(itemId: string, text: string) {
        this.#updateMessage(itemId, (message) => ({ ...message, parts: [{ type: 'text', text }] }));
    }

    #decideBySpeech(itemId: string, text: string) {
        const approved = spokenDecision(text);
        const saidAt = this.#userItemsAt.get(itemId);
        this.#userItemsAt.delete(itemId);
        if (approved == null || saidAt == null) return;
        const waiting = [...this.#approvalsAt].filter(([, requestedAt]) => requestedAt < saidAt);
        const [only] = waiting;
        if (waiting.length === 1 && only != null) this.decide(`${APPROVAL_PREFIX}${only[0]}`, approved);
    }

    #appendText(itemId: string, delta: string) {
        const index = this.#textParts.get(itemId);
        if (index == null) {
            this.#textParts.set(itemId, this.#addPart({ type: 'text', text: delta, state: 'streaming' }));
            return;
        }
        this.#updateMessage(this.#turnMessage(), (message) => ({
            ...message,
            parts: message.parts.map((part, i) =>
                i === index && isTextUIPart(part) ? { ...part, text: part.text + delta } : part,
            ),
        }));
    }

    #onFunctionCall(call: FunctionCall) {
        if (this.#pending.has(call.call_id)) return;
        this.#pending.set(call.call_id, call);
        this.#addPart({
            type: `tool-${call.name}`,
            toolCallId: call.call_id,
            state: 'input-available',
            input: parseArgs(call.arguments),
        } as unknown as Part);
        void this.#runTool(call, false);
    }

    async #runTool(call: FunctionCall, approved: boolean) {
        let reply: ToolReply;
        try {
            const response = await fetch(VOICE_TOOL_URL, {
                method: 'POST',
                headers: { 'content-type': 'application/json' },
                body: JSON.stringify({ ...call, approved }),
            });
            const body = (await response.json()) as ToolReply | { error: string };
            reply = 'status' in body ? body : { status: 'error', error: body.error };
        } catch (error) {
            reply = { status: 'error', error: error instanceof Error ? error.message : String(error) };
        }
        if (!this.#pending.has(call.call_id)) return;
        if (reply.status === 'approval') {
            this.#updatePart(call.call_id, (part) => ({
                ...part,
                state: 'approval-requested',
                approval: { id: `${APPROVAL_PREFIX}${call.call_id}`, requestReason: APPROVAL_HINT },
            }));
            this.#approvalsAt.set(call.call_id, performance.now());
            return;
        }
        if (reply.status === 'ok') {
            this.#updatePart(call.call_id, (part) => ({ ...part, state: 'output-available', output: reply.output }));
            this.#reply(call.call_id, reply.model);
        } else {
            this.#updatePart(call.call_id, (part) => ({ ...part, state: 'output-error', errorText: reply.error }));
            this.#reply(call.call_id, JSON.stringify({ error: reply.error }));
        }
    }

    #reply(callId: string, output: string) {
        this.#pending.delete(callId);
        this.#send({ type: 'conversation.item.create', item: { type: 'function_call_output', call_id: callId, output } });
        this.#owesReply = true;
        this.#continue();
    }

    #continue() {
        if (this.#responding || !this.#owesReply || [...this.#pending.keys()].some((id) => !this.#approvalsAt.has(id))) return;
        this.#owesReply = false;
        this.#send({ type: 'response.create' });
    }
}
