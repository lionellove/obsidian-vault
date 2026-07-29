import { Type } from "@earendil-works/pi-ai";
import {
	defineTool,
	type ToolDefinition,
} from "@earendil-works/pi-coding-agent";
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";

import { isRecord, type McpConfig } from "./protocol.ts";

interface McpToolDescriptor {
	name: string;
	description?: string;
	inputSchema: Record<string, unknown>;
}

interface McpToolList {
	tools: McpToolDescriptor[];
	nextCursor?: string;
}

interface McpToolResult {
	content?: unknown[];
	structuredContent?: unknown;
	isError?: boolean;
}

export interface McpClientLike {
	listTools(request?: { cursor?: string }): Promise<McpToolList>;
	callTool(
		request: {
			name: string;
			arguments: Record<string, unknown>;
		},
		options?: { timeout?: number; signal?: AbortSignal },
	): Promise<McpToolResult>;
}

export interface McpToolConnection {
	tools: ToolDefinition[];
	close(): Promise<void>;
}

export const MAX_MCP_RESULT_BYTES = 64 * 1024;

const MCP_SYSTEM_ENVIRONMENT = new Set([
	"APPDATA",
	"COMSPEC",
	"HOME",
	"HOMEDRIVE",
	"HOMEPATH",
	"LOCALAPPDATA",
	"PATH",
	"PATHEXT",
	"PROGRAMDATA",
	"PROGRAMFILES",
	"PROGRAMFILES(X86)",
	"PROGRAMW6432",
	"SYSTEMDRIVE",
	"SYSTEMROOT",
	"TEMP",
	"TMP",
	"TMPDIR",
	"USERDOMAIN",
	"USERNAME",
	"USERPROFILE",
	"WINDIR",
]);

function mcpEnvironment(
	source: NodeJS.ProcessEnv,
	passthrough: readonly string[],
): Record<string, string> {
	const names = new Set([
		...MCP_SYSTEM_ENVIRONMENT,
		...passthrough.map((name) => name.toUpperCase()),
	]);
	const output: Record<string, string> = {};
	for (const [name, value] of Object.entries(source)) {
		if (value !== undefined && names.has(name.toUpperCase())) {
			output[name] = value;
		}
	}
	for (const name of passthrough) {
		if (!Object.keys(source).some((candidate) => candidate.toUpperCase() === name.toUpperCase())) {
			throw new Error(`Required MCP environment variable is missing: ${name}`);
		}
	}
	return output;
}

function jsonText(value: unknown): string {
	try {
		return JSON.stringify(value);
	} catch {
		return "[unserializable structured MCP content]";
	}
}

function truncateUtf8(text: string, maxBytes: number): string {
	if (Buffer.byteLength(text, "utf8") <= maxBytes) return text;

	const marker = `\n[MCP result truncated at ${maxBytes} UTF-8 bytes]`;
	const contentBudget = Math.max(0, maxBytes - Buffer.byteLength(marker, "utf8"));
	let low = 0;
	let high = text.length;
	while (low < high) {
		const middle = Math.ceil((low + high) / 2);
		if (Buffer.byteLength(text.slice(0, middle), "utf8") <= contentBudget) {
			low = middle;
		} else {
			high = middle - 1;
		}
	}
	return `${text.slice(0, low)}${marker}`;
}

function renderMcpResult(result: McpToolResult): string {
	const parts: string[] = [];
	for (const block of result.content ?? []) {
		if (isRecord(block) && block.type === "text" && typeof block.text === "string") {
			parts.push(block.text);
		} else if (
			isRecord(block) &&
			block.type === "resource" &&
			isRecord(block.resource) &&
			typeof block.resource.text === "string"
		) {
			parts.push(block.resource.text);
		} else {
			const type =
				isRecord(block) && typeof block.type === "string"
					? block.type
					: "unknown";
			parts.push(`[unsupported MCP content type: ${type}]`);
		}
	}
	if (result.structuredContent !== undefined) {
		parts.push(jsonText(result.structuredContent));
	}
	return truncateUtf8(parts.filter(Boolean).join("\n"), MAX_MCP_RESULT_BYTES);
}

function piToolResult(text: string) {
	return {
		content: [{ type: "text" as const, text }],
		details: {},
	};
}

async function closeMcpClients(clients: readonly Client[]): Promise<void> {
	const settled = await Promise.allSettled(
		[...clients].reverse().map((client) => client.close()),
	);
	const errors = settled.flatMap((result) =>
		result.status === "rejected" ? [result.reason] : [],
	);
	if (errors.length > 0) {
		throw new AggregateError(errors, "One or more MCP clients failed to close");
	}
}

