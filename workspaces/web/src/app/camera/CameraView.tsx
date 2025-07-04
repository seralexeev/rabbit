import React from 'react';

import { useNats } from '../realtime/NatsProvider.tsx';

export const CameraView: React.FC = () => {
    const nc = useNats();
    const ref = React.useRef<HTMLImageElement | null>(null);

    React.useEffect(() => {
        let last_img_url: string | null = null;

        const cleanup = (new_img_url: string | null) => {
            if (last_img_url != null) {
                URL.revokeObjectURL(last_img_url);
            }

            last_img_url = new_img_url;
        };

        const subscription = nc.subscribe('rabbit.camera.image.webp', {
            callback: (_, msg) => {
                const blob = new Blob([msg.data], { type: 'image/webp' });
                const img_url = URL.createObjectURL(blob);

                if (ref.current != null) {
                    ref.current.src = img_url;
                }

                cleanup(img_url);
            },
        });

        return () => {
            subscription.unsubscribe();
            cleanup(null);
        };
    }, [nc]);

    return (
        <img
            ref={ref}
            alt='Camera feed'
            style={{
                maxWidth: '100%',
                height: 'auto',
                borderRadius: '5px',
                boxShadow: '0 4px 8px rgba(0,0,0,0.1)',
            }}
        />
    );
};
