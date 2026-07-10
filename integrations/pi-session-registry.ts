// SPDX-License-Identifier: GPL-3.0-or-later
import { mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const tool = "pi";

function processStartTicks(pid: number): number {
	try {
		const stat = readFileSync(`/proc/${pid}/stat`, "utf8");
		return Number(stat.slice(stat.lastIndexOf(") ") + 2).split(/\s+/)[19] ?? 0);
	} catch {
		return 0;
	}
}

function registryPath(): string {
	const runtimeDir = process.env.XDG_RUNTIME_DIR ?? `/run/user/${process.getuid?.() ?? 0}`;
	return join(runtimeDir, "omarchy-session", "agents", tool, `${process.pid}.json`);
}

function removeRegistration(registrationId: string): void {
	try {
		const current = JSON.parse(readFileSync(registryPath(), "utf8")) as { registrationId?: string };
		if (current.registrationId === registrationId) {
			rmSync(registryPath(), { force: true });
		}
	} catch {
		// Best effort during shutdown.
	}
}

function publishRegistration(ctx: ExtensionContext, registrationId: string): void {
	const sessionFile = ctx.sessionManager.getSessionFile();
	if (!sessionFile) {
		removeRegistration(registrationId);
		return;
	}

	const path = registryPath();
	mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
	const record = {
		version: 1,
		tool,
		registrationId,
		pid: process.pid,
		processStartTicks: processStartTicks(process.pid),
		sessionId: ctx.sessionManager.getSessionId(),
		sessionFile,
		cwd: ctx.sessionManager.getCwd(),
		updatedAt: new Date().toISOString(),
		source: "pi-extension",
	};
	const temporary = `${path}.tmp-${registrationId}`;
	writeFileSync(temporary, `${JSON.stringify(record)}\n`, { mode: 0o600 });
	renameSync(temporary, path);
}

export default function (pi: ExtensionAPI) {
	const registrationId = `${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
	const publish = (ctx: ExtensionContext) => {
		try {
			publishRegistration(ctx, registrationId);
		} catch (error) {
			console.error("omarchy-session Pi registry:", error);
		}
	};
	pi.on("session_start", (_event, ctx) => publish(ctx));
	pi.on("message_end", (_event, ctx) => publish(ctx));
	pi.on("session_info_changed", (_event, ctx) => publish(ctx));
	pi.on("agent_settled", (_event, ctx) => publish(ctx));
	pi.on("session_shutdown", () => removeRegistration(registrationId));
}
