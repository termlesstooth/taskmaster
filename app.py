"""Thread — a dependency-free, local project manager. Python 3.9+."""
import argparse
import json
import mimetypes
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "thread.db"
COLORS = {"gray", "blue", "amber", "purple", "green", "red", "pink"}


@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def init_db(demo=True):
    with connect() as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS nodes (
          id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES nodes(id) ON DELETE CASCADE,
          kind TEXT NOT NULL CHECK(kind IN ('space','project')), name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '', color TEXT NOT NULL DEFAULT 'blue');
        CREATE TABLE IF NOT EXISTS statuses (
          id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
          name TEXT NOT NULL, color TEXT NOT NULL DEFAULT 'gray', position INTEGER NOT NULL,
          is_done INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS tasks (
          id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
          parent_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
          status_id INTEGER NOT NULL REFERENCES statuses(id), title TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '', priority TEXT NOT NULL DEFAULT 'medium',
          due_date TEXT, assignee TEXT NOT NULL DEFAULT '', label TEXT NOT NULL DEFAULT '',
          position INTEGER NOT NULL DEFAULT 0, day_order INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS tasks_project ON tasks(project_id);
        CREATE INDEX IF NOT EXISTS tasks_parent ON tasks(parent_id);
        CREATE INDEX IF NOT EXISTS tasks_due ON tasks(due_date);
        CREATE TABLE IF NOT EXISTS comments (
          id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
          author TEXT NOT NULL DEFAULT 'You', body TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS comments_task ON comments(task_id, created_at);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        """)
        # Databases created before the My day ordering feature need the extra column.
        if 'day_order' not in {row['name'] for row in db.execute("PRAGMA table_info(tasks)")}:
            db.execute("ALTER TABLE tasks ADD COLUMN day_order INTEGER NOT NULL DEFAULT 0")
        if db.execute("SELECT 1 FROM settings WHERE key='initialized'").fetchone():
            return
        db.execute("INSERT INTO settings VALUES ('initialized','1')")
        if not demo:
            return
        for ident, parent, kind, name, desc, color in [
            (1, None, 'space', 'Engineering', 'Build thoughtful products, together.', 'blue'),
            (2, 1, 'project', 'Website redesign', 'A fresh foundation for what comes next.', 'blue'),
            (3, 1, 'project', 'Platform & API', 'Keep the engine running smoothly.', 'purple'),
            (4, None, 'space', 'Design', 'Make every detail count.', 'pink'),
            (5, 4, 'project', 'Design system', 'A shared language for our product.', 'pink'),
            (6, None, 'space', 'Marketing', 'Tell a story worth sharing.', 'amber'),
            (7, 6, 'project', 'Fall launch', 'Bring our next chapter to the world.', 'amber'),
            (8, None, 'space', 'Finance', 'A little clarity for the numbers.', 'green'),
            (9, 8, 'project', 'Quarterly planning', 'Make room for sustainable growth.', 'green')]:
            db.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?)", (ident,parent,kind,name,desc,color))
        for project in [2,3,5,7,9]:
            default_statuses(db, project)
        today = date.today()
        examples = [
            ('Explore navigation patterns',0,'low',5,'Design','Alex Morgan',None,'Research a few approaches to navigation. Keep it simple and make the important things easy to find.'),
            ('Audit existing content',0,'medium',3,'Content','Jamie Chen',None,'Map our current pages and identify opportunities to simplify.'),
            ('Define success metrics',0,'high',2,'Planning','',None,''),
            ('Build the new homepage',1,'high',1,'Frontend','Alex Morgan',None,'Create a welcoming homepage with clear typography, considered spacing, and a strong product story.'),
            ('Responsive navigation',1,'medium',0,'Frontend','Sam Rivera',4,'Make navigation feel effortless on small screens.'),
            ('Set up design tokens',1,'medium',2,'Design','Jamie Chen',None,'Bring our colors, typography, and spacing into one consistent system.'),
            ('Review mobile layouts',2,'high',0,'Design','Jamie Chen',None,'Check key layouts at phone and tablet sizes.'),
            ('Accessibility pass',2,'medium',1,'Frontend','Sam Rivera',None,'Review keyboard navigation, color contrast, and screen reader labels.'),
            ('Project kickoff',3,'medium',-3,'Planning','Alex Morgan',None,'Align on goals, scope, and the first milestones.'),
            ('Create wireframes',3,'low',-1,'Design','Jamie Chen',None,''),
            ('Menu keyboard support',0,'medium',1,'Frontend','Sam Rivera',5,'Support focus movement and escape to close.')]
        statuses = [r['id'] for r in db.execute("SELECT id FROM statuses WHERE project_id=2 ORDER BY position")]
        for i, (title, status, priority, days, label, person, parent, desc) in enumerate(examples, 1):
            db.execute("INSERT INTO tasks (id,project_id,parent_id,status_id,title,description,priority,due_date,assignee,label,position) VALUES (?,2,?,?,?,?,?,?,?,?,?)", (i,parent,statuses[status],title,desc,priority,str(today+timedelta(days=days)),person,label,i))
        for project, title, days in [(3,'Document API endpoints',2),(5,'Refine button components',0),(7,'Prepare launch announcement',4),(9,'Review next quarter’s budget',-1)]:
            sid = db.execute("SELECT id FROM statuses WHERE project_id=? ORDER BY position", (project,)).fetchone()['id']
            db.execute("INSERT INTO tasks (project_id,status_id,title,due_date) VALUES (?,?,?,?)", (project,sid,title,str(today+timedelta(days=days))))


def default_statuses(db, project):
    for pos, (name, color) in enumerate([('Backlog','gray'),('In progress','blue'),('In review','purple'),('Done','green')]):
        db.execute("INSERT INTO statuses (project_id,name,color,position,is_done) VALUES (?,?,?,?,?)", (project,name,color,pos,int(pos==3)))


class Invalid(ValueError):
    pass


def require(db, table, ident):
    if not isinstance(ident, int) or isinstance(ident, bool):
        raise Invalid('Invalid identifier')
    row = db.execute(f"SELECT * FROM {table} WHERE id=?", (ident,)).fetchone()
    if not row:
        raise Invalid('That item no longer exists')
    return dict(row)


def nonempty(value, field, limit=250):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise Invalid(f'{field} must contain 1–{limit} characters')
    return value.strip()


def validate_task(db, task, ident=None):
    task['title'] = nonempty(task['title'], 'Title')
    project = require(db, 'nodes', task['project_id'])
    if project['kind'] != 'project':
        raise Invalid('Tasks belong to projects')
    status = require(db, 'statuses', task['status_id'])
    if status['project_id'] != task['project_id']:
        raise Invalid('Status must belong to this project')
    seen = {ident}
    parent = task['parent_id']
    while parent is not None:
        if parent in seen:
            raise Invalid('A task cannot be nested inside itself')
        seen.add(parent)
        row = require(db, 'tasks', parent)
        if row['project_id'] != task['project_id']:
            raise Invalid('Parent task must belong to this project')
        parent = row['parent_id']
    if task['priority'] not in {'low','medium','high','urgent'}:
        raise Invalid('Invalid priority')
    if task['due_date'] is not None:
        if not isinstance(task['due_date'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', task['due_date']):
            raise Invalid('Use a valid date in YYYY-MM-DD format')
        try:
            date.fromisoformat(task['due_date'])
        except ValueError:
            raise Invalid('Use a valid date')
    for field, limit in [('description',20000),('assignee',100),('label',80)]:
        if not isinstance(task[field], str) or len(task[field]) > limit:
            raise Invalid(f'{field} is too long or invalid')
    for field in ('position', 'day_order'):
        if not isinstance(task[field], int) or isinstance(task[field], bool):
            raise Invalid(f'Invalid {field}')


def mutate(db, method, path, data):
    parts = path.strip('/').split('/')
    table = parts[1] if len(parts)>1 else ''
    if table not in {'nodes','tasks','statuses','comments'} or len(parts) not in {2,3}:
        raise Invalid('Unknown endpoint')
    ident = int(parts[2]) if len(parts)==3 and parts[2].isdigit() else None
    if len(parts) == 3 and ident is None:
        raise Invalid('Invalid identifier')
    old = require(db, table, ident) if ident is not None else None
    if method == 'DELETE':
        if old is None:
            raise Invalid('Choose an item to delete')
        if table == 'statuses':
            if db.execute("SELECT 1 FROM tasks WHERE status_id=?",(ident,)).fetchone():
                raise Invalid('Move tasks to another status before deleting this status')
            if db.execute("SELECT count(*) FROM statuses WHERE project_id=?",(old['project_id'],)).fetchone()[0] <= 1:
                raise Invalid('Keep at least one status')
        db.execute(f"DELETE FROM {table} WHERE id=?",(ident,))
        return {'ok': True}
    if table == 'comments':
        if method != 'POST' or old is not None:
            raise Invalid('Comments can only be added or deleted')
        task_id = data.get('task_id')
        if not isinstance(task_id, int) or isinstance(task_id, bool):
            raise Invalid('Choose a task for this comment')
        require(db, 'tasks', task_id)
        body = nonempty(data.get('body', ''), 'Comment', 5000)
        author = data.get('author', 'You')
        if not isinstance(author, str) or not author.strip() or len(author) > 100:
            raise Invalid('Author must contain 1–100 characters')
        cur = db.execute("INSERT INTO comments (task_id,author,body) VALUES (?,?,?)", (task_id,author.strip(),body))
        return require(db, 'comments', cur.lastrowid)
    if (method == 'PATCH' and old is None) or (method == 'POST' and old is not None):
        raise Invalid('Invalid operation')
    if table == 'tasks':
        defaults = dict(project_id=None,parent_id=None,status_id=None,title='',description='',priority='medium',due_date=None,assignee='',label='',position=0,day_order=0)
        fields = set(defaults)
        item = {**defaults, **(old or {}), **{k:v for k,v in data.items() if k in fields}}
        if old and item['project_id'] != old['project_id']:
            raise Invalid('Moving a task between projects is not supported')
        validate_task(db, item, ident)
    elif table == 'nodes':
        defaults = dict(parent_id=None,kind='project',name='',description='',color='blue')
        fields = set(defaults)
        item = {**defaults, **(old or {}), **{k:v for k,v in data.items() if k in fields}}
        item['name'] = nonempty(item['name'], 'Name', 100)
        if item['kind'] not in {'space','project'} or (old and item['kind'] != old['kind']):
            raise Invalid('Invalid kind')
        if not isinstance(item['description'], str) or len(item['description']) > 2000:
            raise Invalid('Description is too long or invalid')
        seen, parent = {ident}, item['parent_id']
        while parent is not None:
            if parent in seen:
                raise Invalid('A space or project cannot contain itself')
            seen.add(parent)
            parent = require(db, 'nodes', parent)['parent_id']
    else:
        defaults = dict(project_id=None,name='',color='gray',position=0,is_done=0)
        fields = set(defaults)
        item = {**defaults, **(old or {}), **{k:v for k,v in data.items() if k in fields}}
        item['name'] = nonempty(item['name'], 'Status name', 50)
        if require(db,'nodes',item['project_id'])['kind'] != 'project':
            raise Invalid('Statuses belong to projects')
        if old and item['project_id'] != old['project_id']:
            raise Invalid('Cannot move a status between projects')
        if not isinstance(item['position'],int) or item['is_done'] not in (0,1):
            raise Invalid('Invalid status settings')
    if table != 'tasks' and item['color'] not in COLORS:
        raise Invalid('Invalid color')
    fields = sorted(fields)
    if old:
        db.execute(f"UPDATE {table} SET {','.join(f'{key}=?' for key in fields)} WHERE id=?", [item[k] for k in fields]+[ident])
    else:
        cur = db.execute(f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", [item[k] for k in fields])
        ident = cur.lastrowid
        if table == 'nodes' and item['kind'] == 'project':
            default_statuses(db, ident)
    return require(db,table,ident)


class Handler(BaseHTTPRequestHandler):
    def send_json(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/state':
            with connect() as db:
                self.send_json({table: [dict(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY id')] for table in ['nodes','statuses','tasks','comments']})
            return
        assets = {'/':'index.html','/app.js':'app.js','/style.css':'style.css','/favicon.svg':'favicon.svg','/images/stoic-bust.png':'images/stoic-bust.png'}
        if path not in assets:
            self.send_error(404)
            return
        file = ROOT / 'static' / assets[path]
        body = file.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type',mimetypes.guess_type(file)[0] or 'application/octet-stream')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def write_request(self):
        # JSON-only writes and same-origin checks protect a local instance from other sites.
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host',''):
            self.send_json({'error':'Origin not allowed'},403)
            return
        if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
            self.send_json({'error':'Send application/json'},415)
            return
        try:
            length = int(self.headers.get('Content-Length','0'))
            if length < 0 or length > 65536:
                raise Invalid('Request is too large')
            data = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(data,dict):
                raise Invalid('Expected a JSON object')
            with connect() as db:
                result = mutate(db,self.command,urlparse(self.path).path,data)
            self.send_json(result,201 if self.command=='POST' else 200)
        except (ValueError,TypeError,sqlite3.IntegrityError) as exc:
            self.send_json({'error':str(exc)},400)

    do_POST = write_request
    do_PATCH = write_request
    do_DELETE = write_request


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--db',type=Path,default=DB_PATH)
    parser.add_argument('--empty',action='store_true',help='Start a new database without sample data')
    args = parser.parse_args()
    DB_PATH = args.db.resolve()
    init_db(not args.empty)
    print(f'Thread is ready at http://{args.host}:{args.port}',flush=True)
    try:
        ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
    except KeyboardInterrupt:
        print('\nSee you next time.')
