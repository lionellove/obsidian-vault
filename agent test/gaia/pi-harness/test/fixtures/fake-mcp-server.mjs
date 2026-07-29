import { writeFileSync } from "node:fs";
import { createInterface } from "node:readline";

const [serverName = "server", closeMarker] = process.argv.slice(2);

function send(message) {
	process.stdout.write(`${JSON.stringify(message)}\n`);
}

function tool(name) {
	return {
		name,
		description: `${serverName} test tool`,
		inputSchema: {
			type: "object",
			properties: { value: { type: "string" } },
		},
	};
}

const lines = createInterface({ input: process.stdin });
lines.on("line", (line) => {
	const message = JSON.parse(line);
	if (message.method === "initialize") {
		send({
			jsonrpc: "2.0",
			id: message.id,
			result: {
				protocolVersion: message.params.protocolVersion,
				capabilities: { tools: {} },
				serverInfo: { name: serverName, version: "1.0.0" },
			},
		});
		return;
	}
	if (message.method === "tools/list") {
		const cursor = message.params?.cursor;
		if (serverName === "alpha" && cursor === undefined) {
			send({
				jsonrpc: "2.0",
				id: message.id,
				result: {
					tools: [tool("not_allowlisted")],
					nextCursor: "alpha-page-2",
				},
			});
			return;
		}
		send({
			jsonrpc: "2.0",
			id: message.id,
			result: { tools: [tool(`${serverName}_tool`)] },
		});
		return;
	}
	if (message.method === "tools/call") {
		send({
			jsonrpc: "2.0",
			id: message.id,
			result: {
				content: [
					{
						type: "text",
						text: `${serverName}:${message.params.name}:${message.params.arguments?.value ?? ""}`,
					},
				],
			},
		});
	}
});

lines.on("close", () => {
	if (closeMarker) writeFileSync(closeMarker, serverName, "utf8");
});
