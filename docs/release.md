# GitHub and website release

## GitHub

Create `compassionate-ai-lab/cai-mcp-guardrail` with the visibility you intend, then put the extracted project's contents at the repository root. Include the hidden `.github/workflows/test.yml` and `.gitignore`. Use the existing README and MIT license from this bundle. Review the license choice and run the tests before tagging `v0.2.0`. Use `docs/release-notes.md` as the release body.

Suggested GitHub description:

> Local MCP guardrail for No-Harm tool policies, single-use human approvals, and verifiable audit records. A Compassionate AI Lab reference implementation.

Suggested topics: `model-context-protocol`, `mcp`, `agentic-ai`, `ai-safety`, `compassionate-ai`, `human-in-the-loop`, `python`.

After publishing, add the following project entry to the Compassionate AI Lab organization profile.

```markdown
- [Compassionate AI MCP Guardrail](https://github.com/compassionate-ai-lab/cai-mcp-guardrail) — Run a local demonstration of No-Harm tool policies, exact-action approval, and audit verification.
```

## Websites

For a standalone demonstration, host `docs/index.html` as a static page. It needs no server API, authentication, or external scripts. If using GitHub Pages, configure the repository's Pages source to publish from the default branch and the `/docs` directory, then use the generated page URL in your article.

For amitray.com or SriAmitRay.com, paste `docs/wordpress.html` into a Custom HTML block. The text is ready to use. Add buttons for the repository, the release archive, and the browser simulation using their final public URLs after publishing them. Suggested post title is **Compassionate AI MCP Guardrail**. Suggested slug is `compassionate-ai-mcp-guardrail`.

Suggested meta description:

> Try Compassionate AI Lab’s local MCP guardrail for AI agents. See how No-Harm policies block unsafe tool calls and require approval for consequential actions.

[GitHub Pages publishing source documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
