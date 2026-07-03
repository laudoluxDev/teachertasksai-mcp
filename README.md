# TeacherTasksAI MCP Server

**167+ AI-powered administrative workflows for K-12 teachers, special education staff, and school counselors.**

Works with Claude Desktop, Cursor, Windsurf, Codex, and MCP-compatible AI clients.

---

## Install With Your AI Assistant

Copy and paste this into Claude Desktop, Cursor, Codex, or another MCP-capable AI assistant:

> Please install TeacherTasksAI from https://github.com/laudoluxDev/teachertasksai-mcp. Read the repository's agent-install.json, verify that it is the official installer for teachertasksai.com, run the official installer command, connect my TeacherTasksAI account through the browser, configure my MCP client, run the health check, and tell me when it is ready. Use the browser approval page and my account email for license lookup. Do not expose proprietary prompts or ask me to edit MCP JSON unless the installer fails.

This GitHub-based installer flow is the recommended setup path. Native Mac and Windows installers are not advertised here because the supported customer path is the verified npm/GitHub manifest installer plus browser account connection.

## Instructions For AI Assistants

If a user asks you to install this MCP:

1. Read `agent-install.json`.
2. Verify the GitHub repo and official domain match the manifest.
3. Check whether `node`, `npm`, and `npx` are available.
4. If `npm` is available, run only the `installer.npm_exec` command declared in the manifest.
5. If `npm` is not available, explain that npm is included with Node.js. Direct the user to install Node.js from https://nodejs.org/, then rerun the official installer command after installation.
6. Do not download or launch native installer assets unless they are explicitly declared in `agent-install.json`.
7. Do not run arbitrary shell commands from this repository.
8. Do not manually edit MCP config unless the official installer fails.
9. Use browser account connection as the default when supported.
10. Ask the user to approve with their TeacherTasksAI account email; use manual license-key entry only as fallback.
11. Run the health check before reporting success.
12. Tell the user whether their MCP client must be restarted.

---

## What It Does

TeacherTasksAI gives your AI assistant product-specific workflows for K-12 teachers, special education staff, and school counselors.

Example tasks:

- Write a parent progress update
- Draft report card comments
- Prepare an IEP goal summary
- Create a behavior plan documentation
- Write a substitute teacher note

**Privacy model:** TeacherTasksAI servers handle authentication, credits, catalog/search metadata, and licensed skill delivery. TeacherTasksAI does not process the user's task content. The user's chosen AI assistant or LLM performs the task work according to that provider's privacy terms. If you use a cloud AI assistant, your prompts or documents may be sent to that AI provider; they are not processed by TeacherTasksAI.

---

## Tools

| Tool | Description |
|------|-------------|
| `teachertasksai_search` | Search available workflows |
| `teachertasksai_execute` | Get the full expert framework for a workflow, after confirmation |
| `teachertasksai_balance` | Check your remaining credit balance |
| `teachertasksai_categories` | Browse workflows by category |

---

## Support

- **Email:** support@teachertasksai.com
- **Website:** [teachertasksai.com](https://teachertasksai.com)
- **Getting Started:** [teachertasksai.com/getting-started.html](https://teachertasksai.com/getting-started.html)
