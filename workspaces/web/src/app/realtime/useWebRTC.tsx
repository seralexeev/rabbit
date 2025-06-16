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
            console.log('� WebRTC connection state:', pc.connectionState);
            
            if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
                setConnected(false);
                console.log('� WebRTC connection lost, will retry on next offer');
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
                console.log('� Data channel opened');
                setConnected(true);
            };
            
            channel.onmessage = (e) => {
                console.log('� Message received:', e.data);
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
        const pc = setupPeerConnection();

        const unsubscribe = ws.subscribe(async (msg: any) => {
            try {
                if (msg.type === 'offer') {
                    // Reset connection if needed
                    if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
                        console.log('� Resetting peer connection for new offer');
                        const newPc = setupPeerConnection();
                        await newPc.setRemoteDescription(new RTCSessionDescription(msg));
                        const answer = await newPc.createAnswer();
                        await newPc.setLocalDescription(answer);
                        ws.send(answer);
                        console.log('� Answer sent to robot');
                    } else {
                        // Handle offer normally
                        await pc.setRemoteDescription(new RTCSessionDescription(msg));
                        const answer = await pc.createAnswer();
                        await pc.setLocalDescription(answer);
                        ws.send(answer);
                        console.log('� Answer sent to robot');
                    }
                } else if (msg.type === 'ice') {
                    try {
                        await pc.addIceCandidate(new RTCIceCandidate(msg));
                    } catch (e) {
                        console.warn('🟡 Failed to add ICE candidate', e);
                    }
                } else if (msg.type === 'ws_connected') {
                    // WebSocket connection established - request WebRTC connection
                    console.log('🟢 WebSocket connected, requesting WebRTC connection');
                    requestConnection();
                }
            } catch (error) {
                console.error('🔴 Error handling WebRTC message:', error);
            }
        });

        // Request connection immediately when effect runs
        requestConnection();

        return () => {
            unsubscribe();
            if (pcRef.current) {
                pcRef.current.close();
            }
        };
    }, [ws, setupPeerConnection, requestConnection]);

    const sendMessage = useEvent((message: unknown) => {
        console.log('� Sending message:', message);
        if (channelRef.current?.readyState === 'open' && connected) {
            channelRef.current.send(JSON.stringify(message));
        } else {
            console.warn('🟡 Cannot send message: data channel not open');
        }
    });

    return { connected, sendMessage, connectionState };
};
