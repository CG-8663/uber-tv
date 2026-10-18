# Security policy

## Reporting a problem

Please report security problems privately, never in a public issue.

- **Use GitHub's private vulnerability reporting:** the repository's
  **Security** tab → **Report a vulnerability**.
- **While the repository is private,** contact the maintainer,
  [@marcho78](https://github.com/marcho78), directly on GitHub.

Say what you found, how to reproduce it (the guide's version or commit, the
steps, and what happens), and what you think it allows. A proof of concept
helps. Please don't test against other people's computers, servers or
accounts.

You'll get an answer, and a fix is prepared in private and released before
the details are shared. You're credited in the changelog unless you'd rather
not be.

## What's in scope

- **The guide** and everything in this repository: its commands, the agent skill, and the helpers in `bin/`.
- **The sandbox for apps with code:**
  - the network checks, and the picture and video relays;
  - storage and secrets;
  - what only the user may do (installing, turning on, signing in, Developer mode).
- **The apps catalog:** signatures, checks and proof of origin.
- **The phone remote:** pairing, tokens and its commands.
- **Files the guide writes:** permissions, safe writes, and clean-ups that delete only what the guide wrote.

## What isn't

- Problems in a third-party app's own code or servers. Report those to its maker.
- Omarchy, Hyprland, Quickshell, bubblewrap or other system software. Report those upstream.
- The limits the documentation already states. For example, the phone remote speaks plain HTTP on your local network ([Permissions and security](docs/security.md)). Better ideas for them are welcome as ordinary issues.

## Supported versions

Only the latest commit on `main` gets security fixes.
