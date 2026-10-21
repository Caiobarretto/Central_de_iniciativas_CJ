"""SQLite for local tests; PostgreSQL for durable free hosting."""
import os
import sqlite3
from urllib.parse import parse_qs, urlsplit


def postgres_sql(query):
    query = query.replace('salt BLOB', 'salt BYTEA').replace('expires REAL', 'expires DOUBLE PRECISION').replace('until REAL', 'until DOUBLE PRECISION')
    if query == 'BEGIN IMMEDIATE':
        # Both writes and login attempts are serialized across connections.
        return 'LOCK TABLE state, attempts IN EXCLUSIVE MODE'
    if query == 'INSERT OR REPLACE INTO admin VALUES (1,?,?,?)':
        return ('INSERT INTO admin (id,username,salt,digest) VALUES (1,%s,%s,%s) '
                'ON CONFLICT (id) DO UPDATE SET username=EXCLUDED.username, salt=EXCLUDED.salt, digest=EXCLUDED.digest')
    if query == 'INSERT OR REPLACE INTO attempts VALUES (?,?,?)':
        return ('INSERT INTO attempts (key,count,until) VALUES (%s,%s,%s) '
                'ON CONFLICT (key) DO UPDATE SET count=EXCLUDED.count, until=EXCLUDED.until')
    return query.replace('?', '%s')


class PostgresDatabase:
    def __init__(self, url):
        import psycopg
        parsed=urlsplit(url)
        if parsed.scheme not in ['postgres','postgresql']:
            raise RuntimeError('DATABASE_URL deve conter somente a URL PostgreSQL copiada do Neon.')
        ssl=parse_qs(parsed.query).get('sslmode',['require'])[0]
        if ssl not in ['require','verify-ca','verify-full']:
            raise RuntimeError('Use uma conexão PostgreSQL com sslmode=require ou verificação de certificado.')
        self.connection=psycopg.connect(url, sslmode=ssl, connect_timeout=20)

    def execute(self, query, params=()):
        return self.connection.execute(postgres_sql(query), params)

    def __enter__(self):
        return self

    def __exit__(self, kind, value, trace):
        try:
            if kind is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()


def connect_database(local_path):
    url=os.environ.get('DATABASE_URL','').strip()
    if url:
        return PostgresDatabase(url)
    if os.environ.get('RENDER') or os.environ.get('REQUIRE_POSTGRES','').lower()=='true':
        raise RuntimeError('Configure DATABASE_URL no Render. O plano gratuito precisa de um banco externo para conservar os dados.')
    con=sqlite3.connect(local_path, timeout=30)
    con.execute('PRAGMA journal_mode=WAL')
    return con
