import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { TaskDetailDrawer } from "../components/TaskDetailDrawer";
import { TaskflowView, taskBucket } from "../views/TaskflowView";
import type { TaskDetail, TaskSummary } from "../types";

function makeSummary(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    id: "TASK-1",
    title: "Sample",
    status: "active",
    summary: "",
    parent: "",
    workflow: "default",
    phase: "",
    blocked: {},
    subtasks: [],
    done_steps: 0,
    total_steps: 0,
    repos: [],
    has_debate: false,
    pending_rounds: 0,
    created_at: "2026-01-01",
    updated_at: "2026-01-01",
    ...overrides,
  };
}

function makeDetail(overrides: Partial<TaskDetail> = {}): TaskDetail {
  return {
    id: "TASK-1",
    title: "First Title",
    status: "active",
    summary: "First summary",
    parent: "",
    workflow: "default",
    phase: "plan",
    blocked: {},
    subtasks: [],
    steps: [],
    facts: [],
    decisions: [],
    links: [],
    repos: [],
    rounds: [],
    created_at: "2026-01-01",
    updated_at: "2026-01-01",
    log_lines: [],
    pending_dispatches: [],
    debate: { active: false, state: null, seats: [], synthesis: "" },
    ...overrides,
  };
}

describe("taskBucket", () => {
  it("classifies closed, blocked, paused, and active tasks", () => {
    expect(taskBucket(makeSummary({ status: "closed", blocked: { owner: "ops" } }))).toBe("closed");
    expect(taskBucket(makeSummary({ status: "active", blocked: { owner: "ops" } }))).toBe("blocked");
    expect(taskBucket(makeSummary({ status: "paused", blocked: {} }))).toBe("paused");
    expect(taskBucket(makeSummary({ status: "active", blocked: {} }))).toBe("active");
  });
});

describe("TaskDetailDrawer", () => {
  it("updates displayed summary when task prop changes", () => {
    const onRefresh = vi.fn();
    const { rerender } = render(
      <TaskDetailDrawer task={makeDetail({ id: "TASK-1", summary: "First summary" })} onRefresh={onRefresh} />
    );
    const input = screen.getByLabelText("Summary") as HTMLInputElement;
    expect(input.value).toBe("First summary");

    rerender(
      <TaskDetailDrawer
        task={makeDetail({
          id: "PROJ-2",
          summary: "Second summary",
          links: [{ title: "Jira PROJ-2", url: "https://co.atlassian.net/browse/PROJ-2" }],
        })}
        onRefresh={onRefresh}
      />
    );
    expect((screen.getByLabelText("Summary") as HTMLInputElement).value).toBe("Second summary");
    const jiraAnchor = screen.getByRole("link", { name: /Open in Jira/i }) as HTMLAnchorElement;
    expect(jiraAnchor.href).toBe("https://co.atlassian.net/browse/PROJ-2");
  });

  it("autofills session fields from Jira lookup", async () => {
    const spy = vi.spyOn(api, "lookupJira").mockResolvedValue({
      key: "PROJ-77",
      title: "Harden auth",
      status: "In Progress",
      issue_type: "Task",
      priority: "High",
      parent: "PROJ-10",
      url: "https://co.atlassian.net/browse/PROJ-77",
    });
    render(
      <TaskflowView tasks={[]} selectedTask={null} onSelectTask={vi.fn()} onRefresh={vi.fn()} />
    );
    fireEvent.click(screen.getByRole("button", { name: /Link Jira/i }));
    fireEvent.change(screen.getByPlaceholderText(/Jira key or URL/i), {
      target: { value: "PROJ-77" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Fetch from Jira/i }));
    await waitFor(() => {
      expect((screen.getByPlaceholderText(/Session ID/i) as HTMLInputElement).value).toBe("PROJ-77");
      expect((screen.getByPlaceholderText(/^Title$/i) as HTMLInputElement).value).toBe("Harden auth");
    });
    spy.mockRestore();
  });
});
