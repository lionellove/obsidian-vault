export const PROTOCOL_VERSION = 1;
export const TOOL_NAMES = [
	"web_search",
	"extract_pdf_text",
	"python",
	"analyze_image",
] as const;

export type ToolName = (typeof TOOL_NAMES)[number];

export interface RunnerRequest {
	version: 1;
	prompt: string;
	cwd: string;
	pythonExecutable: string;
	toolBridgePath: string;
	model: {
		id: string;
		baseUrl: string;
	};
	enabledTools: ToolName[];
	maxTurns: number;
	toolTimeoutMs: number;
}

export interface TokenCounts {
	input: number;
	output: number;
	cacheRead: number;
	cacheWrite: number;
	totalTokens: number;
}

export interface RunnerResponse {
	protocolVersion: 1;
	prediction: string | null;
	error: string | null;
	errorType:
		| "model_error"
		| "answer_format_error"
		| "max_turns"
		| "runner_error"
		| null;
	tokenCounts: TokenCounts;
	toolErrorCount: number;
	turns: number;
	terminatedBy:
		| "assistant"
		| "model_error"
		| "answer_format_error"
		| "max_turns"
		| "runner_error";
	logs: unknown[];
	memoryMessages: unknown[];
}

const BRIDGE_ENVIRONMENT_NAMES = new Set([
	"PATH",
	"PATHEXT",
	"SYSTEMROOT",
	"WINDIR",
	"COMSPEC",
	"TEMP",
	"TMP",
	"HTTP_PROXY",
	"HTTPS_PROXY",
	"NO_PROXY",
	"ALL_PROXY",
]);

export function bridgeEnvironment(
	source: NodeJS.ProcessEnv,
): NodeJS.ProcessEnv {
	const output: NodeJS.ProcessEnv = {};
	for (const [name, value] of Object.entries(source)) {
		const upperName = name.toUpperCase();
		if (
			value !== undefined &&
			(BRIDGE_ENVIRONMENT_NAMES.has(upperName) ||
				upperName.startsWith("SILICON_"))
		) {
			output[name] = value;
		}
	}
	return output;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(
	object: Record<string, unknown>,
	key: string,
): string {
	const value = object[key];
	if (typeof value !== "string" || value.trim() === "") {
		throw new TypeError(`${key} must be a non-empty string`);
	}
	return value;
}

function requiredPositiveInteger(
	object: Record<string, unknown>,
	key: string,
): number {
	const value = object[key];
	if (!Number.isInteger(value) || (value as number) < 1) {
		throw new TypeError(`${key} must be a positive integer`);
	}
	return value as number;
}

export function parseRequest(value: unknown): RunnerRequest {
	if (!isRecord(value)) {
		throw new TypeError("runner request must be a JSON object");
	}
	if (value.version !== PROTOCOL_VERSION) {
		throw new TypeError(`version must be ${PROTOCOL_VERSION}`);
	}
	if (!isRecord(value.model)) {
		throw new TypeError("model must be a JSON object");
	}
	if ("apiKey" in value.model) {
		throw new TypeError(
			"model.apiKey is forbidden; use OPENAI_API_KEY in the environment",
		);
	}

	const modelId = requiredString(value.model, "id");
	const baseUrl = requiredString(value.model, "baseUrl");
	const parsedUrl = new URL(baseUrl);
	if (!["http:", "https:"].includes(parsedUrl.protocol)) {
		throw new TypeError("model.baseUrl must use http or https");
	}

	if (!Array.isArray(value.enabledTools)) {
		throw new TypeError("enabledTools must be an array");
	}
	const allowed = new Set<string>(TOOL_NAMES);
	const enabledTools = value.enabledTools.map((item) => {
		if (typeof item !== "string" || !allowed.has(item)) {
			throw new TypeError(`unknown enabled tool: ${String(item)}`);
		}
		return item as ToolName;
	});
	if (new Set(enabledTools).size !== enabledTools.length) {
		throw new TypeError("enabledTools must not contain duplicates");
	}

	return {
		version: 1,
		prompt: requiredString(value, "prompt"),
		cwd: requiredString(value, "cwd"),
		pythonExecutable: requiredString(value, "pythonExecutable"),
		toolBridgePath: requiredString(value, "toolBridgePath"),
		model: { id: modelId, baseUrl },
		enabledTools,
		maxTurns: requiredPositiveInteger(value, "maxTurns"),
		toolTimeoutMs: requiredPositiveInteger(value, "toolTimeoutMs"),
	};
}

export function extractFinalAnswer(text: string): string {
	const tagged = [
		...text.matchAll(/<final_answer>\s*([\s\S]*?)\s*<\/final_answer>/gi),
	];
	if (tagged.length > 0) {
		const answer = tagged.at(-1)?.[1]?.trim();
		if (answer) return answer;
	}

	const lineMarker = text.match(/(?:^|\n)FINAL_ANSWER:\s*([^\r\n]+)\s*$/i);
	if (lineMarker?.[1]?.trim()) {
		return lineMarker[1].trim();
	}
	throw new Error("Assistant response is missing an explicit final-answer marker");
}

export function summarizeUsage(messages: readonly unknown[]): TokenCounts {
	const total: TokenCounts = {
		input: 0,
		output: 0,
		cacheRead: 0,
		cacheWrite: 0,
		totalTokens: 0,
	};
	for (const message of messages) {
		if (!isRecord(message) || message.role !== "assistant") continue;
		if (!isRecord(message.usage)) continue;
		for (const key of Object.keys(total) as (keyof TokenCounts)[]) {
			const amount = message.usage[key];
			if (typeof amount === "number" && Number.isFinite(amount)) {
				total[key] += amount;
			}
		}
	}
	return total;
}
