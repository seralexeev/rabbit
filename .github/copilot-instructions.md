# Coding Style & Project Guidelines

## Project Overview

Robot control system using WebRTC and gamepad input.

## Architecture

- `workspaces/server/` - WebSocket signaling server (Node.js)
- `workspaces/web/` - React gamepad interface
- `workspaces/rabbit/` - Python robot client
- `workspaces/pcb/` - KiCad hardware

## Coding Preferences

- **Cross-platform compatibility**: Always ensure macOS development works
- **Platform-specific dependencies**: Use `[project.optional-dependencies]` for Linux-only packages
- **Type safety**: Add type hints and handle None checks properly

## Common Patterns

- Robot initiates WebRTC connections (offer first)
- Gamepad commands sent via data channels
- Use `uv` for Python dependency management
- Run signaling server using `yarn workspace @rabbit/web dev`
- Use `uv run src/client.py` to start the robot client
- Use `uv sync` to install dependencies in Python workspaces
- Use `yarn` for Node.js dependencies
- Use English for code comments and documentation
- Do not create README for instructions
- Respond in the same language as the question
- Use TypeScript for Node.js and React projects
    - Always use access modifiers (public, private, protected) for class members
    - For simple array types, use `string` `SomeType` use `...[]`
    - For complex types `{ id: string }` or `SomeType<User>` use `Array<...>`
    - Always check for null or undefined using `if (value != null)`
    - Always use curly braces for single-line blocks
- Use Python for the robot code
- React
    - Never use `React.useCallback` or `React.useMemo` unless absolutely necessary, use `useEvent` from `workspaces/web/src/app/hooks.ts` instead
    - Always use `React` as namespace import (e.g., `import React from 'react'`) and use `React.FC` for functional components
    - Always access anything from react using `React` namespace (e.g., `React.useState`, `React.useEffect`)
- Run projects:
    - Use `yarn workspace @rabbit/web dev` for the web interface
    - Use `yarn workspace @rabbit/server dev` for the signaling server
    - Use `uv run src/client.py` for the robot client

### React

- Use children={children} when children is a variable and not a JSX literal
