// sort-imports-ignore
/// <reference types="vite/client" />
/// <reference types="vite-plugin-svgr/client" />

import React from 'react';
import ReactDOM from 'react-dom/client';

import { App } from './app/App.tsx';
import './main.css';

const root = document.getElementById('root');

ReactDOM.createRoot(root!).render(
    <React.StrictMode>
        <App />
    </React.StrictMode>,
);
