import type { AgentTool } from "@mariozechner/pi-agent-core";
import type { SandboxContext } from "../sandbox.js";
import { readSchema, paginateLines, resolveSandboxPath } from "./shared.js";

export function createSandboxReadTool(ctx: SandboxContext): AgentTool<typeof readSchema> {
	return {
		name: "read",
		label: "read",
		description:
			"Read the contents of a file in the sandbox VM. Output is limited to 2000 lines or ~100KB. Use offset/limit for large files.",
		parameters: readSchema,
		execute: async (
			_toolCallId: string,
			{ path, offset, limit }: { path: string; offset?: number; limit?: number },
			signal?: AbortSignal,
		) => {
			if (signal?.aborted) throw new Error("Operation aborted");

			const sandboxPath = resolveSandboxPath(path, ctx.repoPath);
			const text: string = await ctx.machine.readFile(sandboxPath);

			const page = paginateLines(text, offset, limit);
			let result = page.text;

			if (page.hasMore) {
				const nextOffset = page.shownRange[1] + 1;
				result += `\n\n[Showing lines ${page.shownRange[0]}-${page.shownRange[1]} of ${page.totalLines}. Use offset=${nextOffset} to continue.]`;
			}

			return {
				content: [{ type: "text", text: result }],
				details: undefined,
			};
		},
	};
}
