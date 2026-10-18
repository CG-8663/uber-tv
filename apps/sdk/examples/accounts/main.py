"""An example of an account that lists your servers (app.json's
server.fromSignIn), signed in to with a code or a username and password.

The account service (accounts.example.com) gives an account token, then
lists your servers, each with its own token. The app offers them to the
guide by a handle of its own (never a token); you choose one and how to
reach it; the app keeps only that server's token.

Offline with try: fixtures.json plays the account service and the server
(see README.md)."""

from uber_tv import app, fetch, get_json, storage, secret, Screen, Row, Item, FetchError
import uber_tv

ACCOUNTS = "https://accounts.example.com"


def account_token(flow):
    """The account's token: from what you typed, or a code you enter on the
    account's site; None if it didn't work (said) or was called off"""
    if flow.how == "password":
        typed = flow.credentials()
        if typed is None:
            return None
        r = fetch(ACCOUNTS + "/login", method="POST", json={"username": typed[0], "password": typed[1]})
        typed = None   # let go of it at once
        if r.status != 200:
            flow.done(False, "The account didn't take that username and password.")
            return None
        return r.json().get("token")
    pin = fetch(ACCOUNTS + "/pins", method="POST").json()
    flow.show_code(pin["code"], url=ACCOUNTS + "/link", expires=600)
    while flow.sleep(2):
        try:
            token = get_json(ACCOUNTS + "/pins/" + pin["id"]).get("token")
        except FetchError:
            continue
        if token:
            return token
    return None


@app.sign_in
def sign_in(flow):
    account = account_token(flow)
    if not account:
        return
    servers = get_json(ACCOUNTS + "/servers", headers={"X-Account-Token": account})
    tokens = {s["id"]: s["token"] for s in servers}
    chosen = flow.offer_servers([{"handle": s["id"], "label": s["name"], "urls": s["addresses"]} for s in servers])
    if chosen is None:
        return   # called off: nothing to say
    token = tokens[chosen["handle"]]   # that server's own, and only it
    r = fetch(uber_tv.server.rstrip("/") + "/identity", headers={"X-Server-Token": token})
    if r.status != 200:
        flow.done(False, "That server didn't answer (it said " + str(r.status) + ").")
        return
    name = r.json().get("name") or "your server"
    flow.keep("token", token)
    storage.put("serverName", name, server=True)
    flow.done(True, "Signed in to " + name + ".")


@app.home
def home():
    if not secret("token") or not uber_tv.server:
        return Screen("Accounts", rows=[], empty="Sign in (, then Sign in) to choose your server.")
    name = storage.get("serverName") or "Your server"
    return Screen("Accounts", rows=[Row("server", "Your server", [Item("server", name, subtitle=uber_tv.server, kind="info")])])


app.run()
