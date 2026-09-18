import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

import app


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = app.DB_PATH
        app.DB_PATH = Path(self.temp.name) / 'test.db'
        app.init_db()

    def tearDown(self):
        app.DB_PATH = self.previous
        self.temp.cleanup()

    def write(self, table, data=None, ident=None, method=None):
        with app.connect() as db:
            return app.mutate(db, method or ('PATCH' if ident else 'POST'),
                              '/api/' + table + (f'/{ident}' if ident else ''), data or {})

    def create_task(self, **overrides):
        return self.write('tasks', dict(project_id=2, status_id=1, title='A new task', **overrides))

    def test_seed_is_idempotent_and_persistent(self):
        self.assertEqual(self.create_task()['title'], 'A new task')
        app.init_db()
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0],16)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_nested_tasks_and_cycle_rejection(self):
        parent = self.create_task()
        child = self.create_task(parent_id=parent['id'])
        grandchild = self.create_task(parent_id=child['id'])
        with self.assertRaisesRegex(app.Invalid,'inside itself'):
            self.write('tasks',{'parent_id':grandchild['id']},parent['id'])
        self.write('tasks',ident=parent['id'],method='DELETE')
        with app.connect() as db:
            self.assertIsNone(db.execute('SELECT id FROM tasks WHERE id=?',(grandchild['id'],)).fetchone())

    def test_cross_project_status_and_parent_are_rejected(self):
        with self.assertRaisesRegex(app.Invalid,'Status must belong'):
            self.write('tasks',dict(project_id=3,status_id=1,title='Wrong status'))
        with self.assertRaisesRegex(app.Invalid,'Parent task must belong'):
            self.write('tasks',dict(project_id=3,status_id=5,title='Wrong parent',parent_id=1))

    def test_nested_containers_move_and_delete(self):
        space = self.write('nodes',dict(kind='space',name='Nested',parent_id=2))
        project = self.write('nodes',dict(kind='project',name='Inside',parent_id=space['id']))
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM statuses WHERE project_id=?',(project['id'],)).fetchone()[0],4)
        with self.assertRaisesRegex(app.Invalid,'contain itself'):
            self.write('nodes',{'parent_id':project['id']},2)
        self.write('nodes',{'parent_id':8},space['id'])
        self.write('nodes',ident=space['id'],method='DELETE')
        with app.connect() as db:
            self.assertIsNone(db.execute('SELECT id FROM nodes WHERE id=?',(project['id'],)).fetchone())

    def test_delete_space_cascades_tasks_and_statuses(self):
        self.write('nodes',ident=1,method='DELETE')
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks WHERE project_id IN (2,3)').fetchone()[0],0)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_custom_statuses_and_completion(self):
        custom = self.write('statuses',dict(project_id=2,name='Shipped',color='green',is_done=1))
        t = self.create_task()
        self.write('tasks',{'status_id':custom['id']},t['id'])
        with self.assertRaisesRegex(app.Invalid,'Move tasks'):
            self.write('statuses',ident=custom['id'],method='DELETE')
        self.write('tasks',{'status_id':1},t['id'])
        self.write('statuses',ident=custom['id'],method='DELETE')

    def test_task_comments_persist_and_cascade(self):
        comment = self.write('comments', {'task_id': 1, 'author': 'You', 'body': 'Started the first pass.'})
        self.assertEqual(comment['task_id'], 1)
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM comments WHERE task_id=1').fetchone()[0], 1)
        self.write('comments', ident=comment['id'], method='DELETE')
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM comments WHERE task_id=1').fetchone()[0], 0)
        second = self.write('comments', {'task_id': 1, 'body': 'This should disappear with the task.'})
        self.write('tasks', ident=1, method='DELETE')
        with app.connect() as db:
            self.assertIsNone(db.execute('SELECT id FROM comments WHERE id=?', (second['id'],)).fetchone())

    def test_comment_validation(self):
        for data in [{'task_id': 1, 'body': ' '}, {'task_id': 999, 'body': 'Missing task'}, {'task_id': 1, 'body': []}]:
            with self.subTest(data=data), self.assertRaises(app.Invalid):
                self.write('comments', data)

    def test_last_status_cannot_be_removed(self):
        p = self.write('nodes',dict(name='Fresh',kind='project'))
        with app.connect() as db:
            ids=[r['id'] for r in db.execute('SELECT id FROM statuses WHERE project_id=?',(p['id'],))]
        for ident in ids[:-1]:
            self.write('statuses',ident=ident,method='DELETE')
        with self.assertRaisesRegex(app.Invalid,'at least one'):
            self.write('statuses',ident=ids[-1],method='DELETE')

    def test_validation(self):
        for data in [{'title':' '},{'due_date':'2026-02-30'},{'due_date':'tomorrow'},
                     {'priority':'critical'},{'description':[]},{'parent_id':True}]:
            with self.subTest(data=data), self.assertRaises(app.Invalid):
                self.write('tasks',data,1)

    def test_empty_does_not_destroy_existing_data(self):
        app.init_db(False)
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0],15)
        app.DB_PATH=Path(self.temp.name)/'empty.db'
        app.init_db(False)
        app.init_db(True)
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM nodes').fetchone()[0],0)

    def test_http_crud_assets_and_origin(self):
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
        try:
            conn.request('GET','/api/state')
            response=conn.getresponse()
            self.assertEqual(response.status,200)
            self.assertEqual(len(json.loads(response.read())['tasks']),15)
            conn.request('POST','/api/tasks',json.dumps(dict(project_id=2,status_id=1,title='HTTP task')),{'Content-Type':'application/json'})
            response=conn.getresponse()
            self.assertEqual(response.status,201)
            ident=json.loads(response.read())['id']
            conn.request('PATCH',f'/api/tasks/{ident}',json.dumps({'title':'Saved'}),{'Content-Type':'application/json'})
            response=conn.getresponse()
            self.assertEqual(json.loads(response.read())['title'],'Saved')
            conn.request('POST','/api/tasks','{}',{'Content-Type':'application/json','Origin':'https://other.example'})
            response=conn.getresponse()
            self.assertEqual(response.status,403)
            response.read()
            conn.request('DELETE',f'/api/tasks/{ident}','{}',{'Content-Type':'application/json'})
            response=conn.getresponse()
            self.assertEqual(response.status,200)
            response.read()
            for path,expected in [('/',200),('/style.css',200),('/app.js',200),('/app.py',404),('/../thread.db',404)]:
                conn.request('GET',path)
                response=conn.getresponse()
                self.assertEqual(response.status,expected)
                response.read()
        finally:
            conn.close()
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
