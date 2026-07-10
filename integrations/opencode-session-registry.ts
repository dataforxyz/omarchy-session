// SPDX-License-Identifier: GPL-3.0-or-later
import type { Plugin } from "@opencode-ai/plugin";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

const tool = "opencode";
const pid = process.pid;
const registrationId = `${pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`;

async function processStartTicks(): Promise<number> {
	try {
		const stat = await readFile(`/proc/${pid}/stat`, "utf8");
		return Number(stat.slice(stat.lastIndexOf(") ") + 2).split(/\s+/)[19] ?? 0);
	} catch {
		return 0;
	}
}

function registryPath(): string {
	const runtimeDir = process.env.XDG_RUNTIME_DIR ?? `/run/user/${process.getuid?.() ?? 0}`;
	return join(runtimeDir, "omarchy-session", "agents", tool, `${pid}.json`);
}

async function removeRegistration(): Promise<void> {
	try {
		const current = JSON.parse(await readFile(registryPath(), "utf8")) as { registrationId?: string };
		if (current.registrationId === registrationId) {
			await rm(registryPath(), { force: true });
		}
	} catch {
		// Best effort during plugin disposal.
	}
}

export const SessionRegistryPlugin: Plugin = async ({ directory }) => {
	let activeSessionId = "";

	async function register(sessionId: string): Promise<void> {
		if (!sessionId) return;
		activeSessionId = sessionId;
		const path = registryPath();
		await mkdir(dirname(path), { recursive: true, mode: 0o700 });
		const record = {
			version: 1,
			tool,
			registrationId,
			pid,
			processStartTicks: await processStartTicks(),
			sessionId,
			cwd: directory,
			updatedAt: new Date().toISOString(),
			source: "opencode-plugin",
		};
		const temporary = `${path}.tmp-${pid}`;
		await writeFile(temporary, `${JSON.stringify(record)}\n`, { mode: 0o600 });
		await rename(temporary, path);
	}

	return {
		"chat.message": async (input) => {
			await register(input.sessionID);
		},
		"command.execute.before": async (input) => {
			await register(input.sessionID);
		},
		"shell.env": async (input) => {
			if (input.sessionID) await register(input.sessionID);
		},
		event: async ({ event }) => {
			if (event.type === "session.deleted" && event.properties.info.id === activeSessionId) {
				activeSessionId = "";
				await removeRegistration();
			}
		},
		dispose: removeRegistration,
	};
};

export default SessionRegistryPlugin;
