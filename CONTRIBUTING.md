# Contributing

Thanks for your interest in Gemma Chat. The project is maintained by its owner,
[@tnptm](https://github.com/tntpm).

## Pull request policy

Pull requests are welcome from contributors. The project owner, [@tnptm](https://github.com/tntpm),
reviews all pull requests and decides whether to accept and merge them. A pull
request is accepted only with the project owner's approval.

## Reporting bugs and suggesting improvements

Before opening an issue, check whether a similar one already exists. Include
enough detail to reproduce a bug, such as the affected page or API endpoint,
steps to reproduce it, expected and actual behavior, and relevant error output.
Do not include passwords, tokens, private conversation contents, or other
secrets.

## Development setup

See the [README](README.md) for the complete local setup. The application has a
Django backend in `backend/` and a Next.js frontend in `frontend/`; Ollama is
needed to exercise model-backed chat functionality.

Useful checks before sharing a change:

```sh
cd backend
python manage.py check
```

```sh
cd frontend
npm run build
```

Run each command from its indicated directory. The repository currently has no
dedicated automated test suite, so include any manual verification relevant to
your change when reporting it.

## Contribution expectations

- Keep changes focused and consistent with the existing Django and Next.js
  patterns.
- Preserve the local-first design and user-scoped access to conversations.
- Do not commit `.env` files, credentials, database contents, logs, or other
  private runtime data.
- For changes to authentication, authorization, or request handling, consider
  security implications and describe the behavior you verified.
