"""Reuso de conexão por requisição e pool curto PostgreSQL; nenhuma identidade é cacheada entre requisições."""
from contextvars import ContextVar
from queue import LifoQueue,Empty,Full
import time
_SCOPE=ContextVar('cj_request_connection',default=None)
_POOL=LifoQueue(maxsize=4)

def close(db):
    try:(db.connection if hasattr(db,'connection') else db).close()
    except Exception:pass

def checkout(factory):
    while True:
        try:db,stamp=_POOL.get_nowait()
        except Empty:return factory(),time.monotonic()
        if time.monotonic()-stamp<45 and not db.connection.closed and not getattr(db.connection,'broken',False):return db,stamp
        close(db)

class Scope:
    def __init__(self,factory,method):self.factory=factory;self.method=method;self.db=None;self.created=0;self.depth=0;self.failed=False;self.memo={}
    def enter(self):
        if self.db is None:self.db,self.created=checkout(self.factory)
        self.depth+=1;return self.db
    def leave(self,kind):
        self.failed=self.failed or kind is not None;self.depth-=1
        if self.depth==0:
            raw=self.db.connection if hasattr(self.db,'connection') else self.db
            try:raw.rollback() if self.failed else raw.commit()
            finally:self.failed=False
    def finish(self):
        if self.db is None:return
        try:
            raw=self.db.connection if hasattr(self.db,'connection') else self.db;raw.rollback()
            if hasattr(self.db,'connection') and not raw.closed and not getattr(raw,'broken',False) and time.monotonic()-self.created<45:
                try:_POOL.put_nowait((self.db,self.created));return
                except Full:pass
        except Exception:pass
        close(self.db)

class Lease:
    def __init__(self,scope):self.scope=scope
    def __enter__(self):return self.scope.enter()
    def __exit__(self,kind,value,trace):self.scope.leave(kind)

def install(server):
    if getattr(server,'_cj_fast_installed',False):return
    server._cj_fast_installed=True;original=server.connect
    def connect():
        current=_SCOPE.get();return Lease(current) if current else original()
    server.connect=connect
    old_current=server.sso_auth.current;old_session=server.session
    def current(env,conn):
        scope=_SCOPE.get()
        if scope and scope.method=='GET':
            if 'identity' not in scope.memo:scope.memo['identity']=old_current(env,conn)
            return scope.memo['identity']
        return old_current(env,conn)
    def session(env):
        scope=_SCOPE.get()
        if scope and scope.method=='GET':
            if 'admin' not in scope.memo:scope.memo['admin']=old_session(env)
            return scope.memo['admin']
        return old_session(env)
    server.sso_auth.current=current;server.session=session;server._cj_original_connect=original

def begin(server,method):
    scope=Scope(server._cj_original_connect,method);return scope,_SCOPE.set(scope)
def end(scope,token):
    try:scope.finish()
    finally:_SCOPE.reset(token)
