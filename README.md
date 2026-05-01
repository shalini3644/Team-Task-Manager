# Team Task Manager

Full-stack project and task management app with authentication, team membership, task assignment, status tracking, dashboard metrics, SQL relationships, and role-based access control.

## Features

- Signup and login with JWT authentication.
- First registered user becomes an admin; later users start as members.
- Admins can manage projects, team members, tasks, and user roles.
- Members can view assigned projects/tasks and update their own task status.
- Dashboard shows total tasks, status counts, completion rate, overdue tasks, and project count.
- SQLite by default, configurable with `DATABASE_URL`.

## Run Locally

Install backend dependencies:

```bash
pip install -r requirements.txt
```

Start the API:

```bash
uvicorn main:app --reload
```

Install frontend dependencies:

```bash
npm install
```

Start the Vue app:

```bash
npm run dev
```

Open the Vite URL shown in the terminal. The frontend proxies `/api` requests to `http://127.0.0.1:8000`.
