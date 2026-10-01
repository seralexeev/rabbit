import { css } from '@emotion/css';
import React from 'react';

const CATEGORIES: { code: string; title: string; prompts: string[] }[] = [
    {
        code: 'HL',
        title: 'Health',
        prompts: [
            'Give me a health check of the last run',
            'Was anything unusual in the last 10 minutes?',
            'Compare the last two runs',
            'Which streams dropped data in the last run?',
        ],
    },
    {
        code: 'PW',
        title: 'Power',
        prompts: [
            'Show battery voltage and current for the last run',
            'What uses the most power?',
            'What is the battery internal resistance?',
            'Did battery voltage and motor current misbehave together in the last 15 minutes?',
        ],
    },
    {
        code: 'MS',
        title: 'Motion & safety',
        prompts: [
            'Did the motors stall or spike in the last run?',
            'Were there any bumps or jolts?',
            'Did the robot get close to obstacles?',
            'How does steering affect motor current?',
        ],
    },
    {
        code: 'ZD',
        title: 'Perception / ZED',
        prompts: [
            'Did the camera lose tracking in the last run?',
            'Find anomalies in camera frame rate and tracking confidence',
            'Is the Jetson throttling or overheating?',
        ],
    },
    {
        code: 'NW',
        title: 'Network',
        prompts: [
            'Was the Wi-Fi link healthy in the last run?',
            'Find anomalies in Wi-Fi ping and uplink throughput',
            'Why was the video lagging around 11:32?',
        ],
    },
    {
        code: 'IV',
        title: 'Investigations',
        prompts: [
            'Why did the robot reboot at 11:00?',
            'Trace what caused battery sag in the last run',
            'Show the metric graph around motor current',
            'Why did the motor current go up around 11:34?',
            'How is Jetson CPU load related to tracking confidence?',
            'What could cause data gaps?',
        ],
    },
    {
        code: 'MI',
        title: 'Missions',
        prompts: [
            'Where are you and what are you doing?',
            'Did the robot complete its missions in the last run?',
            'Replay the last mission second by second',
            'Turn around and drive 0.5 m forward',
        ],
    },
];

export const StartScreen: React.FC<{ onAsk: (text: string) => void }> = ({ onAsk }) => (
    <div className={startCss}>
        <div className={titleCss}>ASK THE ROBOT ABOUT ITS DATA, OR TELL IT WHERE TO GO.</div>
        <div className={gridCss}>
            {CATEGORIES.map((category) => (
                <section key={category.code} className={categoryCss}>
                    <header>
                        <span className={codeCss}>{category.code}</span>
                        {category.title}
                    </header>
                    {category.prompts.map((prompt) => (
                        <button key={prompt} className={promptCss} onClick={() => onAsk(prompt)}>
                            › {prompt}
                        </button>
                    ))}
                </section>
            ))}
        </div>
    </div>
);

const startCss = css`
    padding: 6px 0;
`;

const titleCss = css`
    margin-bottom: 6px;
    font-size: 9px;
    letter-spacing: 0.1em;
    opacity: 0.6;
`;

const gridCss = css`
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
    gap: 10px 12px;
`;

const categoryCss = css`
    display: flex;
    flex-direction: column;
    gap: 1px;

    & > header {
        display: flex;
        align-items: center;
        gap: 5px;
        margin-bottom: 1px;
        font-size: 9px;
        font-weight: 600;
        letter-spacing: 0.12em;
        text-transform: uppercase;
    }
`;

const codeCss = css`
    padding: 0 4px;
    font-size: 8px;
    line-height: 11px;
    color: #031016;
    background: var(--hud-dim);
    text-shadow: none;
`;

const promptCss = css`
    padding: 2px 6px;
    border: none;
    background: none;
    color: var(--hud);
    font: inherit;
    font-size: 10px;
    text-align: left;
    text-transform: none;
    letter-spacing: 0.01em;
    cursor: pointer;
    opacity: 0.75;

    &:hover {
        opacity: 1;
        background: #0a2530;
        box-shadow: inset 2px 0 0 var(--hud);
    }
`;
