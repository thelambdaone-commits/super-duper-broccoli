import type { AgentTool, AgentToolUpdateCallback } from "@mariozechner/pi-agent-core";
import type { SandboxContext } from "../sandbox.js";
import { cliSchema, MAX_OUTPUT, DEFAULT_TIMEOUT, truncateOutput } from "./shared.js";

export function createSandboxCliTool(
	ctx: SandboxContext,
	defaultTimeout?: number,
): AgentTool<typeof cliSchema> {
	const baseTimeout = defaultTimeout ?? DEFAULT_TIMEOUT;
	return {
		name: "cli",
		label: "cli",
		description:
			"Execute a shell command in the sandbox VM. Returns stdout and stderr combined. Output is truncated if it exceeds ~100KB. Default timeout is 120 seconds.",
		parameters: cliSchema,
		execute: async (
			_toolCallId: string,
			{ command, timeout }: { command: string; timeout?: number },
			signal?: AbortSignal,
			onUpdate?: AgentToolUpdateCallback,
		) => {
			if (signal?.aborted) throw new Error("Operation aborted");

			const timeoutSecs = timeout ?? baseTimeout;
			let output = "";

			const result = await ctx.gitMachine.run(command, {
				cwd: ctx.repoPath,
				timeout: timeoutSecs,
				onStdout: (data: string) => {
					output += data;
					if (onUpdate && output.length <= MAX_OUTPUT) {
						onUpdate({
							content: [{ type: "text", text: output }],
							details: undefined,
						});
					}
				},
				onStderr: (data: string) => {
					output += data;
					if (onUpdate && output.length <= MAX_OUTPUT) {
						onUpdate({
							content: [{ type: "text", text: output }],
							details: undefined,
						});
					}
				},
			});

			const exitCode = result?.exitCode ?? 0;
			let text = truncateOutput(output) || "(no output)";

			if (exitCode !== 0) {
				text += `\n\nExit code: ${exitCode}`;
				throw new Error(text);
			}

			return {
				content: [{ type: "text", text }],
				details: { exitCode },
			};
		},
	};
}
