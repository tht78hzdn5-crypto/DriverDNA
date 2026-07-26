name: Gemini Assistant

on:
  issue_comment:
    types: [created]
  issues:
    types: [opened]

permissions:
  contents: write
  issues: write
  pull-requests: write

jobs:
  gemini:
    # Runs whenever `@gemini-cli` is mentioned in an issue or PR comment
    if: contains(github.event.comment.body, '@gemini-cli') || contains(github.event.issue.body, '@gemini-cli')
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Run Gemini CLI Action
        uses: google-github-actions/run-gemini-cli@v1
        with:
          gemini_api_key: ${{ secrets.GEMINI_API_KEY }}
