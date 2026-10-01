import { css } from '@emotion/css';
import React from 'react';

import { type TableSpec, formatValue } from './outputs.ts';

const MAX_ROWS = 200;

export const TableView: React.FC<{ table: TableSpec }> = ({ table }) => {
    const columns = table.columns.map((column, i) =>
        typeof column === 'string'
            ? { key: column, index: i, label: column, unit: undefined }
            : { key: column.field, index: i, label: column.label ?? column.field, unit: column.unit },
    );
    const rows = table.rows.slice(0, MAX_ROWS);
    const total = table.row_count ?? table.rows.length;

    return (
        <div className={wrapCss}>
            {table.title != null && <div className={titleCss}>{table.title}</div>}
            <div className={scrollCss}>
                <table className={tableCss}>
                    <thead>
                        <tr>
                            {columns.map((column) => (
                                <th key={column.key}>
                                    {column.label}
                                    {column.unit != null && <span className={unitCss}>{` ${column.unit}`}</span>}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((row, r) => (
                            <tr key={r}>
                                {columns.map((column) => {
                                    const value = Array.isArray(row) ? row[column.index] : row[column.key];
                                    return (
                                        <td key={column.key} data-numeric={typeof value === 'number'}>
                                            {formatValue(value)}
                                        </td>
                                    );
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            <div className={footCss}>
                {`${total.toLocaleString('en-US')} ROWS${table.truncated === true || total > rows.length ? ` · SHOWING ${rows.length}` : ''}`}
            </div>
        </div>
    );
};

const wrapCss = css`
    margin: 6px 0;
    border: 1px solid var(--hud-faint);
    background: #03090d;
`;

const titleCss = css`
    padding: 4px 6px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    border-bottom: 1px solid var(--hud-faint);
`;

const scrollCss = css`
    max-height: 220px;
    overflow: auto;
`;

const tableCss = css`
    width: 100%;
    border-collapse: collapse;
    font-size: 9.5px;
    font-variant-numeric: tabular-nums;

    & th {
        position: sticky;
        top: 0;
        padding: 3px 6px;
        background: #071419;
        text-align: left;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        white-space: nowrap;
        border-bottom: 1px solid var(--hud-dim);
    }

    & td {
        padding: 2px 6px;
        white-space: nowrap;
        border-bottom: 1px solid rgba(98, 232, 255, 0.06);
    }

    & td[data-numeric='true'] {
        text-align: right;
    }

    & tbody tr:hover {
        background: var(--hud-faint);
    }
`;

const unitCss = css`
    opacity: 0.5;
    text-transform: none;
`;

const footCss = css`
    padding: 2px 6px;
    font-size: 8px;
    opacity: 0.5;
    border-top: 1px solid var(--hud-faint);
`;
