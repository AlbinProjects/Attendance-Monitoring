# Attendance Desktop Activity Agent

Optional companion for the attendance app's **Advanced Desktop Monitoring** mode.
It is **not required when Advanced Desktop Monitoring is OFF**.

## Privacy

The agent measures only OS input-idle state and a coarse application category
calculated locally. It never collects or transmits keystrokes, screenshots,
window titles, URLs, browser history, source code, documents, terminal
commands/output, or clipboard contents.

Categories sent to the server are generic labels such as `development`,
`terminal`, `office`, `communication`, `browser`, or `other_desktop`.

## Windows installation

1. Install Python 3.11+ on the work PC.
2. Extract this folder to a permanent location.
3. Run `install_windows.bat` as the employee's Windows user.
4. The installer creates a private virtual environment and registers the agent
   to start at Windows logon.

The agent listens only on `127.0.0.1:17891` and receives an employee-scoped,
short-lived token from the authenticated attendance web app.

To remove automatic startup, run `uninstall_windows.bat`.

## Runtime behavior

- Activity sample: every 30 seconds by default.
- Inactivity threshold: 10 minutes by default.
- Browser activity remains measured by the web app; the agent does not bypass
  browser activity rules.
- Known consumer/game apps are ignored.
- Unknown desktop apps are treated as generic desktop work locally; their
  executable names are never sent to the server.
- A small SQLite queue stores only timestamped coarse events while offline.
- The queue is bounded at 10,000 rows.
- Network/server loss is tracked separately from user inactivity.
- When connectivity returns, queued events and the monitoring-unavailable
  interval are synchronized in order.
- If the attendance session closes or authorization expires, the server rejects
  further activity events.
- Advanced monitoring is used only for Office/WFH employee sessions. Other
  Site and On Duty sessions are rejected by the backend.

## Important

The agent cannot report while the entire PC is powered off. The server will
see the monitoring session stop and later resume. That gap is not converted to
employee inactivity when it has been identified as a connectivity/device gap.
