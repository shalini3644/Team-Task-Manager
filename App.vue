<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

type Role = 'admin' | 'member'
type Status = 'todo' | 'in_progress' | 'done'
type Priority = 'low' | 'medium' | 'high'

type User = {
  id: number
  name: string
  email: string
  role: Role
}

type Project = {
  id: number
  name: string
  description: string
  created_by_id: number
  members: User[]
  task_count: number
}

type Task = {
  id: number
  title: string
  description: string
  status: Status
  priority: Priority
  assigned_to_id: number
  assignee: User
  project_id: number
  project: { id: number; name: string }
  due_date: string | null
}

type Dashboard = {
  total: number
  completed: number
  in_progress: number
  todo: number
  overdue: number
  projects: number
}

const API_URL = import.meta.env.VITE_API_URL || ''

const token = ref(localStorage.getItem('ttm_token') || '')
const user = ref<User | null>(JSON.parse(localStorage.getItem('ttm_user') || 'null'))
const authMode = ref<'login' | 'signup'>('login')
const loading = ref(false)
const error = ref('')
const notice = ref('')

const users = ref<User[]>([])
const projects = ref<Project[]>([])
const tasks = ref<Task[]>([])
const dashboard = ref<Dashboard>({ total: 0, completed: 0, in_progress: 0, todo: 0, overdue: 0, projects: 0 })

const authForm = reactive({
  name: '',
  email: '',
  password: '',
  role: 'member' as Role,
})

const projectForm = reactive({
  name: '',
  description: '',
  member_ids: [] as number[],
})

const memberForm = reactive({
  project_id: '',
  user_id: '',
})

const taskForm = reactive({
  title: '',
  description: '',
  project_id: '',
  assigned_to_id: '',
  due_date: '',
  priority: 'medium' as Priority,
})

const isAdmin = computed(() => user.value?.role === 'admin')
const upcomingTasks = computed(() =>
  [...tasks.value]
    .filter((task) => task.status !== 'done')
    .sort((a, b) => (a.due_date || '').localeCompare(b.due_date || ''))
    .slice(0, 5),
)
const selectedProjectMembers = computed(() => {
  const project = projects.value.find((item) => item.id === Number(taskForm.project_id))
  return project?.members || users.value
})
const completionRate = computed(() =>
  dashboard.value.total ? Math.round((dashboard.value.completed / dashboard.value.total) * 100) : 0,
)

function authHeaders(): Record<string, string> {
  return token.value ? { Authorization: `Bearer ${token.value}` } : {}
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Content-Type', 'application/json')
  for (const [key, value] of Object.entries(authHeaders())) {
    headers.set(key, value)
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
  })

  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || 'Something went wrong')
  }

  return response.json()
}

function storeSession(payload: { token: string; user: User }) {
  token.value = payload.token
  user.value = payload.user
  localStorage.setItem('ttm_token', payload.token)
  localStorage.setItem('ttm_user', JSON.stringify(payload.user))
}

async function authenticate() {
  error.value = ''
  notice.value = ''
  loading.value = true
  try {
    const payload =
      authMode.value === 'signup'
        ? await api<{ token: string; user: User }>('/api/auth/signup', {
            method: 'POST',
            body: JSON.stringify(authForm),
          })
        : await api<{ token: string; user: User }>('/api/auth/login', {
            method: 'POST',
            body: JSON.stringify({ email: authForm.email, password: authForm.password }),
          })
    storeSession(payload)
    await loadData()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Unable to authenticate'
  } finally {
    loading.value = false
  }
}

function logout() {
  token.value = ''
  user.value = null
  localStorage.removeItem('ttm_token')
  localStorage.removeItem('ttm_user')
  users.value = []
  projects.value = []
  tasks.value = []
}

