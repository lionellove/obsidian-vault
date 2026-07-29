import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
	connectMcpTools,
	discoverMcpTools,
	MAX_MCP_RESULT_BYTES,
	type McpClientLike,
} from "../src/mcp-tools.ts";
import type { McpConfig } from "../src/protocol.ts";

const config: McpConfig = {
	servers: [
		{
			name: "gaia",
			command: "docker",
			args: ["mcp", "gateway", "run", "--profile", "gaia", "--static"],
			envPassthrough: [],
		},
	],
	toolAllowlist: ["fetch"],
	maxTools: 4,
	connectTimeoutMs: 10_000,
};

test("MCP discovery exposes only allowlisted tools and forwards calls", async () => {
	const calls: unknown[] = [];
	const client: McpClientLike = {
		async listTools() {
			return {
				tools: [
					{
						name: "fetch",
						description: "Fetch one URL",
						inputSchema: {
							type: "object",
							properties: { url: { type: "string" } },
							required: ["url"],
						},
					},
					{
						name: "browser_file_upload",
						description: "Upload a local file",
						inputSchema: { type: "object" },
					},
				],
			};
		},
		async callTool(request) {
			calls.push(request);
			return {
				content: [{ type: "text", text: "Example Domain" }],
			};
		},
	};

	const tools = await discoverMcpTools(client, config, new Set(["python"]));

	assert.deepEqual(
		tools.map((tool) => tool.name),
		["fetch"],
	);
	const result = await tools[0].execute(
		"call-1",
		{ url: "https://example.com" },
		undefined,
		undefined,
		undefined as never,
	);
	assert.deepEqual(calls, [
		{
			name: "fetch",
			arguments: { url: "https://example.com" },
		},
	]);
	assert.equal(result.content[0]?.type, "text");
	assert.equal(result.content[0]?.text, "Example Domain");
});

test("MCP results omit binary payloads and enforce the UTF-8 byte limit", async () => {
	const client: McpClientLike = {
		async listTools() {
			return {
				tools: [
					{
						name: "fetch",
						inputSchema: { type: "object" },
					},
				],
			};
		},
		async callTool() {
			return {
				content: [
					{ type: "image", data: "secret-base64-payload", mimeType: "image/png" },
					{ type: "text", text: "界".repeat(MAX_MCP_RESULT_BYTES) },
				],
			};
		},
	};
	const [tool] = await discoverMcpTools(client, config, new Set());

	const result = await tool.execute(
		"call-2",
		{},
		undefined,
		undefined,
		undefined as never,
	);
	const content = result.content[0];
	assert.equal(content?.type, "text");
	const text = content?.type === "text" ? content.text : "";

	assert.match(text, /^\[unsupported MCP content type: image\]/);
	assert.doesNotMatch(text, /secret-base64-payload/);
	assert.match(text, /\[MCP result truncated at 65536 UTF-8 bytes\]$/);
	assert.ok(Buffer.byteLength(text, "utf8") <= MAX_MCP_RESULT_BYTES);
});

test("stdio MCP integration paginates each server, routes calls, and closes children", async () => {
	const fixturePath = fileURLToPath(
		new URL("./fixtures/fake-mcp-server.mjs", import.meta.url),
	);
	const markerDirectory = await mkdtemp(join(tmpdir(), "pi-mcp-test-"));
	const alphaMarker = join(markerDirectory, "alpha.closed");
	const betaMarker = join(markerDirectory, "beta.closed");
	const integrationConfig: McpConfig = {
		servers: [
			{
				name: "alpha",
				command: process.execPath,
				args: [fixturePath, "alpha", alphaMarker],
				envPassthrough: [],
			},
			{
				name: "beta",
				command: process.execPath,
				args: [fixturePath, "beta", betaMarker],
				envPassthrough: [],
			},
		],
		toolAllowlist: ["alpha_tool", "beta_tool"],
		maxTools: 2,
		connectTimeoutMs: 10_000,
	};

	const connection = await connectMcpTools(
		integrationConfig,
		new Set(["python"]),
		10_000,
		() => {},
	);
	try {
		assert.deepEqual(
			connection.tools.map((tool) => tool.name),
			["alpha_tool", "beta_tool"],
		);
		const results = await Promise.all(
			connection.tools.map((tool) =>
				tool.execute(
					`call-${tool.name}`,
					{ value: "ok" },
					undefined,
					undefined,
					undefined as never,
				),
			),
		);
		assert.deepEqual(
			results.map((result) => {
				const content = result.content[0];
				return content?.type === "text" ? content.text : undefined;
			}),
			["alpha:alpha_tool:ok", "beta:beta_tool:ok"],
		);
	} finally {
		await connection.close();
	}

	for (let attempt = 0; attempt < 20; attempt += 1) {
		if (existsSync(alphaMarker) && existsSync(betaMarker)) break;
		await new Promise((resolve) => setTimeout(resolve, 25));
	}
	assert.equal(await readFile(alphaMarker, "utf8"), "alpha");
	assert.equal(await readFile(betaMarker, "utf8"), "beta");
});
