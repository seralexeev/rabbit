import React from 'react';

import { useWebSocket } from './WebSocketProvider.tsx';
import { useEvent } from '../hooks.ts';

export const useWebRTC = () => {
    const ws = useWebSocket();
    const pcRef = React.useRef<RTCPeerConnection | null>(null);
    const [connected, setConnected] = React.useState(false);
    const channelRef = React.useRef<RTCDataChannel | null>(null);
    const [connectionState, setConnectionState] = React.useState<RTCPeerConnectionState>('new');

    const setupPeerConnection = useEvent(() => {
        // Close existing connection if any
        if (pcRef.current) {
            pcRef.current.close();
        }

        const pc = new RTCPeerConnection();
        pcRef.current = pc;

        // Monitor connection state
        pc.onconnectionstatechange = () => {
            setConnectionState(pc.connectionState);
            console.log('🔗 WebRTC connection state:', pc.connectionState);
            
            if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
                setConnected(false);
                console.warn('🟡 WebRTC connection lost, will retry on next offer');
            }
        };

        pc.onicecandidate = (event) => {
            if (event.candidate) {
                ws.send({ type: 'ice', ...event.candidate.toJSON() });
            }
        };

        // Handle incoming data channels from robot
        pc.ondatachannel = (event) => {
            const channel = event.channel;
            channelRef.current = channel;
            
            channel.onopen = () => {
                console.log('🟢 Data channel opened');
                setConnected(true);
            };
            
            channel.onmessage = (e) => {
                console.log('🔵 Message received:', e.data);
            };
            
            channel.onclose = () => {
                console.log('🟡 Data channel closed');
                setConnected(false);
            };
            
            channel.onerror = (error) => {
                console.error('🔴 Data channel error:', error);
                setConnected(false);
            };
        };

        return pc;
    });

    // Request WebRTC connection when WebSocket connects
    const requestConnection = useEvent(() => {
        console.log('🔄 Requesting WebRTC connection from robot');
        ws.send({ type: 'request_offer' });
    });

    React.useEffect(() => {
        setupPeerConnection(); // Initial setup

        const unsubscribe = ws.subscribe(async (msg: any) => {
            try {
                if (msg.type === 'offer') {
                    console.log('🔄 Received offer from robot - setting up new connection');
                    const currentPC = setupPeerConnection(); // Ensures pcRef.current is fresh
                    if (!currentPC) {
                        console.error('🔴 Failed to setup peer connection for offer');
                        return;
                    }
                    await currentPC.setRemoteDescription(new RTCSessionDescription(msg));
                    const answer = await currentPC.createAnswer();
                    await currentPC.setLocalDescription(answer);
                    ws.send(answer);
                    console.log('📤 Answer sent to robot');
                } else if (msg.type === 'ice') {
                    if (pcRef.current && pcRef.current.signalingState !== 'closed') {
                        try {
                            await pcRef.current.addIceCandidate(new RTCIceCandidate(msg));
                        } catch (e) {
                            console.warn('🟡 Failed to add ICE candidate', e);
                        }
                    } else {
                        console.warn('🟡 Received ICE candidate for a closed or non-existent peer connection. Current state:', pcRef.current?.signalingState);
                    }
                } else if (msg.type === 'ws_connected') {
                    console.log('🟢 WebSocket connected, requesting WebRTC connection');
                    requestConnection();
                }
            } catch (error) {
                console.error('🔴 Error handling WebRTC message:', error);
            }
        });

        requestConnection();

        return () => {
            unsubscribe();
            if (pcRef.current) {
                pcRef.current.close();
                pcRef.current = null; // Nullify the ref
            }
        };
    }, [ws, setupPeerConnection, requestConnection]);

    const sendMessage = useEvent((message: unknown) => {
        console.log('🔵 Sending message:', message);
        if (channelRef.current?.readyState === 'open' && connected) {
            channelRef.current.send(JSON.stringify(message));
        } else {
            console.warn('🟡 Cannot send message: data channel not open');
        }
    });

    return { connected, sendMessage, connectionState };
};
