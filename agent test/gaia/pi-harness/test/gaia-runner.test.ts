import assert from "node:assert/strict";
import test from "node:test";

import {
	bridgeEnvironment,
	extractFinalAnswer,
	parseRequest,
	summarizeUsage,
} from "../src/protocol.ts";

test("bridge environment excludes the text-model API key", () => {
	assert.deepEqual(
		bridgeEnvironment({
			PATH: "C:\\bin",
			OPENAI_API_KEY: "do-not-forward",
			SILICON_TOKEN: "vision-key",
			HTTPS_PROXY: "http://proxy.test",
			UNRELATED_SECRET: "also-do-not-forward",
		}),
		{
			PATH: "C:\\bin",
			SILICON_TOKEN: "vision-key",
			HTTPS_PROXY: "http://proxy.test",
		},
	);
});

test("extractFinalAnswer requires an explicit final-answer marker", () => {
	assert.equal(
		extractFinalAnswer("work\n<final_answer>  42 litres </final_answer>"),
		"42 litres",
	);
	assert.equal(extractFinalAnswer("FINAL_ANSWER: Ada Lovelace"), "Ada Lovelace");
	assert.throws(
		() => extractFinalAnswer("I think the answer is probably 42."),
		/missing/i,
	);
});

test("parseRequest validates the protocol without accepting API keys", () => {
	const parsed = parseRequest({
		version: 1,
		prompt: "Question",
		cwd: "C:\\work",
		pythonExecutable: "python",
		toolBridgePath: "C:\\work\\pi_tool_bridge.py",
		model: {
			id: "deepseek-v4-flash",
			baseUrl: "https://api.deepseek.com",
		},
		enabledTools: ["web_search"],
		builtinTools: ["read", "bash", "grep", "find", "ls"],
		mcp: {
			servers: [
				{
					name: "gaia",
					command: "docker",
					args: [
						"mcp",
						"gateway",
						"run",
						"--profile",
						"gaia",
						"--static",
					],
					envPassthrough: [],
				},
			],
			toolAllowlist: ["fetch", "browser_navigate"],
			maxTools: 12,
			connectTimeoutMs: 180_000,
		},
		maxTurns: 8,
		toolTimeoutMs: 10_000,
	});

	assert.equal(parsed.model.id, "deepseek-v4-flash");
	assert.deepEqual(parsed.builtinTools, [
		"read",
		"bash",
		"grep",
		"find",
		"ls",
	]);
	assert.equal(parsed.mcp?.servers[0]?.command, "docker");
	assert.throws(
		() =>
			parseRequest({
				...parsed,
				model: { ...parsed.model, apiKey: "must-not-cross-the-protocol" },
			}),
		/apiKey/,
	);
	assert.throws(
		() =>
			parseRequest({
				...parsed,
				builtinTools: ["write"],
			}),
		/unknown builtin tool/i,
	);
});

test("summarizeUsage adds assistant-message token usage", () => {
	assert.deepEqual(
		summarizeUsage([
			{
				role: "assistant",
				usage: {
					input: 10,
					output: 4,
					cacheRead: 2,
					cacheWrite: 1,
					totalTokens: 17,
					cost: {
						input: 0,
						output: 0,
						cacheRead: 0,
						cacheWrite: 0,
						total: 0,
					},
				},
			},
			{ role: "user", content: "ignored" },
			{
				role: "assistant",
				usage: {
					input: 20,
					output: 6,
					cacheRead: 0,
					cacheWrite: 0,
					totalTokens: 26,
					cost: {
						input: 0,
						output: 0,
						cacheRead: 0,
						cacheWrite: 0,
						total: 0,
					},
				},
			},
		]),
		{
			input: 30,
			output: 10,
			cacheRead: 2,
			cacheWrite: 1,
			totalTokens: 43,
		},
	);
});
