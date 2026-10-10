"""Modo padrão: seleção de perfil. Modos anteriores são opções explícitas."""
import os
import email_auth,sso_auth,profile_auth

def provider():
    mode=os.environ.get('ACCESS_MODE','profile').strip().lower()
    if mode=='profile':return profile_auth
    if mode=='email':return email_auth
    if mode=='microsoft':return sso_auth
    raise ValueError('ACCESS_MODE inválido. Use profile, email ou microsoft.')
def enabled():return provider().enabled()
def current(env,connect):return provider().current(env,connect)
def handle(env,respond,connect):return provider().handle(env,respond,connect)
def setup(connect):
    email_auth.setup(connect)
    sso_auth.setup(connect)
    profile_auth.setup(connect)
