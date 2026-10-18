# Accounts

An example app with code (API 4) that signs in to an online account that
lists your servers, the way Plex or Emby Connect do, and has you choose one
while signing in (`app.json`'s `server.fromSignIn`). It offers both ways to
sign in: a code you enter on the account's site, or your username and
password typed in Uber TV's own box.

- **The account** (`accounts.example.com`) gives an account token, then lists
  your servers, each with a token of its own.
- **`flow.offer_servers()`** shows them to the guide by a handle the app makes
  up (here the account's id for each), never a token. You choose the server,
  then one of its addresses or one you type for it.
- **The app keeps only that server's token** (`flow.keep`), and Uber TV keeps
  the server you chose with the sign-in.

Try it offline: `fixtures.json` plays the account service and the "Office"
server. A password sign-in takes the username and password from a secrets
file (only you may read it):

```bash
P=~/.config/omarchy/plugins/marcho78.om-pg
E=$P/apps/sdk/examples/accounts
printf '{"@username": "alex", "@password": "example-password"}' > /tmp/accounts-secrets.json
chmod 600 /tmp/accounts-secrets.json
python3 $P/bin/om-pg-apps try $E --fixtures $E/fixtures.json --secrets /tmp/accounts-secrets.json --allow-write \
  --call 'signIn:{"how":"password","server":"office","url":"http://192.168.1.20:32400/"}' --call home
```

(`--allow-write` lets its sign-in POST reach the account, here a fixture.) `try` lists the servers the account offers, chooses the one the call names
(`server`, then `url` or `typed`; else the first's first address), and prints
how the sign-in ended and the server it kept.
