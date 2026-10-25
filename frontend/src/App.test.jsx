import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

// Fake backend: answers like the Flask API, keyed by "METHOD /path"
function mockApi(routes) {
  const fetchMock = vi.fn(async (url, options = {}) => {
    const key = `${options.method || "GET"} ${url}`;
    if (!(key in routes)) throw new TypeError(`Failed to fetch ${key}`);
    const { status = 200, body } = routes[key];
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const healthyApi = {
  "GET /api/health": { body: { status: "ok", database: "connected" } },
  "GET /api/stats": { body: { total_users: 2, today_users: 1, total_roles: 2 } },
  "GET /api/users": {
    body: {
      users: [
        { id: 1, name: "Aung Test", email: "aung.test@example.com", role: "Student" },
        { id: 2, name: "Kyaw Demo", email: "kyaw.demo@example.com", role: "Instructor" },
      ],
    },
  },
};

describe("dashboard", () => {
  it("shows API status, stats and users from the backend", async () => {
    mockApi(healthyApi);
    render(<App />);

    expect(await screen.findByText("API OK | DB connected")).toBeInTheDocument();
    expect(screen.getByText("Aung Test")).toBeInTheDocument();
    expect(screen.getByText("Kyaw Demo")).toBeInTheDocument();
    expect(screen.getByText("Total Users").previousSibling).toHaveTextContent("2");
  });

  it("says the API is offline when the backend cannot be reached", async () => {
    mockApi({}); // every call fails like a network error
    render(<App />);

    expect(await screen.findByText("API Offline")).toBeInTheDocument();
  });
});

describe("register form", () => {
  it("posts the form to /api/register and shows the success message", async () => {
    const fetchMock = mockApi({
      ...healthyApi,
      "POST /api/register": {
        status: 201,
        body: { message: "Registration successful", user: { id: 3 } },
      },
    });
    render(<App />);
    await screen.findByText("API OK | DB connected");

    await userEvent.type(screen.getByPlaceholderText("Your name"), "Su Placeholder");
    await userEvent.type(screen.getByPlaceholderText("student@example.com"), "su@example.com");
    await userEvent.click(screen.getByRole("button", { name: /register/i }));

    expect(await screen.findByText("Registration successful")).toBeInTheDocument();
    const [, options] = fetchMock.mock.calls.find(([url, o]) => url === "/api/register" && o);
    expect(JSON.parse(options.body)).toMatchObject({
      name: "Su Placeholder",
      email: "su@example.com",
      role: "Student",
    });
  });

  it("shows the backend's error message, e.g. a duplicate email (409)", async () => {
    mockApi({
      ...healthyApi,
      "POST /api/register": { status: 409, body: { error: "This email is already registered" } },
    });
    render(<App />);
    await screen.findByText("API OK | DB connected");

    await userEvent.type(screen.getByPlaceholderText("Your name"), "Aung Test");
    await userEvent.type(screen.getByPlaceholderText("student@example.com"), "aung.test@example.com");
    await userEvent.click(screen.getByRole("button", { name: /register/i }));

    expect(await screen.findByText("This email is already registered")).toBeInTheDocument();
  });
});
