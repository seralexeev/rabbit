import React from 'react';
import { z } from 'zod/v4';

import { useEvent } from '../hooks.ts';
import { useNats } from './NatsProvider.tsx';

export const useWebRTC = () => {
    const nc = useNats();
    const pcRef = React.useRef<RTCPeerConnection | null>(null);
    const channelRef = React.useRef<RTCDataChannel | null>(null);

    const [isConnected, setIsConnected] = React.useState(false);
    const [connectionState, setConnectionState] = React.useState<RTCPeerConnectionState>('new');

    const setupPeerConnection = useEvent(() => {
        if (pcRef.current) {
            pcRef.current.close();
            pcRef.current = null;
        }

        const pc = new RTCPeerConnection({
            iceServers: [{ urls: 'stun:stun.l.google.com:19302' }, { urls: 'stun:stun1.l.google.com:19302' }],
        }); // Consider adding STUN/TURN server configuration here if needed
        pcRef.current = pc;

        pc.onconnectionstatechange = () => {
            setConnectionState(pc.connectionState);
            console.log('🔗 WebRTC connection state:', pc.connectionState);

            if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected' || pc.connectionState === 'closed') {
                setIsConnected(false);
                if (pc.connectionState !== 'closed') {
                    // Avoid warning if closed intentionally
                    console.warn('🟡 WebRTC connection lost or failed.');
                }
            }
        };

        pc.onicecandidate = (event) => {
            if (event.candidate) {
                nc.publish('webrtc.signaling', JSON.stringify({ type: 'ice', ...event.candidate.toJSON() }));
            }
        };

        pc.ondatachannel = (event) => {
            const channel = event.channel;
            channelRef.current = channel;

            channel.onopen = () => {
                console.log('🟢 Data channel opened');
                setIsConnected(true);
            };

            channel.onmessage = (e) => {
                // Optionally, handle incoming messages from robot here if needed
                console.log('🔵 Data channel message received:', e.data);
            };

            channel.onclose = () => {
                console.log('🟡 Data channel closed');
                setIsConnected(false);
            };

            channel.onerror = (error) => {
                console.error('🔴 Data channel error:', error);
                setIsConnected(false);
            };
        };
        return pc;
    });

    React.useEffect(() => {
        const requestOfferFromRobot = () => {
            console.log('🔄 Requesting WebRTC offer from robot');
            nc.publish('webrtc.signaling', JSON.stringify({ type: 'request_offer' }));
        };

        const handleOffer = async (offerMessage: RTCSessionDescriptionInit) => {
            const pc = setupPeerConnection();

            await pc.setRemoteDescription(new RTCSessionDescription(offerMessage));
            const answer = await pc.createAnswer();
            await pc.setLocalDescription(answer);
            nc.publish('webrtc.signaling', JSON.stringify(answer));
            console.log('📤 Answer sent to robot');
        };

        const handleIceCandidate = async (iceCandidateMessage: RTCIceCandidateInit) => {
            if (pcRef.current == null || pcRef.current.signalingState === 'closed') {
                console.warn('🟡 Received ICE candidate for a closed or non-existent peer connection');
                return;
            }

            await pcRef.current.addIceCandidate(new RTCIceCandidate(iceCandidateMessage));
        };

        const subscription = nc.subscribe('webrtc.signaling', {
            callback: (err, raw) => {
                if (err) {
                    console.error('🔴 Error receiving WebRTC signaling message:', err);
                    return;
                }

                const parsed = Message.safeParse(raw.json());
                if (!parsed.success) {
                    console.error('🔴 Invalid WebRTC signaling message:', parsed.error);
                    return;
                }

                const msg = parsed.data;

                try {
                    const t = msg.type;
                    switch (t) {
                        case 'offer': {
                            console.log('🟢 Received offer from robot, setting up connection...');
                            void handleOffer(msg);
                            return;
                        }
                        case 'ice': {
                            console.log('🟢 Received ICE candidate from robot');
                            void handleIceCandidate(msg);
                            return;
                        }
                        case 'ws_connected': {
                            console.log('🟢 WebSocket connected, requesting WebRTC offer from robot');
                            requestOfferFromRobot();
                            return;
                        }
                        default:
                            t satisfies never; // Ensure all cases are handled
                    }
                } catch (error) {
                    console.error('🔴 Error handling WebSocket message for WebRTC:', error);
                }
            },
        });

        // Initial request for an offer, in case WebSocket was already connected
        // before this hook's subscription was established.
        // The 'ws_connected' message handles the primary flow.
        if (nc && typeof (nc as any).isConnected === 'function' && (nc as any).isConnected()) {
            // If WebSocketWrapper had an isConnected method. For now, rely on ws_connected or initial request.
            requestOfferFromRobot();
        } else if (nc) {
            // If ws object exists, assume we might need to kickstart if ws_connected was missed.
            // This is a bit of a guess; ideally, WebSocketProvider guarantees ws_connected fires post-subscription.
            // Given current WebSocketProvider, ws_connected should fire after connect() in its useEffect.
            // So, this initial call might be redundant if ws_connected is always caught.
            // However, it acts as a fallback.
            requestOfferFromRobot();
        }

        return () => {
            subscription.unsubscribe();

            if (pcRef.current) {
                pcRef.current.close();
                pcRef.current = null;
            }
            console.log('🧹 WebRTC connection cleaned up');
        };
    }, [nc, setupPeerConnection]);

    const sendMessage = useEvent((message: unknown) => {
        if (channelRef.current?.readyState === 'open') {
            console.log('🔵 Sending message via WebRTC:', message);
            channelRef.current.send(JSON.stringify(message));
        } else {
            console.warn(
                `🟡 Cannot send message: data channel not open. State: ${channelRef.current?.readyState}, Connected: ${isConnected}`,
            );
        }
    });

    return { connected: isConnected, sendMessage, connectionState };
};

const Message = z.discriminatedUnion('type', [
    z.object({ type: z.literal('offer'), sdp: z.string() }),
    z.object({ type: z.literal('ice'), candidate: z.string(), sdpMLineIndex: z.number().optional() }),
    z.object({ type: z.literal('ws_connected') }),
]);