async function loadData() {
  if (!token.value) return
  error.value = ''
  try {
    const requests = [
      api<Dashboard>('/api/dashboard'),
      api<Project[]>('/api/projects'),
      api<Task[]>('/api/tasks'),
    ] as const

    const [dashboardData, projectData, taskData] = await Promise.all(requests)
    dashboard.value = dashboardData
    projects.value = projectData
    tasks.value = taskData
    if (isAdmin.value) {
      users.value = await api<User[]>('/api/users')
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Unable to load workspace'
    if (error.value.includes('token') || error.value.includes('User not found')) logout()
  }
}

async function createProject() {
  error.value = ''
  notice.value = ''
  try {
    await api<Project>('/api/projects', {
      method: 'POST',
      body: JSON.stringify(projectForm),
    })
    Object.assign(projectForm, { name: '', description: '', member_ids: [] })
    notice.value = 'Project created'
    await loadData()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Unable to create project'
  }
}

async function addMember() {
  error.value = ''
  notice.value = ''
  try {
    await api('/api/projects/' + memberForm.project_id + '/members', {
      method: 'POST',
      body: JSON.stringify({ user_id: Number(memberForm.user_id) }),
    })
    Object.assign(memberForm, { project_id: '', user_id: '' })
    notice.value = 'Member added'
    await loadData()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Unable to add member'
  }
}

async function removeMember(project: Project, member: User) {
  if (!confirm(`Remove ${member.name} from ${project.name}?`)) return
  error.value = ''
  notice.value = ''
  try {
    await api(`/api/projects/${project.id}/members/${member.id}`, { method: 'DELETE' })
    notice.value = 'Member removed'
    await loadData()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Unable to remove member'
  }
}

async function deleteProject(project: Project) {
  if (!confirm(`Delete ${project.name} and all its tasks?`)) return
  error.value = ''
  notice.value = ''
  try {
    await api(`/api/projects/${project.id}`, { method: 'DELETE' })
    notice.value = 'Project deleted'
    await loadData()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Unable to delete project'
  }
}

async function updateUserRole(member: User, role: Role) {
  error.value = ''
  notice.value = ''
  try {
    const updated = await api<User>(`/api/users/${member.id}/role`, {
      method: 'PATCH',
      body: JSON.stringify({ role }),
    })
    users.value = users.value.map((item) => (item.id === updated.id ? updated : item))
    if (user.value?.id === updated.id) {
      user.value = updated
      localStorage.setItem('ttm_user', JSON.stringify(updated))
    }
    notice.value = 'Role updated'
    await loadData()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Unable to update role'
  }
}

async function createTask() {
  error.value = ''
  notice.value = ''
  try {
    await api<Task>('/api/tasks', {
      method: 'POST',
      body: JSON.stringify({
        title: taskForm.title,
        description: taskForm.description,
        project_id: Number(taskForm.project_id),
        assigned_to_id: Number(taskForm.assigned_to_id),
        due_date: taskForm.due_date ? new Date(taskForm.due_date).toISOString() : null,
        priority: taskForm.priority,
      }),
    })
    Object.assign(taskForm, {
      title: '',
      description: '',
      project_id: '',
      assigned_to_id: '',
      due_date: '',
      priority: 'medium',
    })
    notice.value = 'Task created'
    await loadData()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Unable to create task'
  }
}

async function deleteTask(task: Task) {
  if (!confirm(`Delete task "${task.title}"?`)) return
  error.value = ''
  notice.value = ''
  try {
    await api(`/api/tasks/${task.id}`, { method: 'DELETE' })
    notice.value = 'Task deleted'
    await loadData()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Unable to delete task'
  }
}

async function updateStatus(task: Task, status: Status) {
  error.value = ''
  try {
    await api<Task>(`/api/tasks/${task.id}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    })
    await loadData()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Unable to update task'
  }
}

function formatDate(date: string | null) {
  if (!date) return 'No due date'
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(date))
}

function isOverdue(task: Task) {
  return Boolean(task.due_date && new Date(task.due_date) < new Date() && task.status !== 'done')
}

onMounted(loadData)
</script>

<template>
  <main v-if="!user" class="auth-shell">
    <section class="auth-panel">
      <div>
        <p class="eyebrow">Team Task Manager</p>
        <h1>Run projects, assignments, and status from one workspace.</h1>
        <p class="intro">
          Admins create projects, build teams, and assign tasks. Members track their work and update progress.
        </p>
      </div>

      <form class="auth-card" @submit.prevent="authenticate">
        <div class="segmented">
          <button type="button" :class="{ active: authMode === 'login' }" @click="authMode = 'login'">Login</button>
          <button type="button" :class="{ active: authMode === 'signup' }" @click="authMode = 'signup'">Signup</button>
        </div>

        <label v-if="authMode === 'signup'">
          Name
          <input v-model="authForm.name" required minlength="2" placeholder="Aarav Mehta" />
        </label>
        <label>
          Email
          <input v-model="authForm.email" required type="email" placeholder="you@example.com" />
        </label>
        <label>
          Password
          <input v-model="authForm.password" required minlength="6" type="password" placeholder="Minimum 6 characters" />
        </label>
        <p v-if="error" class="message error">{{ error }}</p>
        <button class="primary" :disabled="loading">{{ loading ? 'Please wait...' : authMode === 'login' ? 'Login' : 'Create account' }}</button>
      </form>
    </section>
  </main>

  <main v-else class="app-shell">
    <aside class="sidebar">
      <div>
        <p class="eyebrow">Workspace</p>
        <h2>Team Task Manager</h2>
      </div>
      <div class="profile">
        <strong>{{ user.name }}</strong>
        <span>{{ user.role }}</span>
      </div>
      <button class="ghost" @click="logout">Logout</button>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div>
          <p class="eyebrow">Dashboard</p>
          <h1>Project pulse</h1>
        </div>
        <button class="ghost" @click="loadData">Refresh</button>
      </header>

      <p v-if="error" class="message error">{{ error }}</p>
      <p v-if="notice" class="message success">{{ notice }}</p>

      <section class="metrics">
        <article>
          <span>Total tasks</span>
          <strong>{{ dashboard.total }}</strong>
        </article>
        <article>
          <span>Complete</span>
          <strong>{{ completionRate }}%</strong>
        </article>
        <article>
          <span>Overdue</span>
          <strong>{{ dashboard.overdue }}</strong>
        </article>
        <article>
          <span>Projects</span>
          <strong>{{ dashboard.projects }}</strong>
        </article>
      </section>

      <section class="content-grid">
        <div class="panel">
          <div class="panel-heading">
            <h2>Tasks</h2>
            <span>{{ dashboard.todo }} todo / {{ dashboard.in_progress }} active / {{ dashboard.completed }} done</span>
          </div>
          <div class="task-list">
            <article v-for="task in tasks" :key="task.id" class="task-row" :class="{ overdue: isOverdue(task) }">
              <div>
                <div class="task-title">
                  <strong>{{ task.title }}</strong>
                  <span :class="['badge', task.priority]">{{ task.priority }}</span>
                </div>
                <p>{{ task.project.name }} / {{ task.assignee.name }} / {{ formatDate(task.due_date) }}</p>
              </div>
              <div class="row-actions">
                <select :value="task.status" @change="updateStatus(task, ($event.target as HTMLSelectElement).value as Status)">
                  <option value="todo">Todo</option>
                  <option value="in_progress">In progress</option>
                  <option value="done">Done</option>
                </select>
                <button v-if="isAdmin" class="danger" type="button" @click="deleteTask(task)">Delete</button>
              </div>
            </article>
            <p v-if="!tasks.length" class="empty">No tasks yet.</p>
          </div>
        </div>

        <div class="panel">
          <div class="panel-heading">
            <h2>Upcoming</h2>
            <span>Open work</span>
          </div>
          <div class="mini-list">
            <article v-for="task in upcomingTasks" :key="task.id">
              <strong>{{ task.title }}</strong>
              <span>{{ formatDate(task.due_date) }}</span>
            </article>
            <p v-if="!upcomingTasks.length" class="empty">Nothing pending.</p>
          </div>
        </div>
      </section>

      <section class="content-grid admin-grid" v-if="isAdmin">
        <form class="panel form-panel" @submit.prevent="createProject">
          <div class="panel-heading">
            <h2>New project</h2>
          </div>
          <label>
            Project name
            <input v-model="projectForm.name" required placeholder="Mobile launch" />
          </label>
          <label>
            Description
            <textarea v-model="projectForm.description" rows="3" placeholder="Scope, goals, or notes"></textarea>
          </label>
          <label>
            Team
            <select v-model="projectForm.member_ids" multiple>
              <option v-for="member in users" :key="member.id" :value="member.id">{{ member.name }} / {{ member.role }}</option>
            </select>
          </label>
          <button class="primary">Create project</button>
        </form>

        <form class="panel form-panel" @submit.prevent="createTask">
          <div class="panel-heading">
            <h2>New task</h2>
          </div>
          <label>
            Title
            <input v-model="taskForm.title" required placeholder="Prepare release checklist" />
          </label>
          <label>
            Project
            <select v-model="taskForm.project_id" required @change="taskForm.assigned_to_id = ''">
              <option value="" disabled>Select project</option>
              <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
            </select>
          </label>
          <label>
            Assignee
            <select v-model="taskForm.assigned_to_id" required>
              <option value="" disabled>Select assignee</option>
              <option v-for="member in selectedProjectMembers" :key="member.id" :value="member.id">{{ member.name }}</option>
            </select>
          </label>
          <label>
            Due date
            <input v-model="taskForm.due_date" type="datetime-local" />
          </label>
          <label>
            Priority
            <select v-model="taskForm.priority">
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>
          <label>
            Description
            <textarea v-model="taskForm.description" rows="3"></textarea>
          </label>
          <button class="primary">Create task</button>
        </form>

        <form class="panel form-panel" @submit.prevent="addMember">
          <div class="panel-heading">
            <h2>Add member</h2>
          </div>
          <label>
            Project
            <select v-model="memberForm.project_id" required>
              <option value="" disabled>Select project</option>
              <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
            </select>
          </label>
          <label>
            Member
            <select v-model="memberForm.user_id" required>
              <option value="" disabled>Select member</option>
              <option v-for="member in users" :key="member.id" :value="member.id">{{ member.name }}</option>
            </select>
          </label>
          <button class="primary">Add to project</button>
        </form>
      </section>

      <section class="panel users-panel" v-if="isAdmin">
        <div class="panel-heading">
          <h2>Users</h2>
          <span>{{ users.length }} total</span>
        </div>
        <div class="user-list">
          <article v-for="member in users" :key="member.id">
            <div>
              <strong>{{ member.name }}</strong>
              <span>{{ member.email }}</span>
            </div>
            <select :value="member.role" @change="updateUserRole(member, ($event.target as HTMLSelectElement).value as Role)">
              <option value="admin">Admin</option>
              <option value="member">Member</option>
            </select>
          </article>
        </div>
      </section>

      <section class="panel projects-panel">
        <div class="panel-heading">
          <h2>Projects</h2>
          <span>{{ projects.length }} total</span>
        </div>
        <div class="project-list">
          <article v-for="project in projects" :key="project.id">
            <div>
              <div class="project-heading">
                <strong>{{ project.name }}</strong>
                <button v-if="isAdmin" class="danger" type="button" @click="deleteProject(project)">Delete</button>
              </div>
              <p>{{ project.description || 'No description' }}</p>
              <div class="member-chips">
                <span v-for="member in project.members" :key="member.id">
                  {{ member.name }}
                  <button v-if="isAdmin && member.id !== project.created_by_id" type="button" @click="removeMember(project, member)">
                    Remove
                  </button>
                </span>
              </div>
            </div>
            <span>{{ project.members.length }} members / {{ project.task_count }} tasks</span>
          </article>
          <p v-if="!projects.length" class="empty">No projects yet.</p>
        </div>
      </section>
    </section>
  </main>
</template>
