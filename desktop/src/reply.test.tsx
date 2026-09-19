// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { defaults } from "./types";
import App from "./App";
const channel = vi.hoisted(() => ({ receive: (_event: {payload: {event: string; data: unknown}}) => {} }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(async (_name, callback) => {
  channel.receive = callback; return () => {};
}) }));
vi.mock("./bridge", () => ({ isDesktop: true, invoke: vi.fn(), request: vi.fn(async () => defaults) }));
let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  Element.prototype.scrollIntoView = vi.fn();
  container = document.createElement("div"); document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
async function emit(event: string, data: unknown) {
  await act(async () => { channel.receive({payload: {event, data}}); });
}
async function mount() {
  await act(async () => { root.render(<App/>); });
  const button = Array.from(container.querySelectorAll("nav button")).find(node=>node.textContent==="Assistant");
  expect(button).toBeDefined();
  await act(async () => { (button as HTMLButtonElement).click(); });
}
test("partial answer appears while busy and final answer replaces it once", async () => {
  await mount(); await emit("busy", true);
  await emit("reply_progress", {task_id: "one", content: "Start with a short plan."});
  expect(container.querySelector('[aria-label="Jarvis reply in progress"]')?.textContent).toContain("Start with a short plan.");
  await emit("message", {role: "assistant", content: "Start with a short plan. Take breaks."});
  expect(container.querySelector('[aria-label="Jarvis reply in progress"]')).toBeNull();
  expect(Array.from(container.querySelectorAll(".message p")).filter(p=>p.textContent==="Start with a short plan. Take breaks.")).toHaveLength(1);
});
test("stop removes transient output without storing an unfinished answer", async () => {
  await mount(); await emit("busy", true);
  await emit("reply_progress", {task_id: "one", content: "Unfinished answer"});
  await emit("reply_progress", {task_id: "one", content: ""});
  expect(container.textContent).not.toContain("Unfinished answer");
});
test("disconnect clears transient output", async () => {
  await mount(); await emit("reply_progress", {task_id: "one", content: "Unfinished answer"});
  await emit("disconnected", "Connection ended");
  expect(container.querySelector('[aria-label="Jarvis reply in progress"]')).toBeNull();
});
test("mission control shows actual reminders, authentication and response timing", async () => {
  await act(async () => { root.render(<App/>); });
  const due = Math.floor(Date.now()/1000)-10;
  await emit("activity", {reminders:[{id:1,text:"University assignment",due},{id:2,text:"Next week task",due:due+604800}]});
  await emit("response_timing", {duration_ms:2450, first_text_ms:350, action:"chat",success:true});
  expect(container.textContent).toContain("University assignment");
  expect(container.textContent).not.toContain("Next week task");
  expect(container.textContent).toContain("Not configured");
  expect(container.textContent).toContain("2.5 s");
  expect(container.textContent).toContain("First text in 0.3 s");
});
test("activity updates one task instead of duplicating running and completed rows", async () => {
  await act(async () => { root.render(<App/>); });
  const task={id:"same",source:"typed",state:"running",steps:[{id:"step",tool:"chat",state:"running",verification:"not_checked"}]};
  await emit("task",task);
  await emit("task",{...task,state:"succeeded"});
  expect(container.querySelectorAll(".mission-tasks article")).toHaveLength(1);
  expect(container.querySelector(".mission-tasks")?.textContent).toContain("Completed");
});
