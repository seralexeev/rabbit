import { McpServer } from '@modelcontextprotocol/server';
import { serveStdio } from '@modelcontextprotocol/server/stdio';
import { readFileSync } from 'node:fs';

import { askTool } from '../agent/ask.ts';
import { describeForModel } from '../errors.ts';
import { type ForgeTool, modelView } from '../forge_tool.ts';
import { log } from '../log.ts';
import { DATA_TOOLS } from '../tools.ts';

const instructions = readFileSync(
  new URL('mcp_instructions.md', import.meta.url),
  'utf8',
);

const MCP_TOOLS: Record<string, ForgeTool> = { ...DATA_TOOLS, ask: askTool };

const textResult = (value: unknown, isError = false) => ({
  content: [{ type: 'text' as const, text: JSON.stringify(value) }],
  ...(isError ? { isError: true } : {}),
});

const createServer = () => {
  const server = new McpServer(
    { name: 'forge', title: 'Forge', version: '0.1.0' },
    { instructions },
  );
  for (const [name, tool] of Object.entries(MCP_TOOLS).filter(
    ([, candidate]) => candidate.requiresApproval !== true,
  )) {
    server.registerTool(
      name,
      {
        title: tool.title,
        description: tool.description,
        inputSchema: tool.input,
        annotations: { readOnlyHint: true, openWorldHint: false },
      },
      async (input: unknown) => {
        try {
          return textResult(
            modelView(tool, await tool.run(tool.input.parse(input))),
          );
        } catch (error) {
          log('MCP tool failed', { tool: name, ...describeForModel(error) });
          return textResult(describeForModel(error), true);
        }
      },
    );
  }
  return server;
};

export const serveMcp = () => {
  serveStdio(createServer);
};
