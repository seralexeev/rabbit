import React from 'react';

import { useWebSocket } from './WebSocketProvider.tsx';
import { useEvent } from '../hooks.ts';

export const useWebRTC = () => {
    const ws = useWebSocket();
    const pcRef = React.useRef<RTCPeerConnection | null>(null);
    const channelRef = React.useRef<RTCDataChannel | null>(null);
    
    const [isConnected, setIsConnected] = React.useState(false); // True when data channel is open
    const [connectionState, setConnectionState] = React.useState<RTCPeerConnectionState>('new');

    const setupPeerConnection = useEvent(() => {
        if (pcRef.current) {
            pcRef.current.close(); // Close any existing connection
            pcRef.current = null;
        }

        const pc = new RTCPeerConnection(); // Consider adding STUN/TURN server configuration here if needed
        pcRef.current = pc;

        pc.onconnectionstatechange = () => {
            setConnectionState(pc.connectionState);
            console.log('🔗 WebRTC connection state:', pc.connectionState);
            
            if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected' || pc.connectionState === 'closed') {
                setIsConnected(false);
                if (pc.connectionState !== 'closed') { // Avoid warning if closed intentionally
                    console.warn('🟡 WebRTC connection lost or failed.');
                }
            }
        };

        pc.onicecandidate = (event) => {
            if (event.candidate) {
                ws.send({ type: 'ice', ...event.candidate.toJSON() });
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

    const requestOfferFromRobot = useEvent(() => {
        console.log('🔄 Requesting WebRTC offer from robot');
        ws.send({ type: 'request_offer' });
    });

    React.useEffect(() => {
        const handleOffer = async (offerMessage: RTCSessionDescriptionInit) => {
            console.log('🔄 Received offer from robot, setting up connection...');
            const pc = setupPeerConnection(); // Creates/resets pcRef.current

            try {
                await pc.setRemoteDescription(new RTCSessionDescription(offerMessage));
                const answer = await pc.createAnswer();
                await pc.setLocalDescription(answer);
                ws.send(answer);
                console.log('📤 Answer sent to robot');
            } catch (error) {
                console.error('🔴 Error processing offer or creating answer:', error);
            }
        };

        const handleIceCandidate = async (iceCandidateMessage: RTCIceCandidateInit) => {
            if (pcRef.current && pcRef.current.signalingState !== 'closed') {
                try {
                    await pcRef.current.addIceCandidate(new RTCIceCandidate(iceCandidateMessage));
                } catch (e) {
                    console.warn('🟡 Failed to add ICE candidate:', e);
                }
            } else {
                console.warn('🟡 Received ICE candidate for a closed or non-existent peer connection. Signaling state:', pcRef.current?.signalingState);
            }
        };

        const unsubscribeWs = ws.subscribe(async (msg: any) => {
            try {
                switch (msg.type) {
                    case 'offer':
                        await handleOffer(msg);
                        break;
                    case 'ice':
                        await handleIceCandidate(msg);
                        break;
                    case 'ws_connected':
                        console.log('🟢 WebSocket connected, now requesting WebRTC offer.');
                        requestOfferFromRobot();
                        break;
                }
            } catch (error) {
                console.error('🔴 Error handling WebSocket message for WebRTC:', error);
            }
        });

        // Initial request for an offer, in case WebSocket was already connected
        // before this hook's subscription was established.
        // The 'ws_connected' message handles the primary flow.
        if (ws && typeof (ws as any).isConnected === 'function' && (ws as any).isConnected()) {
             // If WebSocketWrapper had an isConnected method. For now, rely on ws_connected or initial request.
             requestOfferFromRobot();
        } else if (ws) {
            // If ws object exists, assume we might need to kickstart if ws_connected was missed.
            // This is a bit of a guess; ideally, WebSocketProvider guarantees ws_connected fires post-subscription.
            // Given current WebSocketProvider, ws_connected should fire after connect() in its useEffect.
            // So, this initial call might be redundant if ws_connected is always caught.
            // However, it acts as a fallback.
             requestOfferFromRobot();
        }


        return () => {
            unsubscribeWs();
            if (pcRef.current) {
                pcRef.current.close();
                pcRef.current = null;
            }
            console.log('🧹 WebRTC connection cleaned up');
        };
    }, [ws, setupPeerConnection, requestOfferFromRobot]);

    const sendMessage = useEvent((message: unknown) => {
        if (channelRef.current?.readyState === 'open') {
            console.log('🔵 Sending message via WebRTC:', message);
            channelRef.current.send(JSON.stringify(message));
        } else {
            console.warn(`🟡 Cannot send message: data channel not open. State: ${channelRef.current?.readyState}, Connected: ${isConnected}`);
        }
    });

    return { connected: isConnected, sendMessage, connectionState };
};
