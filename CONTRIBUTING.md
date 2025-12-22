# Contributing

> [!WARNING]  
> This guide is a work in progress and may not be complete.

- [Style](#Style)
- [Workflow](#Workflow)
- [Running Locally](#Running-Locally)

This is a basic contributing guide and is a work in progress.

## Style

Formatting (this is done by you):

- Black (.py)
- Prettier (.yml;.yaml;.json;.md)

Linting (this is checked by actions):

- Flake8 (.py)
- ShellCheck (.sh)

## Workflow

1. Fork the repository.
2. Create a branch in your fork!
3. Make your changes.
4. Test your changes.
5. Commit and push your changes.
6. Create a PR to this repository.
7. Verify the tests pass, otherwise resolve.
8. Make sure to keep your branch up-to-date.

## Running Locally

To run actions locally you can use act: https://github.com/nektos/act

1. Install `act`: https://nektosact.com/installation/index.html
2. Create a `.secrets` file with: `GITHUB_TOKEN="ghp_xxx"`
3. Run `act -j test`

Note: You need to have your current commit pushed as this makes a tag on GitHub to the current sha.
This means the `test` will most likely fail on a third-party PR since the automatic GITHUB_TOKEN won't have write access to content.

To see all available jobs run: `act -l`

For advanced using with things like secrets, variables and context see: https://nektosact.com/usage/index.html

You should also review the options from `act --help`

Note, the `.env`, `.secrets` and `.vars` files are automatically sourced with no extra options.
To source `event.json` you need to run act with `act -e event.json`
