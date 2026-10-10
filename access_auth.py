"""Seleciona login por código ou o SSO Microsoft previamente disponível."""
import email_auth,sso_auth

def provider():return email_auth if email_auth.enabled() else sso_auth
def enabled():return provider().enabled()
def current(env,connect):return provider().current(env,connect)
def handle(env,respond,connect):return provider().handle(env,respond,connect)
def setup(connect):
    email_auth.setup(connect)
    sso_auth.setup(connect)