export async function discoverMcpTools(
	client: McpClientLike,
	config: McpConfig,
	reservedNames: ReadonlySet<string>,
	toolTimeoutMs = 60_000,
): Promise<ToolDefinition[]> {
	const discovered: McpToolDescriptor[] = [];
	let cursor: string | undefined;
	do {
		const page = await client.listTools(cursor ? { cursor } : undefined);
		discovered.push(...page.tools);
		cursor = page.nextCursor;
	} while (cursor);

	const byName = new Map<string, McpToolDescriptor>();
	for (const tool of discovered) {
		if (byName.has(tool.name)) {
			throw new Error(`Duplicate MCP tool name: ${tool.name}`);
		}
		byName.set(tool.name, tool);
	}

	const missing = config.toolAllowlist.filter((name) => !byName.has(name));
	if (missing.length > 0) {
		throw new Error(
			`MCP tool allowlist names were not discovered: ${missing.join(", ")}`,
		);
	}

	const selected = config.toolAllowlist.map((name) => byName.get(name)!);
	if (selected.length > config.maxTools) {
		throw new Error(
			`MCP loaded ${selected.length} tools, exceeding maxTools=${config.maxTools}`,
		);
	}
	for (const tool of selected) {
		if (reservedNames.has(tool.name)) {
			throw new Error(`MCP tool name conflicts with an existing tool: ${tool.name}`);
		}
	}

	return selected.map((tool) =>
		defineTool({
			name: tool.name,
			label: tool.name,
			description: tool.description?.trim() || `MCP tool ${tool.name}`,
			promptSnippet: tool.description?.trim() || `Use MCP tool ${tool.name}`,
			parameters: Type.Unsafe<Record<string, unknown>>(
				tool.inputSchema as never,
			),
			executionMode: "sequential",
			async execute(_id, params, signal) {
				const result = await client.callTool(
					{
						name: tool.name,
						arguments: params,
					},
					{ timeout: toolTimeoutMs, signal },
				);
				const text = renderMcpResult(result);
				if (result.isError) {
					throw new Error(text || `MCP tool ${tool.name} failed`);
				}
				return piToolResult(text || "(MCP tool returned no text)");
			},
		}),
	);
}

export async function connectMcpTools(
	config: McpConfig,
	reservedNames: ReadonlySet<string>,
	toolTimeoutMs: number,
	onDiagnostic: (message: string) => void,
): Promise<McpToolConnection> {
	const clients: Client[] = [];
	const toolOwners = new Map<string, Client>();
	try {
		for (const server of config.servers) {
			const client = new Client({
				name: `gaia-pi-harness-${server.name}`,
				version: "1.0.0",
			});
			const transport = new StdioClientTransport({
				command: server.command,
				args: server.args,
				env: mcpEnvironment(process.env, server.envPassthrough),
				stderr: "pipe",
			});
			transport.stderr?.on("data", (chunk) => {
				onDiagnostic(`[mcp:${server.name}] ${String(chunk).trimEnd()}`);
			});
			clients.push(client);
			await client.connect(transport, { timeout: config.connectTimeoutMs });
		}
		const groupClient: McpClientLike = {
			async listTools(request) {
				if (request?.cursor) {
					throw new Error("MCP server-group pagination is internal");
				}
				const tools: McpToolDescriptor[] = [];
				for (const client of clients) {
					let cursor: string | undefined;
					do {
						const page = await client.listTools(
							cursor ? { cursor } : undefined,
						);
						for (const tool of page.tools) {
							toolOwners.set(tool.name, client);
							tools.push(tool);
						}
						cursor = page.nextCursor;
					} while (cursor);
				}
				return { tools };
			},
			async callTool(request, options) {
				const owner = toolOwners.get(request.name);
				if (!owner) {
					throw new Error(`No MCP server owns tool ${request.name}`);
				}
				return owner.callTool(request, options);
			},
		};
		const tools = await discoverMcpTools(
			groupClient,
			config,
			reservedNames,
			toolTimeoutMs,
		);
		return {
			tools,
			async close() {
				await closeMcpClients(clients);
			},
		};
	} catch (error) {
		await closeMcpClients(clients).catch((cleanupError) => {
			onDiagnostic(
				`[mcp] cleanup after connection failure also failed: ${String(cleanupError)}`,
			);
		});
		throw error;
	}
}
