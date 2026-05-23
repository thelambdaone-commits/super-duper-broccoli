import type { AgentTool } from "@mariozechner/pi-agent-core";
import type { SandboxContext } from "../sandbox.js";
import { writeSchema, resolveSandboxPath } from "./shared.js";

export function createSandboxWriteTool(ctx: SandboxContext): AgentTool<typeof writeSchema> {
	return {
		name: "write",
		label: "write",
		description:
			"Write content to a file in the sandbox VM. Creates the file if it doesn't exist, overwrites if it does. Parent directories are created automatically.",
		parameters: writeSchema,
		execute: async (
			_toolCallId: string,
			{ path, content, createDirs }: { path: string; content: string; createDirs?: boolean },
			signal?: AbortSignal,
		) => {
			if (signal?.aborted) throw new Error("Operation aborted");

			const sandboxPath = resolveSandboxPath(path, ctx.repoPath);

			if (createDirs !== false) {
				const dir = sandboxPath.substring(0, sandboxPath.lastIndexOf("/"));
				if (dir) {
					await ctx.gitMachine.run(`mkdir -p "${dir}"`, { cwd: ctx.repoPath });
				}
			}

			await ctx.machine.writeFile(sandboxPath, content);

			const bytes = Buffer.byteLength(content, "utf-8");
			return {
				content: [{ type: "text", text: `Wrote ${bytes} bytes to ${path}` }],
				details: undefined,
			};
		},
	};
}
