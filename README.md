# Thread

A small, fast project manager. Python + SQLite + plain JavaScript and CSS. No dependencies, package install, build step, external fonts, or third-party requests.

## Run

Requires Python 3.9 or newer:

```sh
python3 app.py
```

Open http://127.0.0.1:8000. The first run creates `thread.db` with editable sample projects. Changes are saved immediately.

To start your own empty workspace in a separate database:

```sh
python3 app.py --empty --db my-workspace.db
```

`--empty` only affects a newly initialized database. It never clears existing work. Use `--port 8080` to choose another port.

## Work your way

- Create **spaces** for functions and **projects** inside them. Both can nest inside other spaces or projects. Select a space to see tasks across its projects.
- Tasks can nest to any depth: epics → stories → tasks → subtasks. Open a task to add subtasks or change its parent. List view expands and collapses the hierarchy.
- **Board** groups all tasks, including nested tasks, by status. Drag cards between columns. Touch and keyboard users can open a task and change its status with the form.
- **List** shows the task hierarchy, statuses, priorities, dates, and assignees.
- **Daily** puts overdue tasks first, then today, future deadlines, and undated tasks. Completed tasks are excluded. The sidebar’s My day includes the entire workspace; the Daily tab respects the selected space/project.
- Customize each project's status names, colors, and completion behavior using **Statuses**. New statuses appear as board columns. A status must be empty before it can be removed. At least one status must remain.
- Add descriptions, priorities, dates, one label, and an assignee name. Search covers these text fields. Filter by priority or sort by due date/priority. List view preserves hierarchy when sorting.
- Press **N** to create a task, **⌘/Ctrl K** to search, and **Esc** to close a dialog. Animations respect reduced-motion preferences.

## Storage and scope

This is a local, single-user app. Assignees are text labels, not user accounts. There is no authentication, synchronization, notification service, or multiuser conflict resolution. The server binds to `127.0.0.1` by default. Keep it local; the standard-library HTTP server is not intended as a public production server.

SQLite stores everything in your chosen database file. To back it up, stop the app first, then copy the `.db` file. Deleting tasks, projects, and spaces asks for confirmation; deletion includes descendants and is permanent. Renaming or moving containers preserves their content.

Frontend assets are served locally with no build step. View changes run in memory; mutations use a small JSON API and SQLite transactions. The app loads the workspace at startup and after writes, making it suitable for personal/small workspaces rather than huge organizational datasets. Concurrent browser tabs refresh on their next write or page reload.

## Verify

```sh
python3 -m unittest discover -s tests -v
node --check static/app.js
```

The Python tests use isolated temporary databases and cover hierarchy validation, project/status integrity, completion, deletion, persistence, and HTTP behavior.
